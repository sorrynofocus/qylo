# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.30
#
# Purpose:
# Pins RagAssistant.answer() - the branch that picks the schema-enforced structured
# response over the text-parsing fallback, the deterministic CMD -> UNSAFE promotion,
# and the bounded GraphRecursionError retry. Model-free: the agent is a stand-in, so
# no provider, no network, no cost.
#
# Run:
# uv run pytest tests/test_assistant_answer.py

from __future__ import annotations

import pytest
from langgraph.errors import GraphRecursionError

from qylo import string_table
from qylo.rag import RagAssistant
from qylo.response_contract import ContractResponse, ResponseKind


class FakeMessage:
    """Stands in for a LangChain message: answer() only ever reads .content."""

    def __init__(self, content: str) -> None:
        self.content = content


class FakeAgent:
    """
    Stands in for the compiled LangGraph agent. answer() only ever calls .invoke().

    Parameters:
        outcomes: One entry per expected invocation, in order. An Exception
            instance is raised; anything else is returned as the agent result.

    Counts its own calls, so a test can assert the retry loop ran exactly as
    many times as intended - an extra attempt is a real regression and must not
    pass silently.
    """

    def __init__(self, outcomes: list) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def invoke(self, agent_input, config=None):
        self.calls += 1
        assert self.outcomes, "agent.invoke() was called more times than the test expected"
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_assistant(agent: FakeAgent, max_attempts: int = 3, max_steps: int = 10) -> RagAssistant:
    """
    Build a RagAssistant around a stand-in agent, skipping __init__.

    __init__ would construct a real chat model and compile a real graph. answer()
    only touches the four attributes set here, so __new__ plus these assignments
    gives a real RagAssistant running real answer() code.
    """

    assistant = RagAssistant.__new__(RagAssistant)
    assistant._agent = agent
    assistant.max_agent_steps = max_steps
    assistant.max_agent_attempts = max_attempts
    assistant._telemetry_handler = None
    return assistant


# --- which path produced the answer ------------------------------------------
# The structured result and the message text deliberately disagree in these two
# tests. If they agreed, the assertion could not tell which path actually won.


def test_structured_response_wins_over_the_message_text():
    agent = FakeAgent(
        [
            {
                "structured_response": ContractResponse(kind="ANS", content="from the schema"),
                "messages": [FakeMessage("CMD: rm -rf /")],
            }
        ]
    )

    response = make_assistant(agent).answer("what is flogger?")

    assert response.kind is ResponseKind.ANSWER
    assert response.content == "from the schema"
    assert response.command is None
    assert agent.calls == 1


def test_missing_structured_response_falls_back_to_text_parsing():
    # No "structured_response" key at all - the backend did not produce one.
    agent = FakeAgent([{"messages": [FakeMessage("CMD: rg -w flogger data/")]}])

    response = make_assistant(agent).answer("search for flogger")

    assert response.kind is ResponseKind.COMMAND
    assert response.command == "rg -w flogger data/"
    assert agent.calls == 1


# --- the deterministic Safety: unsafe override -------------------------------


def test_cmd_is_promoted_to_unsafe_when_a_retrieved_doc_declared_unsafe():
    agent = FakeAgent(
        [
            {
                "structured_response": ContractResponse(
                    kind="CMD", content="shuts the machine down", command="shutdown /s /t 0"
                ),
                "messages": [
                    FakeMessage("[1] Source: shutdown.md (Safety: unsafe)\nHow to shut down."),
                    FakeMessage("CMD: shutdown /s /t 0"),
                ],
            }
        ]
    )

    response = make_assistant(agent).answer("shut down this computer")

    assert response.kind is ResponseKind.UNSAFE
    assert response.command == "shutdown /s /t 0"


def test_cmd_stays_cmd_without_an_unsafe_marker():
    agent = FakeAgent(
        [
            {
                "structured_response": ContractResponse(
                    kind="CMD", content="searches the docs", command="rg -w flogger data/"
                ),
                "messages": [
                    FakeMessage("[1] Source: flogger.md\nflogger writes structured logs."),
                ],
            }
        ]
    )

    response = make_assistant(agent).answer("search for flogger")

    assert response.kind is ResponseKind.COMMAND


# --- the bounded retry: all four outcomes must be distinguishable ------------


def test_retry_recovers_after_one_non_convergence():
    agent = FakeAgent(
        [
            GraphRecursionError("did not converge"),
            {"structured_response": ContractResponse(kind="ANS", content="second attempt")},
        ]
    )

    response = make_assistant(agent).answer("what is flogger?")

    assert response.kind is ResponseKind.ANSWER
    assert response.content == "second attempt"
    assert agent.calls == 2


def test_exhausting_every_attempt_returns_general_not_an_exception():
    agent = FakeAgent([GraphRecursionError("loop") for _ in range(3)])

    response = make_assistant(agent, max_attempts=3, max_steps=10).answer("what is flogger?")

    assert response.kind is ResponseKind.GENERAL
    assert response.content == string_table.MSG_AGENT_STEP_LIMIT_EXCEEDED.format(limit=10)
    assert response.command is None
    assert agent.calls == 3


def test_an_unrelated_error_propagates_and_is_not_retried():
    # Auth, network and schema failures must surface on the first occurrence
    # rather than being retried or swallowed into a GENERAL answer.
    agent = FakeAgent([RuntimeError("azure auth failed")])

    with pytest.raises(RuntimeError):
        make_assistant(agent).answer("what is flogger?")

    assert agent.calls == 1
