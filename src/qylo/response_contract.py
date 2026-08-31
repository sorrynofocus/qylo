# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.07.30
# The response contract: how a model reply is labeled, validated, and parsed.
#
# Purpose:
# Every reply is classified as exactly one of four kinds, and that label is
# what decides whether anything is allowed to execute:
#
#   ANS      grounded answer from the knowledge base   never executes
#   GENERAL  ungrounded answer, model's own knowledge  never executes
#   CMD      non-destructive command                   needs --exe
#   UNSAFE   destructive/privileged/ambiguous command  needs --exe --yolo
#
# cli.py::apply_exe_request enforces those rules; this module only produces
# the label. Keeping the two apart means a parsing change can't accidentally
# widen what runs.
#
# There are two ways a label gets produced, and both live here on purpose:
#
#   ContractResponse    the reliable path. A Pydantic schema handed to
#                       create_agent as response_format, so the API validates
#                       the label rather than the model writing it as prose.
#   parse_model_response the fallback. Reads the old "ANS:"/"CMD:" text
#                       prefixes off raw message text. Still needed because
#                       local llama.cpp backends can't be relied on to honor
#                       forced structured output - it is NOT dead code.
#
# Both funnel into the same ModelResponse dataclass, so cli.py never has to
# care which path ran.
#
# Note for readers: the description= strings on ContractResponse fields are
# prompt content, NOT documentation. The model reads them. Edit accordingly.
#
# Usage examples (see README for granular details):
#
# Structured path (what RagAssistant.answer tries first):
# response = contract_response_to_model_response(result["structured_response"])
#
# Text fallback (when no structured response came back):
# response = parse_model_response("CMD: rg -w 'flogger' data/")
# response.kind     -> ResponseKind.COMMAND
# response.command  -> "rg -w 'flogger' data/"
#
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from qylo import string_table


class ResponseKind(Enum):
    """
    Labels the model must use at the start of every response.

    when responses are built, we need to determine if this is an answer to
    an ungrounded query, a potential command from RAG with unsafe deterrence from
    unsafe and insecure commands (disabled for now)
    """

    ANSWER = "ANS"
    COMMAND = "CMD"
    UNSAFE = "UNSAFE"
    GENERAL = "GENERAL"


@dataclass
class ModelResponse:
    """
    Parsed model response using the ANS/CMD/UNSAFE contract.

    Parameters:
        kind: The model's declared response type.
        content: Human-readable answer text, command text, or safety reason.
        command: Executable command when kind is COMMAND, or the proposed
            blocked command when kind is UNSAFE.
        raw_text: Original model output for debugging and learning.
    """

    kind: ResponseKind
    content: str
    command: str | None
    raw_text: str


class ContractResponse(BaseModel):
    """Schema-enforced final answer for create_agent's structured-output path.

    Replaces the free-text ANS:/GENERAL:/CMD:/UNSAFE: label convention with a
    tool-call schema the API validates directly, instead of relying on the
    model to write the label correctly as prose. See RagAssistant.answer()
    (assistant.py) for how this is combined with the text-label fallback below for
    backends that can't reliably produce a forced structured response.

    For readers new to Pydantic: BaseModel is roughly Pydantic's equivalent
    of a C# record with data-annotation validation built in - it declares
    typed fields and validates/coerces incoming data against them
    automatically. Field(description=...) attaches metadata to a field
    (here, text the LLM itself reads as part of the tool schema - see the
    comment above, not just documentation). @model_validator (below) is
    Pydantic's hook for custom validation logic that runs after normal
    field validation, similar to IValidatableObject.Validate() in C#.
    """

    # The description= text on each field below is not a code comment for
    # humans - it is sent to the model as part of the tool-call schema and
    # doubles as the instruction the model reads when deciding how to fill in
    # that field. Edit it as prompt content, not as documentation.
    kind: Literal["ANS", "GENERAL", "CMD", "UNSAFE"] = Field(
        description=(
            "Classify by INTENT FIRST, before considering whether anything was retrieved. "
            "If the user is requesting an executable command or tool invocation, this is "
            "ALWAYS 'CMD' or 'UNSAFE' - never 'ANS' or 'GENERAL', even when retrieved "
            "context was used to compose the command. 'CMD': non-destructive command, "
            "command field must be set. 'UNSAFE': destructive/privileged/ambiguous command, "
            "command field must be set and content explains the safety reason. Only use "
            "'ANS' (grounded) or 'GENERAL' (ungrounded) for genuine questions that are not "
            "command requests - command must be null for both."
        )
    )
    content: str = Field(description="Answer text (ANS/GENERAL) or safety reason (UNSAFE/CMD).")
    command: str | None = Field(
        default=None,
        description="The actual executable command text. Required (non-null) when kind is "
        "CMD or UNSAFE; must be null when kind is ANS or GENERAL.",
    )

    @model_validator(mode="after")
    def _validate_command_matches_kind(self) -> ContractResponse:
        """Enforce that command is set if and only if kind requires one.

        CMD/UNSAFE must carry a non-null command; ANS/GENERAL must not. This
        is more than input validation: ToolStrategy defaults handle_errors to
        True (see the response_format=ToolStrategy(...) in
        RagAssistant.__init__, assistant.py), so a ValueError raised here is caught
        by create_agent and fed back to the model as a retry prompt rather
        than surfacing as a crash. That makes this validator a self-
        correction mechanism, not just a guard rail.
        """

        if self.kind in ("CMD", "UNSAFE") and not self.command:
            raise ValueError(string_table.MSG_CONTRACT_COMMAND_REQUIRED.format(kind=self.kind))
        if self.kind in ("ANS", "GENERAL") and self.command:
            raise ValueError(string_table.MSG_CONTRACT_COMMAND_FORBIDDEN.format(kind=self.kind))
        return self


def contract_response_to_model_response(resp: ContractResponse) -> ModelResponse:
    """
    Convert a validated structured response into the app's existing ModelResponse shape.

    Lets callers like cli.py keep working against the same ModelResponse
    dataclass regardless of which path produced the answer: the new
    schema-validated ContractResponse path (this function), or the older
    text-label parsing fallback (parse_model_response below).
    """

    return ModelResponse(
        kind=ResponseKind(resp.kind),
        content=resp.content,
        command=resp.command,
        raw_text=resp.model_dump_json(),
    )


def parse_model_response(text: str) -> ModelResponse:
    """Parse the model's labeled response into a ModelResponse.

    Expected model formats:
        ANS: explanation text
        GENERAL: explanation text (not grounded in context)
        CMD: single executable command
        UNSAFE: safety reason
        COMMAND: proposed command

    If the model forgets a label, the response is treated as ANS so normal
    question-answering stays forgiving. Execution logic still refuses unlabeled
    answers because they are not COMMAND responses.
    """

    stripped = text.strip()
    upper = stripped.upper()

    if upper.startswith(f"{ResponseKind.COMMAND.value}:"):
        command = text_after_label(stripped, ResponseKind.COMMAND.value)
        return ModelResponse(
            kind=ResponseKind.COMMAND,
            content=command,
            command=command,
            raw_text=text,
        )

    if upper.startswith(f"{ResponseKind.UNSAFE.value}:"):
        unsafe_body = text_after_label(stripped, ResponseKind.UNSAFE.value)
        reason, command = parse_unsafe_body(unsafe_body)
        return ModelResponse(
            kind=ResponseKind.UNSAFE,
            content=reason,
            command=command,
            raw_text=text,
        )

    if upper.startswith(f"{ResponseKind.ANSWER.value}:"):
        answer = text_after_label(stripped, ResponseKind.ANSWER.value)
        return ModelResponse(
            kind=ResponseKind.ANSWER,
            content=answer,
            command=None,
            raw_text=text,
        )

    if upper.startswith(f"{ResponseKind.GENERAL.value}:"):
        general = text_after_label(stripped, ResponseKind.GENERAL.value)
        return ModelResponse(
            kind=ResponseKind.GENERAL,
            content=general,
            command=None,
            raw_text=text,
        )

    return ModelResponse(
        kind=ResponseKind.ANSWER,
        content=stripped,
        command=None,
        raw_text=text,
    )


def text_after_label(text: str, prefix: str) -> str:
    """Return text after a top-level contract prefix such as CMD:."""

    return text[len(prefix) + 1 :].strip()


def parse_unsafe_body(body: str) -> tuple[str, str | None]:
    """Split an UNSAFE response into safety reason and optional command.

    The model is asked to put the proposed command on a separate line:
        COMMAND: shutdown /s /t 0

    Everything else remains part of the safety reason shown to the user.
    """

    reason_lines: list[str] = []
    command: str | None = None

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("COMMAND:"):
            command = stripped[len("COMMAND:") :].strip()
            continue
        if stripped:
            reason_lines.append(stripped)

    return "\n".join(reason_lines).strip(), command
