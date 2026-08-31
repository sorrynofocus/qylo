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
import re
import subprocess
from pathlib import Path

from dotenv import load_dotenv

from qylo import string_table
from qylo.response_contract import ModelResponse, ResponseKind
from qylo.model_provider import ModelProvider, build_chat_model, get_model_provider


DEFAULT_DOCS_PATH = Path("data") / "documents"

# Matches a POSIX-style 'single-quoted' segment with no embedded double quote.
SINGLE_QUOTED_SEGMENT = re.compile(r"'([^'\"]*)'")


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
        help=string_table.HELP_DOCUMENTS.format(default_path=DEFAULT_DOCS_PATH),
    )
    source_group.add_argument(
        "--doc",
        type=Path,
        help=string_table.HELP_DOC,
    )

    parser.add_argument(
        "-k",
        type=int,
        default=4,
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


def stage_prefix(stage_tag: str, locality_tag: str) -> str:
    """
    Build a "[stage] [local] " prefix for a progress message.
    """
    return f"{stage_tag} {locality_tag} "


def run_command(command: str) -> None:
    """
    Execute one command string through the system shell.

    Parameters:
        command: Command text produced by a CMD response, or by an UNSAFE
            response when the user also passed --yolo.

    This is intentionally small and visible for learning. Future governance can
    add allowlists, deny patterns, confirmation prompts, and audit logging here.
    """

    print()
    print(string_table.MSG_EXECUTING_COMMAND.format(command=command), flush=True)

    result = subprocess.run(command, shell=True, check=False)

    print(string_table.MSG_COMMAND_EXIT_CODE.format(code=result.returncode))


def print_model_response(response: ModelResponse) -> None:
    """
    Print the parsed response without exposing contract labels as noise.

    Parameters:
        response: Parsed ANS/CMD/UNSAFE response from the model.
    """

    if response.kind is ResponseKind.ANSWER:
        print(response.content)
        return

    if response.kind is ResponseKind.GENERAL:
        print(string_table.MSG_NOT_GROUNDED)
        print(response.content)
        return

    if response.kind is ResponseKind.COMMAND:
        print(string_table.LABEL_COMMAND)
        print(response.command or response.content)
        return

    print(string_table.LABEL_UNSAFE_REQUEST)
    print(response.content or string_table.MSG_UNSAFE_DEFAULT_REASON)

    if response.command:
        print()
        print(string_table.LABEL_PROPOSED_COMMAND)
        print(response.command)


def apply_exe_request(response: ModelResponse, *, yolo: bool) -> None:
    """
    Apply execution rules after the model response has been printed.

    Parameters:
        response: Parsed model response.
        yolo: Whether the user explicitly allowed UNSAFE command execution.

    Rules:
        ANS: never execute.
        GENERAL: never execute (same guarantee as ANS, regardless of --exe/--yolo).
        CMD: execute when --exe was provided.
        UNSAFE: show reason and command, execute only with --exe --yolo.
    """

    match response.kind:
        case ResponseKind.ANSWER:
            print()
            print(string_table.MSG_NO_COMMAND_PROVIDED)
            return

        case ResponseKind.GENERAL:
            print()
            print(string_table.MSG_GENERAL_NOT_RUN)
            return

        case ResponseKind.COMMAND:
            if not response.command:
                print()
                print(string_table.MSG_CMD_NO_TEXT)
                return
            run_command(response.command)
            return

        case ResponseKind.UNSAFE:
            if not response.command:
                print()
                print(string_table.MSG_UNSAFE_NO_COMMAND)
                return
            if not yolo:
                print()
                print(string_table.MSG_UNSAFE_BLOCKED)
                return
            run_command(response.command)



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

    source_path = args.doc or args.documents or DEFAULT_DOCS_PATH

    #What provider being used? Azure or local? Azure local only supported for now.
    provider = get_model_provider()

    # cloud tag is just tagging if we're using azure or local
    cloud_tag = string_table.TAG_CLOUD if provider is ModelProvider.AZURE else string_table.TAG_LOCAL

    print(stage_prefix(string_table.TAG_MODEL_CALL, cloud_tag) + string_table.MSG_CONNECTING.format(provider=provider.value))

    # Import the heavier RAG dependencies after argument parsing so --help
    # stays fast and easy to understand. It gets SLLLOWW!
    # Leave this here, lot's math -heh
    from qylo.rag import (
                                RagAssistant,
                                build_embeddings,
                                build_vectors,
                                load_documents,
                                scan_document_paths,
                                split_documents,
                            )

    print(stage_prefix(string_table.TAG_INGESTION, string_table.TAG_LOCAL) + string_table.MSG_SCANNING.format(path=source_path))
    document_paths = scan_document_paths(source_path)
    print(stage_prefix(string_table.TAG_INGESTION, string_table.TAG_LOCAL) + string_table.MSG_FOUND_DOCUMENTS.format(count=len(document_paths)))

    print(stage_prefix(string_table.TAG_INGESTION, string_table.TAG_LOCAL) + string_table.MSG_LOADING_DOCUMENTS)
    docs = load_documents(document_paths)
    print(stage_prefix(string_table.TAG_INGESTION, string_table.TAG_LOCAL) + string_table.MSG_LOADED_DOCUMENTS.format(count=len(docs)))

    print(stage_prefix(string_table.TAG_INGESTION, string_table.TAG_LOCAL) + string_table.MSG_SPLITTING_DOCUMENTS)
    # Chunk size/overlap come from DEFAULT_CHUNK_SIZE/DEFAULT_CHUNK_OVERLAP
    # in rag.py, overridable per-machine via .env - see split_documents().
    chunks = split_documents(docs)
    print(stage_prefix(string_table.TAG_INGESTION, string_table.TAG_LOCAL) + string_table.MSG_SPLIT_DOCUMENTS.format(count=len(chunks)))

    print(stage_prefix(string_table.TAG_EMBEDDING, string_table.TAG_LOCAL) + string_table.MSG_LOADING_EMBEDDING_MODEL)
    embeddings = build_embeddings()

    print(stage_prefix(string_table.TAG_EMBEDDING, string_table.TAG_LOCAL) + string_table.MSG_BUILDING_VECTOR_STORE)
    vector_store = build_vectors(chunks, embeddings)
    print(stage_prefix(string_table.TAG_EMBEDDING, string_table.TAG_LOCAL) + string_table.MSG_VECTOR_STORE_READY.format(count=len(chunks)))

    provider = get_model_provider()
    
    print(stage_prefix(string_table.TAG_MODEL_CALL, cloud_tag) + string_table.MSG_CONNECTING.format(provider=provider.value))
    
    model = build_chat_model()
    
    assistant = RagAssistant(
                            vector_store=vector_store,
                            model=model,
                            retrieval_k=args.k,
                            system_prompt_path=args.system_prompt,
                        )

    print(stage_prefix(string_table.TAG_MODEL_CALL, cloud_tag) + string_table.MSG_THINKING)

    # answer() already returns a parsed ModelResponse (schema validated, or
    # text-parsed as a fallback) - there is no separate parse step to call here.
    model_response = assistant.answer(args.question)
    
    if model_response.command and os.name == "nt":
        # Models often compose commands with POSIX-style single quotes (rg -w
        # 'flogger' data/). subprocess.run(shell=True) below runs through
        # cmd.exe, which doesn't treat single quotes as argument delimiters —
        # they'd pass through as literal characters, so the command would
        # silently search for 'flogger' quotes and all. Rewrite to double
        # quotes, which cmd.exe and most Windows console apps do understand.
        model_response.command = SINGLE_QUOTED_SEGMENT.sub(r'"\1"', model_response.command)

    print()
    print_model_response(model_response)

    if execute_flag:
        apply_exe_request(model_response, yolo=args.yolo)

# -~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~
if __name__ == "__main__":
    main()
# -~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~