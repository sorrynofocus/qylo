# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.01
# Opt-in measurement of what a single question actually cost: calls, bytes, tokens, time, retries.
#
# Purpose:
# Without this you are guessing about the expensive half of the pipeline.
#
# Work is bucketed into four stages, only one of which costs money:
#
#   INGESTION   load/split documents      local, free
#   EMBEDDING   build the vector store    local, free
#   MODEL_CALL  chat completion round     billable, and the one to watch
#   RETRIEVAL   vector store lookup       local, free
#
# Two token numbers get reported because only one is always available.
# est_input_tokens is a tiktoken cl100k_base estimate that works for every
# provider; actual_* tokens come from provider-reported usage_metadata and in
# practice show up on Azure only. Both are shown, actuals win when present.
#
# Everything here is off unless --usage is passed. cli.py builds a
# TelemetrySession only in that case and threads None everywhere otherwise -
# measure(), build_chat_model(telemetry=...) and RagAssistant(telemetry=...)
# all accept None and no-op, so the un-instrumented run pays nothing.
#
# Previews are whitespace-collapsed and cut to 80 chars, and are deliberately
# taken from the user's question or the retrieval query only - never from the
# system prompt or retrieved document text. A usage log is meant to be
# shareable.
#
# Usage examples (see README for granular details):
#
# Print the per-stage table after the answer:
# uv run qna-chatbot "What is flogger?" --usage
#
# Also append one JSON line per event, for comparing runs (requires --usage):
# uv run qna-chatbot "What is flogger?" --usage --usagelog runs.log
#
# Instrument a local stage from cli.py (harmless when telemetry is None):
# with measure(telemetry, Stage.EMBEDDING) as metrics:
#     metrics.payload_bytes = ...
#


"""
Two independent instrumentation layers feed one TelemetrySession:
    - TelemetryCallbackHandler hooks langchain_core's callback boundary
      (on_chat_model_start/on_llm_end/on_tool_start/on_tool_end) to see
      logical model calls and tool calls, including provider-reported
      usage_metadata.
    - httpx_event_hooks hooks the actual wire requests/responses, including
      any silent retry the OpenAI SDK performs underneath a single logical
      call, which the callback boundary alone can't see.

Both layers correlate through TelemetrySession's "currently open call"
slot: RagAssistant.answer() is synchronous, so a model call's
on_chat_model_start/on_llm_end pair always brackets its own httpx
request(s) in the same call stack.
"""

from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

import httpx
import tiktoken
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage

from qna_chatbot import string_table

# tiktoken has no llama.cpp-specific encoding available, so cl100k_base is
# used as a same-order-of-magnitude estimate for every provider; actual
# token counts (Azure only, via usage_metadata) are reported separately and
# take precedence whenever both are shown.
# https://github.com/openai/tiktoken
# https://mdstudio.app/cl100k-base-tokenizer
_TOKENIZER_ENCODING = "cl100k_base"
_PROMPT_ROLES = {"system", "human"}


class Stage(str, Enum):
    """
    Pipeline stage a TelemetryEvent belongs to.
    """

    INGESTION = "ingestion"
    EMBEDDING = "embedding"
    MODEL_CALL = "model_call"
    RETRIEVAL = "retrieval"


def sha256_short(text: str) -> str:
    """
    First 12 hex chars of a sha256 digest, for cross-call/cross-run content identity.
    """

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def redact_preview(text: str, max_chars: int = 80) -> str:
    """
    Collapse whitespace and truncate text to a short, log-safe preview.
    """

    collapsed = " ".join(text.split())
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[: max_chars - 1] + "…"


def estimate_tokens(text: str) -> int:
    """
    Best-effort BPE token estimate via tiktoken's cl100k_base encoding.
    BPE - Byte Pair Encoding - is the same algorithm used by OpenAI and 
    Azure to count tokens, BUT the actual tokenization is provider-specific. 
    """

    encoding = tiktoken.get_encoding(_TOKENIZER_ENCODING)
    return len(encoding.encode(text))


def _message_role(message: BaseMessage) -> str:
    return message.type


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return str(content)


@dataclass
class TelemetryEvent:
    """One recorded unit of work: a local pipeline stage, a model call, or a retrieval.

    Parameters:
        stage: Pipeline stage this event belongs to.
        sequence: Monotonic per-session ordinal, for stable ordering in the log.
        timestamp: ISO-8601 timestamp of when the event was recorded.
        duration_ms: Wall-clock duration of the measured unit of work.
        payload_bytes: Wire-measured bytes for MODEL_CALL; computed from local
            content length for INGESTION/EMBEDDING; always 0 for RETRIEVAL.
        prompt_bytes: System+human message bytes (MODEL_CALL only).
        context_bytes: Tool-result/retrieved-context message bytes (MODEL_CALL only).
        est_input_tokens: tiktoken cl100k_base estimate (MODEL_CALL only).
        actual_input_tokens: Provider-reported input tokens, or None outside MODEL_CALL.
        actual_output_tokens: Provider-reported output tokens, or None outside MODEL_CALL.
        actual_total_tokens: Provider-reported total tokens, or None outside MODEL_CALL.
        http_requests: Wire attempt count for this call; >1 means a retry happened.
        content_hash: sha256_short() of the measured content.
        preview: Redacted, <=80 char preview (never system-prompt or retrieved-document text).
        final: True when this MODEL_CALL didn't request the retrieval tool (it
            produced the final answer, whether via a structured tool call or
            plain text) - not simply "tool_calls is empty", since a forced
            structured-output schema delivers the final answer as a tool call too.
    """

    stage: Stage
    sequence: int
    timestamp: str
    duration_ms: float
    payload_bytes: int
    prompt_bytes: int | None = None
    context_bytes: int | None = None
    est_input_tokens: int | None = None
    actual_input_tokens: int | None = None
    actual_output_tokens: int | None = None
    actual_total_tokens: int | None = None
    http_requests: int = 0
    content_hash: str = ""
    preview: str = ""
    final: bool = False

    def to_json_line(self) -> str:
        payload = asdict(self)
        payload["stage"] = self.stage.value
        return json.dumps(payload, ensure_ascii=False)


@dataclass
class _StageMetrics:
    """Mutable metrics a `measure()` caller fills in during its `with` block."""

    payload_bytes: int = 0
    content_for_hash: str = ""
    preview_text: str = ""


class TelemetrySession:
    """Accumulates TelemetryEvents for one CLI invocation."""

    def __init__(self) -> None:
        self._events: list[TelemetryEvent] = []
        self._sequence = 0
        self._open_call: TelemetryEvent | None = None

    def next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def record(self, event: TelemetryEvent) -> None:
        self._events.append(event)

    def open_call(self, event: TelemetryEvent) -> None:
        """Mark a MODEL_CALL event as in-flight so httpx hooks can attribute wire requests to it."""

        self._open_call = event

    def close_call(self) -> None:
        self._open_call = None

    @property
    def open_call_event(self) -> TelemetryEvent | None:
        return self._open_call

    def stage_summary(self) -> dict[Stage, dict[str, Any]]:
        """Aggregate recorded events per stage: call count, bytes, tokens, latency, retries."""

        summary: dict[Stage, dict[str, Any]] = {}
        for event in self._events:
            bucket = summary.setdefault(
                event.stage,
                {
                    "calls": 0,
                    "bytes": 0,
                    "est_tokens": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "has_actual_tokens": False,
                    "duration_ms": 0.0,
                    "retries": 0,
                },
            )
            bucket["calls"] += 1
            bucket["bytes"] += event.payload_bytes
            bucket["est_tokens"] += event.est_input_tokens or 0
            if event.actual_total_tokens is not None:
                bucket["has_actual_tokens"] = True
                bucket["input_tokens"] += event.actual_input_tokens or 0
                bucket["output_tokens"] += event.actual_output_tokens or 0
                bucket["total_tokens"] += event.actual_total_tokens or 0
            bucket["duration_ms"] += event.duration_ms
            bucket["retries"] += max(event.http_requests - 1, 0)
        return summary

    def stat_summary(self) -> str:
        """
        Display per stage report to the console: tokens in/out, total tokens, bytes, duration, and retries.
        """

        lines = [string_table.MSG_USAGE_SUMMARY_TITLE, string_table.MSG_USAGE_SUMMARY_HEADER]

        for stage in Stage:
            call_bucket = self.stage_summary().get(stage)

            if call_bucket is None:
                continue

            na = string_table.MSG_USAGE_SUMMARY_NA
            tok_in = str(call_bucket["input_tokens"]) if call_bucket["has_actual_tokens"] else na
            tok_out = str(call_bucket["output_tokens"]) if call_bucket["has_actual_tokens"] else na
            tok_total = str(call_bucket["total_tokens"]) if call_bucket["has_actual_tokens"] else na

            lines.append(
                f"{stage.value:<10} {call_bucket['calls']:>5} {call_bucket['bytes']:>9} {call_bucket['est_tokens']:>8} "
                f"{tok_in:>7} {tok_out:>7} {tok_total:>7} {call_bucket['duration_ms']:>8.0f} {call_bucket['retries']:>7}"
            )

        return "\n".join(lines)

    def write_log(self, path: Path) -> None:
        """Append each recorded event as one JSON line, for cross-run comparison."""

        with path.open("a", encoding="utf-8") as handle:
            for event in self._events:
                handle.write(event.to_json_line())
                handle.write("\n")


@contextmanager
def measure(session: TelemetrySession | None, stage: Stage) -> Iterator[_StageMetrics]:
    """
    Time a local pipeline stage (ingestion/embedding) and record one TelemetryEvent.

    Parameters:
        session: Active TelemetrySession, or None when --usage wasn't passed.
        stage: INGESTION or EMBEDDING (the two local, always-free stages).

    Always yields a _StageMetrics the caller can populate (payload_bytes,
    content_for_hash, preview_text); populating it is harmless even when
    session is None, so call sites don't need a separate `if telemetry`
    branch around the wrapped work itself.
    """

    metrics = _StageMetrics()
    start = time.perf_counter()
    yield metrics
    if session is None:
        return
    duration_ms = (time.perf_counter() - start) * 1000
    session.record(
        TelemetryEvent(
            stage=stage,
            sequence=session.next_sequence(),
            timestamp=datetime.now().isoformat(timespec="seconds"),
            duration_ms=duration_ms,
            payload_bytes=metrics.payload_bytes,
            content_hash=sha256_short(metrics.content_for_hash) if metrics.content_for_hash else "",
            preview=redact_preview(metrics.preview_text) if metrics.preview_text else "",
        )
    )


class TelemetryCallbackHandler(BaseCallbackHandler):
    """Bridges create_agent's LangGraph callback events into MODEL_CALL/RETRIEVAL TelemetryEvents.

    Parameters:
        session: TelemetrySession to record events into.
        retrieval_tool_name: Name of the real (non-structured-output) tool
            bound to the agent, e.g. "retrieve_document_context". Needed to
            tell "this call still has work to do" apart from "this call
            produced the final answer" — see the `final` note on
            on_llm_end() below.
    """

    def __init__(self, session: TelemetrySession, retrieval_tool_name: str) -> None:
        self.session = session
        self.retrieval_tool_name = retrieval_tool_name
        self._call_start = 0.0
        self._tool_start = 0.0
        self._tool_query = ""

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._call_start = time.perf_counter()
        flat_messages = messages[0] if messages else []

        prompt_bytes = 0
        context_bytes = 0
        text_parts: list[str] = []
        human_preview = ""
        for message in flat_messages:
            content = _message_text(message)
            text_parts.append(content)
            if _message_role(message) in _PROMPT_ROLES:
                prompt_bytes += len(content.encode("utf-8"))
                if _message_role(message) == "human" and not human_preview:
                    human_preview = content
            else:
                context_bytes += len(content.encode("utf-8"))

        joined = "\n".join(text_parts)
        event = TelemetryEvent(
            stage=Stage.MODEL_CALL,
            sequence=self.session.next_sequence(),
            timestamp=datetime.now().isoformat(timespec="seconds"),
            duration_ms=0.0,
            payload_bytes=prompt_bytes + context_bytes,
            prompt_bytes=prompt_bytes,
            context_bytes=context_bytes,
            est_input_tokens=estimate_tokens(joined),
            content_hash=sha256_short(joined),
            # human_preview only, with no fallback to joined. joined holds every
            # message - system prompt and retrieved chunks included - which is
            # correct for the token estimate and hash above, but must never
            # reach preview: --usagelog writes previews to a file meant to be
            # shared. No human turn (or an empty question) leaves this "", and
            # an empty preview is the right failure here.
            preview=redact_preview(human_preview),
        )
        self.session.open_call(event)

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        event = self.session.open_call_event
        if event is None:
            return
        event.duration_ms = (time.perf_counter() - self._call_start) * 1000

        message = None
        if response.generations and response.generations[0]:
            message = response.generations[0][0].message
        usage = getattr(message, "usage_metadata", None) if message is not None else None
        if usage:
            event.actual_input_tokens = usage.get("input_tokens")
            event.actual_output_tokens = usage.get("output_tokens")
            event.actual_total_tokens = usage.get("total_tokens")
        tool_calls = getattr(message, "tool_calls", None) if message is not None else None
        # A forced structured-output schema (ToolStrategy) delivers the final
        # answer AS a tool call too - to an artificial tool named after the
        # schema class - so "tool_calls is empty" is never true in this
        # pipeline. "final" instead means "this call didn't request the real
        # retrieval tool", whether it answered as a structured tool call or
        # (fallback path) as plain text.
        event.final = not any(call.get("name") == self.retrieval_tool_name for call in (tool_calls or []))

        self.session.record(event)
        self.session.close_call()

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._tool_start = time.perf_counter()
        self._tool_query = input_str

    def on_tool_end(self, output: Any, *, run_id: Any, parent_run_id: Any = None, **kwargs: Any) -> None:
        result_text = str(output)
        self.session.record(
            TelemetryEvent(
                stage=Stage.RETRIEVAL,
                sequence=self.session.next_sequence(),
                timestamp=datetime.now().isoformat(timespec="seconds"),
                duration_ms=(time.perf_counter() - self._tool_start) * 1000,
                payload_bytes=0,
                content_hash=sha256_short(result_text),
                preview=redact_preview(self._tool_query),
            )
        )


def httpx_event_hooks(session: TelemetrySession) -> dict[str, list[Any]]:
    """Build httpx event hooks that attribute wire requests to the session's open MODEL_CALL.

    Sees every actual wire request/response, including any silent retry the
    OpenAI SDK performs underneath a single logical .invoke() call, which
    langchain_core's callback boundary (one on_llm_end per logical call) can't.
    """

    def on_request(request: httpx.Request) -> None:
        event = session.open_call_event
        if event is None:
            return
        event.http_requests += 1
        try:
            event.payload_bytes += len(request.content)
        except httpx.RequestNotRead:
            pass

    def on_response(response: httpx.Response) -> None:
        event = session.open_call_event
        if event is None:
            return
        content_length = response.headers.get("content-length")
        if content_length is not None:
            event.payload_bytes += int(content_length)

    return {"request": [on_request], "response": [on_response]}
