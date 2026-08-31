#!/usr/bin/env python3
# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.08
# Diagnostic harness: streams the agent's message sequence so a non-converging run can
# actually be read, instead of vanishing inside a GraphRecursionError.
#
# Purpose:
# RagAssistant.answer() invokes the agent, and .invoke() discards every intermediate
# message when it raises on the step limit - you learn only that ten steps elapsed. This
# reruns the same agent with stream_mode="values" and prints each message as it is
# produced: type, finish_reason, tool calls with their arguments, and content length.
#
# That distinction is the whole diagnosis. Repeated tool calls with DIFFERENT arguments
# mean the model is exploring and may need better context or a larger step budget.
# Repeated tool calls with the SAME argument mean it has no reachable terminal state -
# a control-flow problem, not a model-quality one. Only the transcript tells them apart.
#
# NOT a test suite. It calls a real model provider and costs real tokens.
#
# Usage examples (see tools/README.md for granular details):
#
# Stream the default question against the whole knowledge base:
# uv run python tools/stream_agent.py
#
# Stream a specific question:
# uv run python tools/stream_agent.py "How do I shut down Windows in 30 minutes?"
#
# Narrow to one document to rule out corpus size as a factor:
# uv run python tools/stream_agent.py "What is flogger?" data/documents/Flogger-README.md

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage

load_dotenv()

from qylo.assistant import system_prompt
from qylo.documents import load_documents, scan_document_paths, split_documents
from qylo.model_provider import build_chat_model
from qylo.response_contract import ContractResponse
from qylo.retrieval import build_embeddings, build_retrieval_tool, build_vectors
from qylo.settings import DEFAULT_MAX_AGENT_STEPS, DEFAULT_RETRIEVAL_K


def main() -> None:
    """
    Rebuild the agent exactly as RagAssistant does, then stream one question through it.
    """

    question = sys.argv[1] if len(sys.argv) > 1 else "What is flogger?"
    source = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data") / "documents"

    chunks = split_documents(load_documents(scan_document_paths(source)))
    store = build_vectors(chunks, build_embeddings())
    tool = build_retrieval_tool(store, DEFAULT_RETRIEVAL_K)

    agent = create_agent(
        build_chat_model(),
        [tool],
        system_prompt=system_prompt(None),
        response_format=ToolStrategy(schema=ContractResponse),
    )

    print(f"{len(chunks)} chunk(s) from {source}")
    print(f"question: {question}\n", flush=True)

    seen = 0
    try:
        for state in agent.stream(
            {"messages": [HumanMessage(content=question)]},
            {"recursion_limit": DEFAULT_MAX_AGENT_STEPS},
            stream_mode="values",
        ):
            messages = state.get("messages", [])

            while seen < len(messages):
                message = messages[seen]
                seen += 1

                calls = getattr(message, "tool_calls", None) or []
                finish = getattr(message, "response_metadata", {}).get("finish_reason")
                content = message.content
                text = (content if isinstance(content, str) else str(content)).strip()

                print(f"[{seen - 1}] {type(message).__name__} "
                      f"finish={finish} tool_calls={len(calls)}")

                for call in calls:
                    # Identical args across turns is the signature of a stuck model.
                    print(f"     CALL {call.get('name')}  args={call.get('args')}")

                if text:
                    print(f"     text[{len(text)}]: {text[:250]}")

                if not text and not calls:
                    print("     <<< EMPTY: no content and no tool calls >>>")

    except Exception as exc:  # noqa: BLE001 - diagnostic script, report anything
        print(f"\nSTOPPED: {type(exc).__name__}: {str(exc)[:200]}")


if __name__ == "__main__":
    main()
