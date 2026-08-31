# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.31
# The agent loop: retrieve -> decide -> answer.
#
# Stage 5 of the request flow. Called by cli.py; uses retrieval.py's tool,
# model_provider.py's chat model, and response_contract.py to parse the reply.
#
# Purpose:
# This is agentic RAG, not the naive retrieve-then-read kind. The model is NOT
# handed pre-fetched context. It gets a retrieve_document_context tool and
# decides for itself whether to search at all, and how many times, before
# answering. That freedom is why max_agent_steps exists - see
# settings.DEFAULT_MAX_AGENT_STEPS.
#
# A source document can declare "Safety: unsafe" (documents.py::extract_safety_tag),
# which the retrieval tool surfaces in its returned text. answer() uses that to
# deterministically upgrade CMD -> UNSAFE. The upgrade is one-directional on
# purpose: a doc can make a command more restricted, never less.
#
# Usage examples (see README for granular details):
#
# Answer one question against an already-built vector store:
# answer = RagAssistant(store, model).answer("What is flogger?")
#
# Override retrieval depth and the system prompt for one run:
# assistant = RagAssistant(store, model, retrieval_k=8, system_prompt_path=Path("prompt.txt"))
#

from __future__ import annotations

from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.middleware import InputAgentState
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.vectorstores import InMemoryVectorStore
from langgraph.errors import GraphRecursionError

from qylo import string_table
from qylo.response_contract import (
    ContractResponse,
    ModelResponse,
    ResponseKind,
    contract_response_to_model_response,
    parse_model_response,
)
from qylo.retrieval import build_retrieval_tool
from qylo.settings import (
    DEFAULT_MAX_AGENT_ATTEMPTS,
    DEFAULT_MAX_AGENT_STEPS,
    DEFAULT_RETRIEVAL_K,
)

# Package-relative so the bundled prompt is found from an installed wheel and
# from inside the Docker image, not only from a source checkout.
DEFAULT_SYSTEM_PROMPT_PATH = Path(__file__).parent / "system_prompt.txt"


def system_prompt(path: Path | None = None) -> str:
    """
    Load the instruction prompt that drives tool-calling retrieval and the answer contract.

    Parameters:
        path: Custom prompt file to load instead of the bundled default at
            DEFAULT_SYSTEM_PROMPT_PATH.
    """
    prompt_path = path or DEFAULT_SYSTEM_PROMPT_PATH

    return prompt_path.read_text(encoding="utf-8").rstrip("\n")


class RagAssistant:
    """
    Coordinates tool-calling retrieval and answering after documents have been indexed.

    Parameters:
        vector_store: In-memory index containing embedded document chunks.
        model: Chat model used to decide when to retrieve and to write the final answer.
        retrieval_k: Number of matching chunks the retrieval tool returns per call.
        system_prompt_path: Custom system prompt file to use instead of the
            bundled default at DEFAULT_SYSTEM_PROMPT_PATH.
        max_agent_steps: Hard ceiling on LangGraph steps (one model call or
            one tool call each) for a single answer() call, passed as
            recursion_limit. See settings.DEFAULT_MAX_AGENT_STEPS for why this
            exists. create_agent's graph does not use a safe default on its
            own.

    Unlike naive RAG, the chat model is not handed pre-fetched context. It is
    given a retrieve_document_context tool and decides for itself, via
    langchain.agents.create_agent's tool-calling loop, whether and how many
    times to search the knowledge base before producing a final answer.
    """

    def __init__(
        self,
        vector_store: InMemoryVectorStore,
        model: BaseChatModel,
        retrieval_k: int = DEFAULT_RETRIEVAL_K,
        system_prompt_path: Path | None = None,
        max_agent_steps: int = DEFAULT_MAX_AGENT_STEPS,
        max_agent_attempts: int = DEFAULT_MAX_AGENT_ATTEMPTS,
    ) -> None:
        self.vector_store = vector_store
        self.model = model
        self.retrieval_k = retrieval_k
        self.max_agent_steps = max_agent_steps
        self.max_agent_attempts = max_agent_attempts
        self._retrieval_tool = build_retrieval_tool(vector_store, retrieval_k)

        self._agent = create_agent(
            model,
            [self._retrieval_tool],
            system_prompt=system_prompt(system_prompt_path),
            # Forces the agent's final answer through the ContractResponse
            # schema instead of relying on the model writing a free-text
            # ANS:/GENERAL:/CMD:/UNSAFE: label correctly on its own.
            response_format=ToolStrategy(schema=ContractResponse),
        )

    def answer(self, question: str) -> ModelResponse:
        """
        Run the tool-calling agent end-to-end and return a parsed ModelResponse.

        The agent may call retrieve_document_context zero or more times before
        producing its final answer. The final answer is normally a schema-
        validated ContractResponse (create_agent's response_format), which is
        the reliable path. Some backends (local llama.cpp, depending on the
        GGUF chat template) aren't confirmed to support a forced structured
        response — if none was produced, fall back to parsing the raw message
        text against the original ANS:/GENERAL:/CMD:/UNSAFE: text contract.

        If the model doesn't converge within max_agent_steps LangGraph steps
        (see settings.DEFAULT_MAX_AGENT_STEPS), the run is aborted with a
        GENERAL response explaining why, instead of running away indefinitely —
        see TROUBLESHOOT.MD for the measured incident this guards against.
        """

        # Per-call settings for this one .invoke(). RunnableConfig is the TypedDict
        # langchain_core declares for that second argument, and annotating the
        # literal is the entire point of naming it: at runtime this is a plain dict
        # with zero overhead and nothing validates it, so a typo such as
        # "recursion_limits" would be accepted, silently ignored, and leave the run
        # uncapped. The annotation is what gets the key names checked against the
        # real schema instead of inferring an opaque dict[str, int].
        #
        # RunnableConfig has eight optional keys - tags, metadata, callbacks,
        # run_name, max_concurrency, recursion_limit, configurable, run_id - and
        # every Runnable in LangChain accepts them. It also propagates downward: a
        # parent's config is merged into child runnables through a ContextVar, so
        # callbacks and tags set once apply to nested calls without being threaded
        # through by hand. Qylo needs exactly one of the eight.
        #
        # recursion_limit has to be passed explicitly, because the two libraries in
        # play disagree about what happens when you don't:
        #   - langchain_core documents a default of 25.
        #   - LangGraph does NOT inherit that. langgraph/_internal/_config.py sets
        #     its own DEFAULT_RECURSION_LIMIT of 10007 (itself overridable via the
        #     LANGGRAPH_DEFAULT_RECURSION_LIMIT environment variable), which for a
        #     chat agent is no cap at all.
        # One "step" is one node execution - one model call OR one tool call - so a
        # model that never converges could reach ~5,000 real model calls before
        # LangGraph itself would ever intervene. That is measured history rather
        # than a hypothetical: see settings.DEFAULT_MAX_AGENT_STEPS for the numbers
        # and TROUBLESHOOT.MD for the run that provoked this line existing.
        #
        # Exceeding the limit raises GraphRecursionError, which the retry loop below
        # catches. Together they are what turns a runaway loop into a bounded, cheap
        # failure that degrades to a GENERAL answer instead of billing for hours.
        invoke_config: RunnableConfig = {"recursion_limit": self.max_agent_steps}

        # InputAgentState for the same reason invoke_config is a RunnableConfig:
        # it's the TypedDict create_agent's graph declares as its input schema.
        # HumanMessage rather than a raw {"role": ..., "content": ...} dict -
        # add_messages accepts either and coerces the dict to exactly this, but
        # the typed object is what the schema is written around.
        # The annotation is load-bearing, not decoration: the declared field is
        # list[AnyMessage | dict[str, Any]], and an un-annotated literal infers
        # as list[HumanMessage], which isn't assignable to it because list is
        # invariant. Naming the target type resolves that. Runtime is unchanged.
        agent_input: InputAgentState = {"messages": [HumanMessage(content=question)]}

        # Retry the whole run on non-convergence. See DEFAULT_MAX_AGENT_ATTEMPTS
        # for the measurements behind this: looping is a sampling outcome rather
        # than a property of the question, so a fresh attempt usually lands.
        # Only GraphRecursionError is retried - a real error (auth, network,
        # schema validation) still propagates on the first occurrence.
        result = None

        for attempt in range(1, self.max_agent_attempts + 1):
            try:
                result = self._agent.invoke(agent_input, config=invoke_config)
                break
            except GraphRecursionError:
                if attempt >= self.max_agent_attempts:
                    return ModelResponse(
                        kind=ResponseKind.GENERAL,
                        content=string_table.MSG_AGENT_STEP_LIMIT_EXCEEDED.format(
                            limit=self.max_agent_steps
                        ),
                        command=None,
                        raw_text="",
                    )

        if result is None:  # unreachable: the loop either breaks or returns
            return ModelResponse(
                kind=ResponseKind.GENERAL,
                content=string_table.MSG_AGENT_STEP_LIMIT_EXCEEDED.format(limit=self.max_agent_steps),
                command=None,
                raw_text="",
            )

        structured = result.get("structured_response")

        if structured is not None:
            model_response = contract_response_to_model_response(structured)
        else:
            model_response = parse_model_response(str(result["messages"][-1].content))

        if model_response.kind is ResponseKind.COMMAND:
            # A source doc can declare itself Safety: unsafe (extract_safety_tag),
            # which retrieve_document_context surfaces as "(Safety: unsafe)" in
            # its returned text. Measured ~77% correct (10/13) even with that tag
            # present in context, so a CMD verdict isn't trustworthy enough on its
            # own here... if a retrieved source said unsafe, override deterministically
            # rather than trusting the model's classification.
            for message in result["messages"]:
                content = getattr(message, "content", "")
                if isinstance(content, str) and "(Safety: unsafe)" in content:
                    model_response.kind = ResponseKind.UNSAFE
                    break

        return model_response
