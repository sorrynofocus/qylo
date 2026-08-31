# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.30
#
# Purpose:
# Pins the ingestion helpers that Phase C moves into documents.py - the Safety: tag
# stripper, the supported-file scan, and the chunk-overlap guard. Model-free.
#
# Run:
# uv run pytest tests/test_documents.py

from __future__ import annotations

import pytest

from qylo.rag import extract_safety_tag, scan_document_paths, split_documents


# --- extract_safety_tag ------------------------------------------------------


def test_safety_unsafe_line_is_stripped_and_returned():
    content, safety = extract_safety_tag("Safety: unsafe\n\nHow to shut the machine down.")

    assert safety == "unsafe"
    assert content == "How to shut the machine down."


def test_safety_tag_is_lowercased():
    _, safety = extract_safety_tag("Safety: Unsafe\n\nBody text.")

    assert safety == "unsafe"


def test_safety_safe_line_is_recognized():
    content, safety = extract_safety_tag("Safety: safe\n\nHow to search files.")

    assert safety == "safe"
    assert content == "How to search files."


def test_content_without_a_safety_line_is_unchanged():
    original = "flogger writes structured logs."

    content, safety = extract_safety_tag(original)

    assert content == original
    assert safety is None


# --- scan_document_paths -----------------------------------------------------
# tmp_path is a pytest built-in: a fresh empty directory for this one test.


def test_scan_finds_supported_files_and_sorts_them(tmp_path):
    (tmp_path / "b.txt").write_text("second", encoding="utf-8")
    (tmp_path / "a.md").write_text("first", encoding="utf-8")

    found = scan_document_paths(tmp_path)

    assert [path.name for path in found] == ["a.md", "b.txt"]


def test_scan_ignores_unsupported_extensions(tmp_path):
    (tmp_path / "keep.md").write_text("keep", encoding="utf-8")
    (tmp_path / "skip.json").write_text("{}", encoding="utf-8")

    found = scan_document_paths(tmp_path)

    assert [path.name for path in found] == ["keep.md"]


def test_scan_searches_subdirectories(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "deep.md").write_text("deep", encoding="utf-8")

    found = scan_document_paths(tmp_path)

    assert [path.name for path in found] == ["deep.md"]


def test_scan_accepts_a_single_file(tmp_path):
    single = tmp_path / "one.md"
    single.write_text("one", encoding="utf-8")

    found = scan_document_paths(single)

    assert [path.name for path in found] == ["one.md"]


def test_scan_raises_when_the_path_does_not_exist(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_document_paths(tmp_path / "missing")


def test_scan_raises_when_nothing_supported_was_found(tmp_path):
    (tmp_path / "skip.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        scan_document_paths(tmp_path)


# --- split_documents: the chunk-overlap guard --------------------------------


def test_overlap_equal_to_chunk_size_is_rejected():
    # RecursiveCharacterTextSplitter rejects this too, but its message does not
    # name the .env variables that produced the values.
    with pytest.raises(RuntimeError):
        split_documents([], chunk_size=100, chunk_overlap=100)


def test_overlap_larger_than_chunk_size_is_rejected():
    with pytest.raises(RuntimeError):
        split_documents([], chunk_size=100, chunk_overlap=250)


def test_overlap_smaller_than_chunk_size_is_accepted():
    assert split_documents([], chunk_size=100, chunk_overlap=20) == []
