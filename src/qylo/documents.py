# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.31
# Scan, load and split the source documents that become the knowledge base.
#
# Stage 2 of the request flow. Called by cli.py; its output feeds retrieval.py.
#
# Purpose:
# Everything between "a folder of files" and "a list of chunked Documents".
# scan_document_paths -> load_documents -> split_documents, in that order.
# Nothing here embeds, indexes or searches - that is retrieval.py - and nothing
# here knows a model exists.
#
# Docs can declare "Safety: safe|unsafe" near the top. extract_safety_tag lifts
# that out of the indexed text and into metadata, where retrieval.py surfaces it
# back to the model and assistant.py uses it to deterministically upgrade
# CMD -> UNSAFE. That upgrade is one-directional on purpose: a doc can make a
# command more restricted, never less.
#
# Usage examples (see README for granular details):
#
# Turn a folder into chunks ready for embedding:
# paths = scan_document_paths(Path("data/documents"))
# chunks = split_documents(load_documents(paths))
#
# Chunking honors CHATBOT_CHUNK_SIZE / CHATBOT_CHUNK_OVERLAP from .env;
# explicit arguments still win over both:
# chunks = split_documents(docs, chunk_size=1500, chunk_overlap=300)
#

from __future__ import annotations

import re
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from qylo import string_table
from qylo.settings import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, positive_int_from_env

SUPPORTED_DOCUMENT_EXTENSIONS = {".pdf", ".md", ".txt"}

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

    size = (
        chunk_size
        if chunk_size is not None
        else positive_int_from_env(string_table.ENV_CHUNK_SIZE, DEFAULT_CHUNK_SIZE)
    )

    overlap = (
        chunk_overlap
        if chunk_overlap is not None
        #convert an env variable supposed to be an int to an int
        else positive_int_from_env(string_table.ENV_CHUNK_OVERLAP, DEFAULT_CHUNK_OVERLAP)

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
