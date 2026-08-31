# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.07.25
# Agentic RAG CLI assistant to help build command line runs/cli for internal built tools or general query assistant.
#
# Purpose:
# A utility to help create and  run internal tools cli and typical general queries.
#
# Usage examples (see README for granular details):
#
# Ask against all supported files in `data/documents`:
# uv run qylo "What is flogger and what logging features does it support?"
#
# Use a different document folder or file:
# uv run qylo "What does this document say?" --documents path\to\knowledge-base
#
# Ask something the knowledge base doesn't cover
# uv run qylo "Who wrote the novel Moby Dick?"
#

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

from qylo import console, settings, string_table
from qylo.execution import apply_exe_request, normalize_command_for_shell
from qylo.model_provider import ModelProvider, build_chat_model, get_model_provider

if TYPE_CHECKING:  # import-time cost stays out of the real run - see build_assistant()
    from qylo.assistant import RagAssistant


def parse_args() -> argparse.Namespace:
    """
    Your friendly command-line argument parser.
    TODO: This will change in future for click
    """

    parser = argparse.ArgumentParser(
        prog="qylo",
        description=string_table.CLI_DESCRIPTION,
    )
    parser.add_argument("question", help=string_table.HELP_QUESTION)

    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--documents",
        type=Path,
        help=string_table.HELP_DOCUMENTS.format(default_path=settings.DEFAULT_DOCS_PATH),
    )
    source_group.add_argument(
        "--doc",
        type=Path,
        help=string_table.HELP_DOC,
    )

    parser.add_argument(
        "-k",
        type=int,
        default=settings.DEFAULT_RETRIEVAL_K,
        help=string_table.HELP_RETRIEVAL_K,
    )
    parser.add_argument(
        "--exe",
        action="store_true",
        help=string_table.HELP_EXE,
    )
    parser.add_argument(
        "--yolo",
        action="store_true",
        help=string_table.HELP_YOLO,
    )
    parser.add_argument(
        "--system-prompt",
        type=Path,
        default=None,
        help=string_table.HELP_SYSTEM_PROMPT,
    )
    return parser.parse_args()


def build_assistant(
    source_path: Path,
    retrieval_k: int,
    system_prompt_path: Path | None,
) -> RagAssistant:
    """
    Run the ingestion -> embedding -> model pipeline and return a ready assistant.

    Parameters:
        source_path: File or folder to scan for source documents.
        retrieval_k: Chunks the retrieval tool returns per search (-k).
        system_prompt_path: Custom prompt file, or None for the bundled default.

    Every stage prints as it goes, because ingestion and embedding take long
    enough that silence reads as a hang.
    """

    # Import the heavier RAG dependencies after argument parsing so --help
    # stays fast and easy to understand. It gets SLLLOWW!
    # Leave this here, lot's math -heh
    from qylo.assistant import RagAssistant
    from qylo.documents import load_documents, scan_document_paths, split_documents
    from qylo.retrieval import build_embeddings, build_vectors

    ingestion = string_table.TAG_INGESTION
    embedding = string_table.TAG_EMBEDDING
    local = string_table.TAG_LOCAL

    console.print_stage(ingestion, local, string_table.MSG_SCANNING.format(path=source_path))
    document_paths = scan_document_paths(source_path)
    console.print_stage(ingestion, local, string_table.MSG_FOUND_DOCUMENTS.format(count=len(document_paths)))

    console.print_stage(ingestion, local, string_table.MSG_LOADING_DOCUMENTS)
    docs = load_documents(document_paths)
    console.print_stage(ingestion, local, string_table.MSG_LOADED_DOCUMENTS.format(count=len(docs)))

    console.print_stage(ingestion, local, string_table.MSG_SPLITTING_DOCUMENTS)
    # Chunk size/overlap come from DEFAULT_CHUNK_SIZE/DEFAULT_CHUNK_OVERLAP
    # in settings.py, overridable per-machine via .env - see split_documents().
    chunks = split_documents(docs)
    console.print_stage(ingestion, local, string_table.MSG_SPLIT_DOCUMENTS.format(count=len(chunks)))

    console.print_stage(embedding, local, string_table.MSG_LOADING_EMBEDDING_MODEL)
    embeddings = build_embeddings()

    console.print_stage(embedding, local, string_table.MSG_BUILDING_VECTOR_STORE)
    vector_store = build_vectors(chunks, embeddings)
    console.print_stage(embedding, local, string_table.MSG_VECTOR_STORE_READY.format(count=len(chunks)))

    return RagAssistant(
        vector_store=vector_store,
        model=build_chat_model(),
        retrieval_k=retrieval_k,
        system_prompt_path=system_prompt_path,
    )


# -- main ---
def main() -> None:
    """
    Run a grounded Q&A request from the cli.
    """

    args = parse_args()

    # Load .env before anything reads an env var. build_chat_model() calls this
    # again later (harmless, it's idempotent), but that's too late for the
    # settings read below - without this, CHATBOT_MODEL_PROVIDER and the
    # CHATBOT_* chunk settings would only ever be seen if they were exported
    # into the real environment, never when they live in .env alone.
    load_dotenv()

    execute_flag = (
        args.exe or os.getenv(string_table.ENV_EXECUTE_COMMANDS, "").lower() == "true"
    )

    source_path = args.doc or args.documents or settings.DEFAULT_DOCS_PATH

    # What provider is being used, Azure or local? Resolved once: the tag below
    # labels every later model-call line, and asking twice was how the
    # connecting message came to be printed twice.
    provider = get_model_provider()
    cloud_tag = string_table.TAG_CLOUD if provider is ModelProvider.AZURE else string_table.TAG_LOCAL
    model_call = string_table.TAG_MODEL_CALL

    console.print_stage(model_call, cloud_tag, string_table.MSG_CONNECTING.format(provider=provider.value))

    assistant = build_assistant(source_path, args.k, args.system_prompt)

    console.print_stage(model_call, cloud_tag, string_table.MSG_THINKING)

    # answer() already returns a parsed ModelResponse (schema validated, or
    # text-parsed as a fallback) - there is no separate parse step to call here.
    model_response = assistant.answer(args.question)

    # The one and only normalization point - see execution.py.
    if model_response.command and os.name == "nt":
        model_response.command = normalize_command_for_shell(model_response.command)

    print()
    console.print_model_response(model_response)

    if execute_flag:
        apply_exe_request(model_response, yolo=args.yolo)

# -~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~
if __name__ == "__main__":
    main()
# -~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~
