# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.30
#
# Purpose:
# Pins the two execution gates. The inner gate (execution.apply_exe_request) decides what
# a given response kind is allowed to run. The outer gate (cli.main) decides whether
# execution was authorized at all - --exe or CHATBOT_EXECUTE_COMMANDS=true - and forwards
# --yolo to the inner one. They fail differently and are connected only inside main(), so
# both are tested, and the outer tests cover UNSAFE as well as CMD: a CMD-only outer test
# cannot notice main() forwarding yolo=True regardless of the flag. Nothing here reaches
# a shell.
#
# Patch target note: apply_exe_request resolves run_command in execution.py's namespace,
# so that is where the recorder is installed. Patching cli.run_command would silently
# stop working after the Phase C split - the name no longer lives there.
#
# Run:
# uv run pytest tests/test_execution_gate.py

from __future__ import annotations

import sys

from qylo import cli, execution, string_table
from qylo.response_contract import ModelResponse, ResponseKind

SAFE_COMMAND = "rg -w flogger data/"
DESTRUCTIVE_COMMAND = "shutdown /s /t 0"


def response(kind: ResponseKind, command: str | None) -> ModelResponse:
    """Build a ModelResponse without repeating the four fields in every test."""

    return ModelResponse(kind=kind, content="reason or answer text", command=command, raw_text="")


def record_run_command(monkeypatch) -> list[str]:
    """
    Replace execution.run_command with a recorder and return the list it appends to.

    monkeypatch is pytest's built-in "swap this out, put it back after the test"
    helper. Replacing run_command is the only substitution the inner-gate tests
    make - the gate logic under test stays real.
    """

    executed: list[str] = []
    monkeypatch.setattr(execution, "run_command", lambda command: executed.append(command))
    return executed


# --- inner gate: the complete apply_exe_request matrix -----------------------
#
# 4 response kinds x --yolo on/off x command present/absent = 16 combinations,
# all of them below. Only three may ever execute. The table is the specification:
# read it top to bottom and it states the whole policy in one place.

GATE_MATRIX = [
    # (kind, command, yolo, should_execute)
    (ResponseKind.ANSWER, None, False, False),
    (ResponseKind.ANSWER, None, True, False),
    (ResponseKind.ANSWER, DESTRUCTIVE_COMMAND, False, False),
    (ResponseKind.ANSWER, DESTRUCTIVE_COMMAND, True, False),
    (ResponseKind.GENERAL, None, False, False),
    (ResponseKind.GENERAL, None, True, False),
    (ResponseKind.GENERAL, DESTRUCTIVE_COMMAND, False, False),
    (ResponseKind.GENERAL, DESTRUCTIVE_COMMAND, True, False),
    (ResponseKind.COMMAND, None, False, False),
    (ResponseKind.COMMAND, None, True, False),
    (ResponseKind.COMMAND, SAFE_COMMAND, False, True),
    (ResponseKind.COMMAND, SAFE_COMMAND, True, True),
    (ResponseKind.UNSAFE, None, False, False),
    (ResponseKind.UNSAFE, None, True, False),
    (ResponseKind.UNSAFE, DESTRUCTIVE_COMMAND, False, False),
    (ResponseKind.UNSAFE, DESTRUCTIVE_COMMAND, True, True),
]


def test_the_whole_gate_matrix(monkeypatch):
    for kind, command, yolo, should_execute in GATE_MATRIX:
        executed = record_run_command(monkeypatch)

        execution.apply_exe_request(response(kind, command), yolo=yolo)

        expected = [command] if should_execute else []
        # The message names the row, so a failure says which combination broke.
        assert executed == expected, (
            f"{kind.value} command={command!r} yolo={yolo}: "
            f"expected {'execution' if should_execute else 'no execution'}, got {executed}"
        )


def test_exactly_three_combinations_are_allowed_to_execute():
    # A guard on the table itself: if someone widens the policy by editing a row,
    # this count changes and says so.
    assert sum(1 for *_, should_execute in GATE_MATRIX if should_execute) == 3
    assert len(GATE_MATRIX) == 16


# --- the Windows single-quote rewrite ----------------------------------------


def test_single_quoted_segments_become_double_quoted():
    # cmd.exe does not treat single quotes as argument delimiters, so a POSIX-style
    # quoted command would search for the quotes themselves.
    rewritten = execution.normalize_command_for_shell("rg -w 'flogger' data/")

    assert rewritten == 'rg -w "flogger" data/'


def test_unquoted_command_is_left_alone():
    assert execution.normalize_command_for_shell(SAFE_COMMAND) == SAFE_COMMAND


# --- outer gate: the real main(), with only its surroundings replaced --------
#
# apply_exe_request assumes authorization already happened, so the matrix above
# cannot catch main() calling it unconditionally, ignoring its result, or passing
# the wrong yolo. These tests run the real main(): real argument parsing, real
# flag/env resolution, the real `if execute_flag:` branch, and the real
# apply_exe_request. Only the work around it is replaced - ingestion, embedding,
# model construction - plus the shell call.


class FakeDoc:
    """Stands in for a LangChain Document: main() only reads .page_content."""

    def __init__(self, text: str) -> None:
        self.page_content = text


def run_main_with_stubs(
    monkeypatch,
    argv: list[str],
    execute_env: str | None = None,
    reply: ModelResponse | None = None,
) -> list[str]:
    """
    Run the real cli.main() against stand-ins and return what reached the shell.

    Parameters:
        argv: Command line, without the program name.
        execute_env: Value for CHATBOT_EXECUTE_COMMANDS, or None to unset it.
        reply: What the assistant answers with. Defaults to a safe CMD response.

    cli.build_assistant() imports the pipeline functions from qylo.documents,
    qylo.retrieval and qylo.assistant at call time, so patching them on those
    modules is what the deferred imports pick up.
    """

    import qylo.assistant as assistant_module
    import qylo.documents as documents
    import qylo.retrieval as retrieval

    answer_with = reply if reply is not None else response(ResponseKind.COMMAND, SAFE_COMMAND)

    class FakeAssistant:
        """Stands in for RagAssistant: main() constructs it, then calls answer()."""

        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def answer(self, question: str) -> ModelResponse:
            return answer_with

    monkeypatch.setattr(sys, "argv", ["qylo", *argv])

    # Keep a developer's real .env out of the test: load_dotenv would otherwise
    # supply CHATBOT_EXECUTE_COMMANDS and silently change what is being tested.
    monkeypatch.setattr(cli, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv(string_table.ENV_MODEL_PROVIDER, "azure")
    if execute_env is None:
        monkeypatch.delenv(string_table.ENV_EXECUTE_COMMANDS, raising=False)
    else:
        monkeypatch.setenv(string_table.ENV_EXECUTE_COMMANDS, execute_env)

    monkeypatch.setattr(documents, "scan_document_paths", lambda path: ["doc.md"])
    monkeypatch.setattr(documents, "load_documents", lambda paths: [FakeDoc("flogger writes logs")])
    monkeypatch.setattr(documents, "split_documents", lambda docs: [FakeDoc("flogger writes logs")])
    monkeypatch.setattr(retrieval, "build_embeddings", lambda: object())
    monkeypatch.setattr(retrieval, "build_vectors", lambda chunks, embeddings: object())
    monkeypatch.setattr(assistant_module, "RagAssistant", FakeAssistant)
    monkeypatch.setattr(cli, "build_chat_model", lambda **kwargs: object())

    executed = record_run_command(monkeypatch)
    cli.main()
    return executed


# The outer opt-in: --exe or CHATBOT_EXECUTE_COMMANDS=true, nothing else.


def test_main_does_not_execute_a_command_without_opt_in(monkeypatch):
    assert run_main_with_stubs(monkeypatch, ["find flogger"]) == []


def test_main_executes_a_command_with_the_exe_flag(monkeypatch):
    assert run_main_with_stubs(monkeypatch, ["find flogger", "--exe"]) == [SAFE_COMMAND]


def test_main_executes_a_command_with_the_env_opt_in(monkeypatch):
    executed = run_main_with_stubs(monkeypatch, ["find flogger"], execute_env="true")

    assert executed == [SAFE_COMMAND]


def test_main_ignores_a_non_true_env_value(monkeypatch):
    assert run_main_with_stubs(monkeypatch, ["find flogger"], execute_env="yes") == []


# --yolo forwarding: only visible through UNSAFE, because CMD ignores yolo.
# A CMD-only outer test passes even if main() hardcodes yolo=True.


def test_main_blocks_unsafe_with_exe_but_no_yolo(monkeypatch):
    executed = run_main_with_stubs(
        monkeypatch,
        ["shut it down", "--exe"],
        reply=response(ResponseKind.UNSAFE, DESTRUCTIVE_COMMAND),
    )

    assert executed == []


def test_main_executes_unsafe_with_exe_and_yolo(monkeypatch):
    executed = run_main_with_stubs(
        monkeypatch,
        ["shut it down", "--exe", "--yolo"],
        reply=response(ResponseKind.UNSAFE, DESTRUCTIVE_COMMAND),
    )

    assert executed == [DESTRUCTIVE_COMMAND]


def test_main_blocks_unsafe_when_yolo_is_passed_without_any_opt_in(monkeypatch):
    # --yolo alone is not authorization: the outer gate is still closed.
    executed = run_main_with_stubs(
        monkeypatch,
        ["shut it down", "--yolo"],
        reply=response(ResponseKind.UNSAFE, DESTRUCTIVE_COMMAND),
    )

    assert executed == []


def test_main_blocks_unsafe_with_env_opt_in_but_no_yolo(monkeypatch):
    executed = run_main_with_stubs(
        monkeypatch,
        ["shut it down"],
        execute_env="true",
        reply=response(ResponseKind.UNSAFE, DESTRUCTIVE_COMMAND),
    )

    assert executed == []


def test_main_executes_unsafe_with_env_opt_in_and_yolo(monkeypatch):
    executed = run_main_with_stubs(
        monkeypatch,
        ["shut it down", "--yolo"],
        execute_env="true",
        reply=response(ResponseKind.UNSAFE, DESTRUCTIVE_COMMAND),
    )

    assert executed == [DESTRUCTIVE_COMMAND]


def test_main_never_executes_an_answer_even_with_exe_and_yolo(monkeypatch):
    executed = run_main_with_stubs(
        monkeypatch,
        ["what is flogger", "--exe", "--yolo"],
        reply=response(ResponseKind.ANSWER, DESTRUCTIVE_COMMAND),
    )

    assert executed == []
