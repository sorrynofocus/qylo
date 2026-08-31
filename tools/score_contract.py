#!/usr/bin/env python3
# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.08
# Diagnostic harness: measures how reliably the agent terminates and how often it
# classifies a request correctly, through the real RagAssistant.answer() path.
#
# Purpose:
# This backend is stochastic and cannot be pinned - gpt-5-nano rejects an explicit
# temperature - so a single run proves nothing. Reasoning about a prompt change and
# measuring one are different activities; several changes that were argued convincingly
# turned out to be regressions when run more than once. Run this before and after any
# change to system_prompt.txt, assistant.py's agent construction, or retrieval settings.
#
# NOT a test suite. It calls a real model provider and costs real tokens.
#
# Usage examples (see tools/README.md for granular details):
#
# Default 5 rounds per case against whatever CHATBOT_MODEL_PROVIDER says:
# uv run python tools/score_contract.py
#
# More rounds for a tighter estimate (each round is a full agent run):
# uv run python tools/score_contract.py 10
#
# Score the local backend instead (edit .env, or export the variable first):
# CHATBOT_MODEL_PROVIDER=local uv run python tools/score_contract.py

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from qylo.assistant import RagAssistant
from qylo.documents import load_documents, scan_document_paths, split_documents
from qylo.model_provider import build_chat_model
from qylo.retrieval import build_embeddings, build_vectors

# One case per response-contract branch. `expected` holds ResponseKind names, and a
# command request accepts either COMMAND or UNSAFE - the deterministic Safety override
# in answer() may legitimately promote one to the other.
CASES = [
    ("grounded", "What is flogger and what logging features does it support?", {"ANSWER"}),
    ("ungrounded", "Who wrote the novel Moby Dick?", {"GENERAL"}),
    ("command", "How do I shut down Windows in 30 minutes?", {"COMMAND", "UNSAFE"}),
    ("conversational", "Thanks, that was helpful!", {"GENERAL"}),
]

# answer() returns this text once every retry attempt has been exhausted.
EXHAUSTED_MARKER = "didn't converge"


def main() -> None:
    """
    Score each contract branch over N rounds and print a per-case summary.
    """

    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 5

    paths = scan_document_paths(Path("data") / "documents")
    chunks = split_documents(load_documents(paths))
    store = build_vectors(chunks, build_embeddings())
    assistant = RagAssistant(vector_store=store, model=build_chat_model())

    print(f"{len(chunks)} chunk(s); {rounds} round(s) per case\n", flush=True)
    print(f"{'case':16} {'answered':>9} {'correct':>8}  detail", flush=True)

    answered_total = correct_total = attempted_total = 0

    for name, question, expected in CASES:
        answered = correct = 0
        detail: list[str] = []

        for _ in range(rounds):
            attempted_total += 1
            response = assistant.answer(question)

            if EXHAUSTED_MARKER in (response.content or ""):
                detail.append("EXHAUSTED")
                continue

            answered += 1
            is_correct = response.kind.name in expected
            correct += is_correct
            detail.append(f"{response.kind.name}{'' if is_correct else '<<WRONG'}")

        answered_total += answered
        correct_total += correct
        print(
            f"{name:16} {answered}/{rounds:<7} {correct}/{rounds:<6}  {' '.join(detail)}",
            flush=True,
        )

    print(
        f"\nTOTAL answered {answered_total}/{attempted_total}"
        f"   correct {correct_total}/{attempted_total}",
        flush=True,
    )


if __name__ == "__main__":
    main()
