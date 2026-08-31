# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.31
# Embed the chunks, index them, and hand the model a tool that searches them.
#
# Stage 3 of the request flow. Called by cli.py; the tool it builds is used by
# assistant.py.
#
# Purpose:
# Every vector-store detail lives behind this one module: which embedding model
# is used, where the vectors are kept, how a similarity hit is turned into a
# citation, and exactly what text the model reads back. Nothing flows back the
# other way - documents.py produces Documents, retrieval.py consumes them.
#
# The store is in-memory and lives for exactly one process. Nothing is cached to
# disk, so every run re-indexes from scratch.
#
# Usage examples (see README for granular details):
#
# Index chunks, then build the tool the agent calls:
# store = build_vectors(chunks, build_embeddings())
# tool = build_retrieval_tool(store, DEFAULT_RETRIEVAL_K)
#

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.tools import BaseTool, tool
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_huggingface import HuggingFaceEmbeddings

from qylo import string_table
from qylo.settings import DEFAULT_EMBEDDING_MODEL


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


def format_retrieval_results(contexts: list[RetrievedContext]) -> str:
    """
    Render retrieved chunks as the numbered, cited text the model reads back.

    Parameters:
        contexts: Retrieved chunks, in the order the vector store returned them.

    One block per chunk, separated by a blank line: a "[n] Source: ..." header,
    a "(Safety: ...)" suffix when the source document declared one, then the
    chunk text. The safety marker is not decoration - assistant.py scans the
    message history for it to promote CMD to UNSAFE, so the exact wording is
    pinned by tests/test_model_facing_text.py.
    """

    results: list[str] = []

    for index, context in enumerate(contexts, start=1):
        result = string_table.MSG_RETRIEVAL_RESULT_HEADER.format(
            index=index, citation=context.citation
        )

        if context.safety:
            result += string_table.MSG_RETRIEVAL_SAFETY_SUFFIX.format(safety=context.safety)

        result += string_table.MSG_RETRIEVAL_RESULT_BODY.format(content=context.content)
        results.append(result)

    return "\n\n".join(results)


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

        return format_retrieval_results([context_from_document(doc) for doc in similar_docs])

    return retrieve_document_context
