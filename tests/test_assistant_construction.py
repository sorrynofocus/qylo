# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.31
#
# Purpose:
# Closes the coverage gap the Phase C review demonstrated: before this file, no test
# ever called the real RagAssistant.__init__. tests/test_assistant_answer.py builds the
# object with __new__, and tests/test_execution_gate.py substitutes a FakeAssistant, so
# a lost import or broken create_agent wiring after the split would have passed the
# whole suite. Two things are pinned here:
#
#   1. RagAssistant.__init__ - the real constructor, with only create_agent replaced by
#      a recorder. Asserts the model, the retrieval tool, k, the system prompt and the
#      ToolStrategy schema all reach the agent.
#   2. cli.build_assistant() - the extracted wiring. Asserts the pipeline runs in order
#      and that -k and --system-prompt actually arrive at the assistant.
#
# Only construction boundaries are replaced (create_agent, the ingestion and embedding
# functions, build_chat_model). The functions under review stay real. No model call, no
# network, no cost.
#
# Run:
# uv run pytest tests/test_assistant_construction.py

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from langchain.agents.structured_output import ToolStrategy

from qylo import assistant as assistant_module
from qylo import cli, execution, settings, string_table
from qylo.assistant import RagAssistant, system_prompt
from qylo.response_contract import ContractResponse, ModelResponse, ResponseKind
from qylo.settings import (
    DEFAULT_MAX_AGENT_ATTEMPTS,
    DEFAULT_MAX_AGENT_STEPS,
    DEFAULT_RETRIEVAL_K,
)


class FakeVectorStore:
    """Stands in for InMemoryVectorStore, and records the k it was searched with."""

    def __init__(self) -> None:
        self.searched_with_k: list[int] = []

    def similarity_search(self, query: str, k: int = 4) -> list:
        self.searched_with_k.append(k)
        return []


def record_create_agent(monkeypatch) -> dict:
    """
    Replace assistant.create_agent with a recorder and return what it captured.

    create_agent is the only substitution these constructor tests make: it is an
    external boundary (it compiles a real LangGraph graph around a real model),
    not the code under review. Everything else in __init__ runs for real.
    """

    recorded: dict = {}

    def fake_create_agent(model, tools, system_prompt=None, response_format=None):
        recorded["model"] = model
        recorded["tools"] = tools
        recorded["system_prompt"] = system_prompt
        recorded["response_format"] = response_format
        return object()

    monkeypatch.setattr(assistant_module, "create_agent", fake_create_agent)
    return recorded


# --- the real RagAssistant.__init__ ------------------------------------------


def test_constructor_hands_the_model_straight_to_the_agent(monkeypatch):
    recorded = record_create_agent(monkeypatch)
    model = object()

    RagAssistant(vector_store=FakeVectorStore(), model=model)

    assert recorded["model"] is model


def test_constructor_gives_the_agent_the_retrieval_tool(monkeypatch):
    # A lost import or a dropped tool list leaves the agent unable to search at
    # all, which no golden text test would notice.
    recorded = record_create_agent(monkeypatch)

    RagAssistant(vector_store=FakeVectorStore(), model=object())

    assert [tool.name for tool in recorded["tools"]] == ["retrieve_document_context"]


def test_constructor_binds_retrieval_k_into_the_tool(monkeypatch):
    # -k is only observable through the tool's closure, so invoke it and see what
    # k the vector store was searched with.
    recorded = record_create_agent(monkeypatch)
    store = FakeVectorStore()

    RagAssistant(vector_store=store, model=object(), retrieval_k=7)
    recorded["tools"][0].invoke({"query": "flogger"})

    assert store.searched_with_k == [7]


def test_constructor_sends_the_bundled_system_prompt(monkeypatch):
    recorded = record_create_agent(monkeypatch)

    RagAssistant(vector_store=FakeVectorStore(), model=object())

    assert recorded["system_prompt"] == system_prompt()


def test_constructor_sends_a_custom_system_prompt_when_one_is_given(monkeypatch, tmp_path):
    recorded = record_create_agent(monkeypatch)
    custom = tmp_path / "custom_prompt.txt"
    custom.write_text("Answer only in haiku.\n", encoding="utf-8")

    RagAssistant(vector_store=FakeVectorStore(), model=object(), system_prompt_path=custom)

    assert recorded["system_prompt"] == "Answer only in haiku."


def test_constructor_forces_the_contract_schema(monkeypatch):
    # Losing response_format silently drops the structured-output path and leaves
    # every answer to the text-parsing fallback.
    recorded = record_create_agent(monkeypatch)

    RagAssistant(vector_store=FakeVectorStore(), model=object())

    response_format = recorded["response_format"]
    assert isinstance(response_format, ToolStrategy)
    assert response_format.schema is ContractResponse


def test_constructor_defaults_come_from_settings(monkeypatch):
    record_create_agent(monkeypatch)

    assistant = RagAssistant(vector_store=FakeVectorStore(), model=object())

    assert assistant.retrieval_k == DEFAULT_RETRIEVAL_K
    assert assistant.max_agent_steps == DEFAULT_MAX_AGENT_STEPS
    assert assistant.max_agent_attempts == DEFAULT_MAX_AGENT_ATTEMPTS


# --- cli.build_assistant(): the extracted wiring ------------------------------


def build_assistant_with_stubs(monkeypatch, retrieval_k: int, system_prompt_path: Path | None):
    """
    Run the real cli.build_assistant() against stand-ins and report what it did.

    Returns (stages, kwargs, expected): the pipeline calls in the order they
    happened, the keyword arguments RagAssistant was constructed with, and the
    exact objects the stand-ins handed back.

    `expected` exists so a caller can assert object *identity* rather than
    non-nullness. An earlier version of this helper kept the store to itself, so
    the only available assertion was `is not None` - and replacing the forwarded
    store with a fresh `object()` in build_assistant passed the whole suite while
    silently discarding the built index.
    """

    import qylo.documents as documents
    import qylo.retrieval as retrieval

    stages: list[str] = []
    captured: dict = {}
    embeddings = object()
    vector_store = object()

    def scan(path):
        stages.append(f"scan:{path}")
        return ["doc.md"]

    def load(paths):
        stages.append(f"load:{list(paths)}")
        return ["loaded"]

    def split(docs):
        stages.append(f"split:{list(docs)}")
        return ["chunk"]

    def embed():
        stages.append("embeddings")
        return embeddings

    def vectors(chunks, embeds):
        stages.append(f"vectors:{list(chunks)}:{embeds is embeddings}")
        return vector_store

    class FakeAssistant:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(documents, "scan_document_paths", scan)
    monkeypatch.setattr(documents, "load_documents", load)
    monkeypatch.setattr(documents, "split_documents", split)
    monkeypatch.setattr(retrieval, "build_embeddings", embed)
    monkeypatch.setattr(retrieval, "build_vectors", vectors)
    monkeypatch.setattr(assistant_module, "RagAssistant", FakeAssistant)
    monkeypatch.setattr(cli, "build_chat_model", lambda **kwargs: "the model")

    cli.build_assistant(Path("kb"), retrieval_k, system_prompt_path)
    return stages, captured, {"vector_store": vector_store, "embeddings": embeddings}


def test_build_assistant_runs_the_pipeline_in_order(monkeypatch):
    stages, _, _ = build_assistant_with_stubs(monkeypatch, 4, None)

    assert stages == [
        f"scan:{Path('kb')}",
        "load:['doc.md']",
        "split:['loaded']",
        "embeddings",
        "vectors:['chunk']:True",
    ]


def test_build_assistant_passes_the_vector_store_and_model_through(monkeypatch):
    # Identity, not non-nullness: the assistant must get the index that was just
    # built, not merely some object.
    _, captured, expected = build_assistant_with_stubs(monkeypatch, 4, None)

    assert captured["vector_store"] is expected["vector_store"]
    assert captured["model"] == "the model"


def test_build_assistant_forwards_the_k_flag(monkeypatch):
    _, captured, _ = build_assistant_with_stubs(monkeypatch, 9, None)

    assert captured["retrieval_k"] == 9


def test_build_assistant_forwards_the_system_prompt_flag(monkeypatch, tmp_path):
    custom = tmp_path / "custom_prompt.txt"

    _, captured, _ = build_assistant_with_stubs(monkeypatch, 4, custom)

    assert captured["system_prompt_path"] == custom


# --- main() -> build_assistant: the flags a user actually typed ---------------
#
# The tests above call build_assistant directly, so they establish that the helper
# forwards its own parameters - not that parse_args and main put the user's flags
# into them. Those are different claims, and the gap between them is invisible
# when a flag's default equals the value a test happens to use: replacing
# `args.k` with a literal 4 in main passed all 81 tests, because -k defaults to 4
# and nothing else asserted on it. These run the real main() instead.


def run_main_and_capture_assistant(monkeypatch, argv: list[str]):
    """
    Run the real cli.main() against stand-ins and report what reached the assistant.

    Returns (kwargs, scanned): the keyword arguments RagAssistant was constructed
    with, and the paths the document scan was asked for.

    Real argument parsing, real flag resolution, real build_assistant. Only the
    ingestion, embedding and model boundaries are replaced. The reply is an
    ANSWER with no command, and run_command is replaced with a failing stub, so
    nothing can reach a shell even if the gates were to break.
    """

    import qylo.documents as documents
    import qylo.retrieval as retrieval

    captured: dict = {}
    scanned: list = []

    class FakeAssistant:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def answer(self, question: str) -> ModelResponse:
            return ModelResponse(
                kind=ResponseKind.ANSWER, content="an answer", command=None, raw_text=""
            )

    def scan(path):
        scanned.append(path)
        return ["doc.md"]

    monkeypatch.setattr(sys, "argv", ["qylo", *argv])

    # Keep a developer's real .env out of the test, exactly as the gate tests do.
    monkeypatch.setattr(cli, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv(string_table.ENV_MODEL_PROVIDER, "azure")
    monkeypatch.delenv(string_table.ENV_EXECUTE_COMMANDS, raising=False)

    monkeypatch.setattr(documents, "scan_document_paths", scan)
    monkeypatch.setattr(documents, "load_documents", lambda paths: ["loaded"])
    monkeypatch.setattr(documents, "split_documents", lambda docs: ["chunk"])
    monkeypatch.setattr(retrieval, "build_embeddings", lambda: object())
    monkeypatch.setattr(retrieval, "build_vectors", lambda chunks, embeddings: object())
    monkeypatch.setattr(assistant_module, "RagAssistant", FakeAssistant)
    monkeypatch.setattr(cli, "build_chat_model", lambda **kwargs: object())
    monkeypatch.setattr(
        execution, "run_command", lambda command: pytest.fail(f"main() ran a command: {command!r}")
    )

    cli.main()
    return captured, scanned


def test_main_forwards_a_non_default_k_to_the_assistant(monkeypatch):
    captured, _ = run_main_and_capture_assistant(monkeypatch, ["what is flogger", "-k", "9"])

    assert captured["retrieval_k"] == 9


def test_main_uses_the_settings_default_when_k_is_not_given(monkeypatch):
    captured, _ = run_main_and_capture_assistant(monkeypatch, ["what is flogger"])

    assert captured["retrieval_k"] == DEFAULT_RETRIEVAL_K


def test_main_forwards_a_custom_system_prompt_to_the_assistant(monkeypatch, tmp_path):
    custom = tmp_path / "custom_prompt.txt"

    captured, _ = run_main_and_capture_assistant(
        monkeypatch, ["what is flogger", "--system-prompt", str(custom)]
    )

    assert captured["system_prompt_path"] == custom


def test_main_defaults_the_system_prompt_to_none(monkeypatch):
    # None is what tells RagAssistant to load the bundled prompt.
    captured, _ = run_main_and_capture_assistant(monkeypatch, ["what is flogger"])

    assert captured["system_prompt_path"] is None


def test_main_forwards_the_document_source_to_the_scan(monkeypatch, tmp_path):
    # Same class of gap as -k above: --doc/--documents are parsed, but nothing
    # asserted they reach ingestion rather than the default folder.
    captured, scanned = run_main_and_capture_assistant(
        monkeypatch, ["what is flogger", "--doc", str(tmp_path / "one.md")]
    )

    assert scanned == [tmp_path / "one.md"]


def test_main_scans_the_default_folder_when_no_source_is_given(monkeypatch):
    _, scanned = run_main_and_capture_assistant(monkeypatch, ["what is flogger"])

    assert scanned == [settings.DEFAULT_DOCS_PATH]
