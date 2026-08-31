# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.30
#
# Purpose:
# Pins the .env-derived settings that Phase C moves into settings.py: the positive-int
# reader (etoi, renamed there to positive_int_from_env) and provider resolution. A typo
# in .env must fail loudly rather than silently reverting to a default. Model-free.
#
# Run:
# uv run pytest tests/test_settings.py

from __future__ import annotations

import pytest

from qylo import string_table
from qylo.model_provider import ModelProvider, get_model_provider
from qylo.rag import etoi

CHUNK_SIZE = string_table.ENV_CHUNK_SIZE
PROVIDER = string_table.ENV_MODEL_PROVIDER


# --- etoi: environment string to positive int --------------------------------


def test_unset_variable_falls_back_to_the_default(monkeypatch):
    monkeypatch.delenv(CHUNK_SIZE, raising=False)

    assert etoi(CHUNK_SIZE, 1000) == 1000


def test_empty_variable_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv(CHUNK_SIZE, "")

    assert etoi(CHUNK_SIZE, 1000) == 1000


def test_valid_value_is_returned_as_an_int(monkeypatch):
    monkeypatch.setenv(CHUNK_SIZE, "512")

    assert etoi(CHUNK_SIZE, 1000) == 512


def test_non_numeric_value_raises_rather_than_defaulting(monkeypatch):
    monkeypatch.setenv(CHUNK_SIZE, "lots")

    with pytest.raises(RuntimeError):
        etoi(CHUNK_SIZE, 1000)


def test_zero_is_rejected(monkeypatch):
    monkeypatch.setenv(CHUNK_SIZE, "0")

    with pytest.raises(RuntimeError):
        etoi(CHUNK_SIZE, 1000)


def test_negative_value_is_rejected(monkeypatch):
    monkeypatch.setenv(CHUNK_SIZE, "-5")

    with pytest.raises(RuntimeError):
        etoi(CHUNK_SIZE, 1000)


# --- get_model_provider ------------------------------------------------------


def test_provider_defaults_to_azure_when_unset(monkeypatch):
    monkeypatch.delenv(PROVIDER, raising=False)

    assert get_model_provider() is ModelProvider.AZURE


def test_provider_local_is_recognized(monkeypatch):
    monkeypatch.setenv(PROVIDER, "local")

    assert get_model_provider() is ModelProvider.LOCAL


def test_provider_is_case_insensitive_and_trimmed(monkeypatch):
    monkeypatch.setenv(PROVIDER, "  AZURE  ")

    assert get_model_provider() is ModelProvider.AZURE


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv(PROVIDER, "bedrock")

    with pytest.raises(RuntimeError):
        get_model_provider()
