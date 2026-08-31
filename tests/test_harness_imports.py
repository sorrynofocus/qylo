# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.31
#
# Purpose:
# The three harnesses in tools/ import from the package, and nothing in the suite
# imported them before this file - so a rename in src/ left pytest green and
# `python -m compileall` green too (it checks syntax, not whether a name resolves).
# Phase C moved every one of their imports, which is exactly the change that gap
# hides. Importing each module executes its import block for real.
#
# This is necessary but NOT sufficient. It proves the from-imports resolve at import
# time; it cannot see an attribute read inside main(), such as verify_retry's
# settings.DEFAULT_MAX_AGENT_ATTEMPTS. Those are still only covered by running the
# harness, which costs real tokens. Do not read a green test here as "the harnesses
# work" - read it as "their imports are not stale".
#
# load_dotenv is neutralized before each module executes: these scripts call it at
# module level, and a developer's real .env would otherwise leak provider and
# execution settings into the rest of the session.
#
# Run:
# uv run pytest tests/test_harness_imports.py

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
HARNESSES = ["score_contract", "stream_agent", "verify_retry"]


@pytest.mark.parametrize("name", HARNESSES)
def test_harness_imports_resolve(monkeypatch, name):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)

    path = TOOLS / f"{name}.py"
    assert path.exists(), f"{path} is missing - update HARNESSES if a harness was renamed"

    spec = importlib.util.spec_from_file_location(f"qylo_harness_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert callable(module.main)
