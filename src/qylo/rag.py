# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.07.30
# Document ingestion and the agentic retrieval loop that answers a question.
#
# Purpose:
# Everything between "a folder of files" and "a parsed ModelResponse". Two
# halves that run in that order:
#
#   1. Ingestion (module-level functions, driven by cli.py):
#      scan_document_paths -> load_documents -> split_documents ->
#      build_embeddings -> build_vectors. Files become chunks, chunks become
#      vectors in an in-memory store that lives for exactly one process.
#      Nothing is cached to disk, so every run re-indexes from scratch.
#
#   2. Answering (RagAssistant): this is agentic RAG, not the naive
#      retrieve-then-read kind. The model is NOT handed pre-fetched context.
#      It gets a retrieve_document_context tool and decides for itself whether
#      to search at all, and how many times, before answering. That freedom is
#      why max_agent_steps exists - see DEFAULT_MAX_AGENT_STEPS below.
#
# Docs can declare "Safety: safe|unsafe" near the top. extract_safety_tag
# lifts that out of the indexed text and into metadata, the retrieval tool
# surfaces it back to the model, and answer() uses it to deterministically
# upgrade CMD -> UNSAFE. That upgrade is one-directional on purpose: a doc can
# make a command more restricted, never less.
#
# Usage examples (see README for granular details):
#
# Ingest a folder, then ask one question:
# paths = scan_document_paths(Path("data/documents"))
# chunks = split_documents(load_documents(paths))
# store = build_vectors(chunks, build_embeddings())
# answer = RagAssistant(store, model).answer("What is flogger?")
#
# Chunking honors CHATBOT_CHUNK_SIZE / CHATBOT_CHUNK_OVERLAP from .env;
# explicit arguments still win over both:
# chunks = split_documents(docs, chunk_size=1500, chunk_overlap=300)
#


from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.middleware import InputAgentState
from langchain.agents.structured_output import ToolStrategy
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.errors import GraphRecursionError

from qylo import string_table
from qylo.response_contract import (
    ContractResponse,
    ModelResponse,
    ResponseKind,
    contract_response_to_model_response,
    parse_model_response,
)

# Default local embedding model. It maps text into a 384-dimensional vector
# space so semantically similar chunks can be found with similarity search.
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Chunking defaults. Both are overridable from .env (CHATBOT_CHUNK_SIZE /
# CHATBOT_CHUNK_OVERLAP) - see split_documents() below. Sizes are in
# characters, not tokens: overlap is how much text adjacent chunks share so a
# sentence split across a boundary still appears whole in at least one chunk.
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200
DEFAULT_RETRIEVAL_K = 4
SUPPORTED_DOCUMENT_EXTENSIONS = {".pdf", ".md", ".txt"}
DEFAULT_SYSTEM_PROMPT_PATH = Path(__file__).parent / "system_prompt.txt"

# create_agent's compiled LangGraph graph does NOT inherit langchain_core's
# well-known RunnableConfig default of 25 - langgraph 1.x sets its own
# internal default (DEFAULT_RECURSION_LIMIT, langgraph/_internal/_config.py)
# of 10,007 graph steps, which is effectively no cap at all for a chat agent.
# One "step" is one node execution (one model call OR one tool call), so a
# model that never converges to a final answer can run to ~5,000 real model
# calls before LangGraph itself would ever intervene - see TROUBLESHOOT.MD
# for a measured real-world case that hit 118 model calls / 114 retrievals
# for a single question before it happened to converge on its own. 10 steps
# is enough headroom for the system prompt's own stated behavior ("call it
# again with a refined query if the first results seem incomplete" - up to
# ~4 retrieval round trips) plus the final answer, while still failing fast
# and cheaply instead of silently running away.
DEFAULT_MAX_AGENT_STEPS = 10

# How many times to run the whole agent for one question before giving up.
#
# Non-convergence on this stack is stochastic, not deterministic: the same
# question, prompt and model either terminates or loops depending only on
# sampling. gpt-5-nano rejects an explicit temperature, so that randomness
# cannot be turned off from here.
#
# Measured on Azure (2026-08-08, 5 rounds x 4 cases, TROUBLESHOOT.MD): a single
# attempt converged 13/20, while allowing up to 3 attempts converged 18/20 -
# and for the three real query shapes (grounded / ungrounded / command) retrying
# took 12/15 to 15/15. Failures behave as independent draws, so a bounded retry
# is worth far more here than any further prompt wording.
#
# The cost is real and bounded: a retry re-runs the model calls (not ingestion
# or embedding, which happen once per process), so a worst case is 3x the model
# spend on a question that was going to fail anyway. Retrying only ever happens
# after a GraphRecursionError, never on a successful answer.
DEFAULT_MAX_AGENT_ATTEMPTS = 3

# Source docs may declare a tool's safety with a leading "Safety: safe" or
# "Safety: unsafe" line. This is stripped from the indexed content and
# surfaced separately so the model can prefer it over its own guess.
SAFETY_LINE_PATTERN = re.compile(r"(?im)^[ \t]*Safety:[ \t]*(safe|unsafe)[ \t]*$\n?\n?")


def extract_safety_tag(content: str) -> tuple[str, str | None]:
    """
    Strip a `Safety: safe|unsafe` declaration line out of document content.

    Returns the unchanged content plus a lowercased tag string if a Safety: line was found,
    or None if not.

    The tag is lowercased for consistency, so "Safety: Unsafe" and "Safety: unsafe" both
    return "unsafe". The returned content has the Safety: line and one trailing blank line
    (if any) removed, so the model doesn't see it in the indexed text and can rely on
    the separate safety metadata
    """

    match = SAFETY_LINE_PATTERN.search(content)

    if not match:
        return content, None
    return content[: match.start()] + content[match.end() :], match.group(1).lower()


@dataclass
class RetrievedContext:
    """
    A retrieved chunk plus the metadata needed to cite it in the answer.

    Parameters:
        content: Text retrieved from the knowledge base.
        source: Source file name used for citation.
        page: Zero-based page number for PDFs, or None for text files.
        safety: Source doc's declared "safe"/"unsafe" tool classification, or
            None if the doc doesn't declare one.

    RetrievedContext is a small container for "one retrieved chunk plus its citation metadata."
    It exists so the code can pass around a single object instead of a loose tuple/dict with
    four separate values: content, source, page, safety
    It also gives a builtin citation property, so callers can ask for a formatted citation
    without repeating formatting logic.
    """
    content: str
    source: str
    page: int | None
    safety: str | None


    @property
    def citation(self) -> str:

        if self.page is None:
            return self.source

        return f"{self.source}, page {self.page + 1}"


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
            recursion_limit. See DEFAULT_MAX_AGENT_STEPS above for why this
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
        (see DEFAULT_MAX_AGENT_STEPS), the run is aborted with a GENERAL
        response explaining why, instead of running away indefinitely — see
        TROUBLESHOOT.MD for the measured incident this guards against.
        """

        # RunnableConfig, not a bare dict: it's the TypedDict .invoke() declares,
        # so the key set below is checked against it instead of being opaque.
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


def scan_document_paths(documents_path: Path) -> list[Path]:
    """
    Return sorted supported files from a single file or directory tree.
    """

    resolved_path = documents_path.expanduser().resolve()

    if not resolved_path.exists():
        raise FileNotFoundError(
            string_table.MSG_DOCUMENT_PATH_NOT_FOUND.format(path=resolved_path)
        )

    if resolved_path.is_file():
        paths = [resolved_path]
    else:
        paths = [
            path
            for path in resolved_path.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_DOCUMENT_EXTENSIONS
        ]

    if not paths:
        extensions = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        raise FileNotFoundError(
            string_table.MSG_NO_SUPPORTED_DOCUMENTS.format(path=resolved_path, extensions=extensions)
        )

    return sorted(paths)


def load_documents( document_paths: list[Path], ) -> list[Document]:
    """
    Load all scanned document paths into LangChain Document objects.
    """

    docs: list[Document] = []
    for path in document_paths:
        loaded_docs = load_document(path)
        docs.extend(loaded_docs)
    return docs


def load_document(path: Path) -> list[Document]:
    """
    Load one supported document and normalize useful metadata.

    Try your best to KEEP the documents SHORT!

    Give good examples and great information of the subject just enough
    for digestion _-__---_O<

    """

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        loader = PyPDFLoader(str(path))
    elif suffix in {".md", ".txt"}:
        loader = TextLoader(str(path), encoding="utf-8", autodetect_encoding=True)
    else:
        raise ValueError(string_table.MSG_UNSUPPORTED_DOCUMENT_TYPE.format(path=path))

    docs = loader.load()
    safety = None
    if docs:
        docs[0].page_content, safety = extract_safety_tag(docs[0].page_content)
    for doc in docs:
        doc.metadata["source"] = str(path)
        doc.metadata["file_type"] = suffix.lstrip(".")
        if safety:
            doc.metadata["safety"] = safety
    return docs


def etoi(name: str, default: int) -> int:
    """
    Read a positive integer from the environment and convert it to int
    - or fall to a default.
    similar to atoi() since env are strings and we need an int

    Parameters:
        name: Environment variable to read. Unset or empty falls back.
        default: Value used when the variable isn't set.

    Raises RuntimeError with the offending variable named when the value isn't
    a positive integer, so a typo in .env fails loudly instead of silently
    reverting to the default.
    """

    raw_val = os.getenv(name)

    if not raw_val:
        return default
    #  ok, so
    try: # and try again.
        value = int(raw_val)
    except ValueError:
        raise RuntimeError(string_table.MSG_INVALID_INT_ENV.format(name=name, value=raw_val)) from None

    if value <= 0:
        raise RuntimeError(string_table.MSG_INVALID_INT_ENV.format(name=name, value=raw_val))
    return value


def split_documents(
    docs: list[Document],
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[Document]:
    """
    Split loaded documents into smaller chunks for retrieval.

    Parameters:
        docs: Loaded documents to split.
        chunk_size: Characters per chunk. None (the default) resolves
            CHATBOT_CHUNK_SIZE from .env, falling back to DEFAULT_CHUNK_SIZE.
        chunk_overlap: Characters adjacent chunks share. None resolves
            CHATBOT_CHUNK_OVERLAP from .env, falling back to
            DEFAULT_CHUNK_OVERLAP.

    Explicit arguments take precedence over .env so a caller can still stick values directly!
    """

    size = chunk_size if chunk_size is not None else etoi(string_table.ENV_CHUNK_SIZE, DEFAULT_CHUNK_SIZE)

    overlap = (
        chunk_overlap
        if chunk_overlap is not None
        #convert an env variable supposed to be an int to an int
        else etoi(string_table.ENV_CHUNK_OVERLAP, DEFAULT_CHUNK_OVERLAP)

    )

    # RecursiveCharacterTextSplitter rejects this too, but its message doesn't
    # name the .env variables that produced the values.
    if overlap >= size:
        raise RuntimeError(
            string_table.MSG_CHUNK_OVERLAP_TOO_LARGE.format(
                overlap_name=string_table.ENV_CHUNK_OVERLAP,
                overlap=overlap,
                size_name=string_table.ENV_CHUNK_SIZE,
                size=size,
            )
        )

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
    )
    return text_splitter.split_documents(docs)


def build_embeddings(model_name: str = DEFAULT_EMBEDDING_MODEL) -> HuggingFaceEmbeddings:
    """
    Create the local embedding model used for semantic search.
    """

    return HuggingFaceEmbeddings(model_name=model_name)


def build_vectors(
    chunks: list[Document],
    embeddings: HuggingFaceEmbeddings,
) -> InMemoryVectorStore:
    """
    Embed chunks and store the vectors in memory for this process.
    """

    return InMemoryVectorStore.from_documents(chunks, embeddings)


def context_from_document(doc: Document) -> RetrievedContext:
    """
    Attempt to convert LangChain core document base metadata
    into the app's citation format.
    """

    source = str(doc.metadata.get("source", "unknown"))
    page = doc.metadata.get("page")
    safety = doc.metadata.get("safety")

    return RetrievedContext(
        content=doc.page_content,
        source=Path(source).name if source != "unknown" else source,
        page=page if isinstance(page, int) else None,
        safety=safety if isinstance(safety, str) else None,
    )


def build_retrieval_tool(vector_store: InMemoryVectorStore, retrieval_k: int) -> BaseTool:
    """
    Build a retrieve_document_context tool bound to one vector store and k.

    Each RagAssistant instance calls this once in __init__ so the tool closes
    over instance-scoped vector_store/retrieval_k rather than module globals.
    """


    @tool
    def retrieve_document_context(query: str) -> str:
        """
        Search the local knowledge base for chunks relevant to the query.
        this retrieval tool is exposed to the agent.

        It takes a text query from the model.
        It calls the bound vector store to find the most relevant document chunks.

        If no chunks match, it returns a fallback message indicating that no relevant context was found.
        If chunks are found, it formats each one as a retrieval result with:
         - a citation based on the source file/page
         - the chunk content
         - an optional safety note if the source document declared one that returned string is then
         handed back to the agent so it can decide whether to use that context in its final answer.


        Call this before answering questions that may be covered by the local
        knowledge base. Returns the most relevant chunks with citations, or an
        explicit message saying nothing relevant was found so you can fall
        back to a GENERAL: answer.


        """
        similar_docs = vector_store.similarity_search(query, k=retrieval_k)

        if not similar_docs:
            return string_table.MSG_NO_RELEVANT_CONTEXT

        contexts = [context_from_document(doc) for doc in similar_docs]

        return "\n\n".join(
            string_table.MSG_RETRIEVAL_RESULT_HEADER.format(index=index, citation=context.citation)
            + (
                string_table.MSG_RETRIEVAL_SAFETY_SUFFIX.format(safety=context.safety)
                if context.safety
                else ""
            )
            + string_table.MSG_RETRIEVAL_RESULT_BODY.format(content=context.content)
            for index, context in enumerate(contexts, start=1)
        )

    return retrieve_document_context


def system_prompt(path: Path | None = None) -> str:
    """
    Load the instruction prompt that drives tool-calling retrieval and the answer contract.

    Parameters:
        path: Custom prompt file to load instead of the bundled default at
            DEFAULT_SYSTEM_PROMPT_PATH.
    """
    prompt_path = path or DEFAULT_SYSTEM_PROMPT_PATH

    return prompt_path.read_text(encoding="utf-8").rstrip("\n")
