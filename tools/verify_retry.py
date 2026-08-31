#!/usr/bin/env python3
# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.08
# Diagnostic harness: proves the bounded retry in RagAssistant.answer() actually runs,
# deterministically, without waiting for a real non-convergence to occur.
#
# Purpose:
# answer() retries on GraphRecursionError because looping is a sampling outcome rather
# than a property of the question (see DEFAULT_MAX_AGENT_ATTEMPTS in settings.py). Confirming
# that from live traffic is unreliable - a healthy run converges on the first attempt and
# exercises none of the retry path, so "it worked" proves nothing about the retry.
#
# Setting max_agent_steps=1 guarantees GraphRecursionError on every attempt, which turns
# the question into a simple count: how many times was the agent invoked?
#
# NOT a test suite, though it is the closest thing here to one. It calls a real model
# provider and costs real tokens - each forced failure is still a live model call.
#
# Usage examples (see tools/README.md for granular details):
#
# uv run python tools/verify_retry.py

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from qylo import settings
from qylo.assistant import RagAssistant
from qylo.documents import load_documents, scan_document_paths, split_documents
from qylo.model_provider import build_chat_model
from qylo.response_contract import ResponseKind
from qylo.retrieval import build_embeddings, build_vectors


def main() -> None:
    """
    Force non-convergence and assert the agent is invoked exactly max_agent_attempts times.
    """

    source = Path("data") / "documents" / "Flogger-README.md"
    store = build_vectors(
        split_documents(load_documents(scan_document_paths(source))),
        build_embeddings(),
    )

    print(f"DEFAULT_MAX_AGENT_ATTEMPTS = {settings.DEFAULT_MAX_AGENT_ATTEMPTS}")

    for attempts in (1, settings.DEFAULT_MAX_AGENT_ATTEMPTS):
        assistant = RagAssistant(
            vector_store=store,
            model=build_chat_model(),
            # 1 step cannot fit a tool call plus an answer, so every attempt raises.
            max_agent_steps=1,
            max_agent_attempts=attempts,
        )

        calls = {"count": 0}
        real_invoke = assistant._agent.invoke

        def counting_invoke(*args, **kwargs):
            calls["count"] += 1
            return real_invoke(*args, **kwargs)

        assistant._agent.invoke = counting_invoke  # type: ignore[method-assign]

        response = assistant.answer("What is flogger?")

        print(f"max_agent_attempts={attempts}: agent invoked {calls['count']} time(s); "
              f"kind={response.kind.name}")

        assert calls["count"] == attempts, (
            f"expected {attempts} invocation(s), got {calls['count']}"
        )
        # Exhausting every attempt must degrade to the GENERAL step-limit response,
        # never raise into the caller.
        assert response.kind is ResponseKind.GENERAL

    print("\nOK - retry invokes exactly max_agent_attempts times and degrades to GENERAL")


if __name__ == "__main__":
    main()
