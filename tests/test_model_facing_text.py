# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.30
#
# Purpose:
# Golden capture of the model-facing text, taken from the code as it stood on 2026-08-30,
# BEFORE the Phase C split. Each of these can change model behaviour while the Python
# still looks equivalent, so they are pinned exactly. Covered, and this is the whole list:
#
#   1. system_prompt() - the bundled prompt text, and custom-path loading
#   2. the retrieval tool's name and description (its docstring IS the description)
#   3. the three ContractResponse field descriptions (sent as the tool-call schema)
#   4. the retrieval result format, including the "(Safety: unsafe)" marker
#
# NOT covered here: string_table's user-facing output (printed to the person, never sent
# to the model) and any prompt text a caller supplies at runtime via --system-prompt.
#
# If a test here fails, the model-facing text changed. That is either a mistake during a
# move - fix the code, not the expectation - or a deliberate prompt edit, in which case
# re-measure with tools/score_contract.py before updating the value here. Never
# regenerate these from the refactored implementation; that would make them pass by
# construction and measure nothing.
#
# Run:
# uv run pytest tests/test_model_facing_text.py

from __future__ import annotations

import hashlib

from qylo import string_table
from qylo.assistant import system_prompt
from qylo.response_contract import ContractResponse
from qylo.retrieval import build_retrieval_tool

# Hashes captured 2026-08-30 from the pre-split code.
TOOL_DESCRIPTION_SHA = "e91fc70faf6b925cd375845e135bccd30ad86746dabc14d9c976a7f0c26b7155"
TOOL_DESCRIPTION_LENGTH = 877
SYSTEM_PROMPT_SHA = "e17169099382b34839e399901a6f946e6006d1fb33b7abc39c093d7b2ca73d80"
SYSTEM_PROMPT_LENGTH = 4594
SCHEMA_DESCRIPTION_SHA = {
    "kind": "f85383691e6fd4d3dd58b08b069fb601d61be49588ec42370c50a1de296badee",
    "content": "08a18c6ab142a5e2025bd60819aad430f4e473866fa807285ba981bc66e87cea",
    "command": "54aace3ffa90bf50f3efbded0749db86bd7229fee904c66bd28365bab3d303d0",
}


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class FakeDocument:
    """Stands in for a LangChain Document: only .page_content and .metadata are read."""

    def __init__(self, page_content: str, metadata: dict) -> None:
        self.page_content = page_content
        self.metadata = metadata


class FakeVectorStore:
    """Stands in for InMemoryVectorStore: the tool only calls similarity_search."""

    def __init__(self, docs: list[FakeDocument]) -> None:
        self.docs = docs

    def similarity_search(self, query: str, k: int = 4) -> list[FakeDocument]:
        return self.docs[:k]


# --- the retrieval tool's identity and description ---------------------------


def test_retrieval_tool_name_is_unchanged():
    # The model calls the tool by this name; renaming it is a prompt change.
    tool = build_retrieval_tool(FakeVectorStore([]), 4)

    assert tool.name == "retrieve_document_context"


def test_retrieval_tool_description_is_unchanged():
    # @tool uses the function docstring as the description sent to the model.
    tool = build_retrieval_tool(FakeVectorStore([]), 4)

    assert len(tool.description) == TOOL_DESCRIPTION_LENGTH
    assert sha256_of(tool.description) == TOOL_DESCRIPTION_SHA


# --- the bundled system prompt -----------------------------------------------


def test_bundled_system_prompt_is_unchanged():
    # The largest single piece of model-facing text in the project, and the one
    # that carries the intent-first classification rules. TROUBLESHOOT.MD records
    # three separate prompt edits that were argued well and measured worse, so an
    # accidental change here during a file move must not pass silently.
    prompt = system_prompt()

    assert len(prompt) == SYSTEM_PROMPT_LENGTH
    assert sha256_of(prompt) == SYSTEM_PROMPT_SHA


def test_system_prompt_trailing_newlines_are_stripped():
    prompt = system_prompt()

    assert not prompt.endswith("\n")


def test_custom_system_prompt_path_is_loaded_instead(tmp_path):
    # --system-prompt <file> must actually replace the bundled prompt.
    custom = tmp_path / "custom_prompt.txt"
    custom.write_text("Answer only in haiku.\n\n", encoding="utf-8")

    assert system_prompt(custom) == "Answer only in haiku."


# --- the structured-output schema the model fills in -------------------------


def test_contract_schema_field_descriptions_are_unchanged():
    # Field(description=...) text is sent to the model as part of the tool schema -
    # it is prompt content, not documentation.
    properties = ContractResponse.model_json_schema()["properties"]

    for field, expected_sha in SCHEMA_DESCRIPTION_SHA.items():
        assert sha256_of(properties[field]["description"]) == expected_sha


# --- the retrieved text that lands in the model's context --------------------


def test_retrieval_result_format_is_unchanged():
    docs = [
        FakeDocument(
            "flogger writes structured logs.",
            {"source": "C:/kb/flogger.md", "safety": "unsafe"},
        ),
        FakeDocument(
            "Rotation is configured per handler.",
            {"source": "C:/kb/notes.md", "page": 2},
        ),
    ]
    tool = build_retrieval_tool(FakeVectorStore(docs), 4)

    result = tool.invoke({"query": "flogger"})

    # Captured verbatim on 2026-08-30. The "(Safety: unsafe)" marker in particular is
    # what RagAssistant.answer() scans for when it promotes CMD to UNSAFE, and page
    # numbers are cited one-based from zero-based metadata.
    assert result == (
        "[1] Source: flogger.md (Safety: unsafe)\n"
        "flogger writes structured logs.\n"
        "\n"
        "[2] Source: notes.md, page 3\n"
        "Rotation is configured per handler."
    )


def test_no_match_returns_the_fallback_sentinel():
    tool = build_retrieval_tool(FakeVectorStore([]), 4)

    result = tool.invoke({"query": "nothing relevant"})

    assert result == string_table.MSG_NO_RELEVANT_CONTEXT
    assert result == "No relevant context found in the knowledge base."
