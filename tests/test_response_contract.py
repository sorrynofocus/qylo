# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.30
#
# Purpose:
# Pins the ANS/GENERAL/CMD/UNSAFE response contract - the labels that decide whether
# anything is allowed to execute. Model-free: no provider, no network, no cost.
#
# Run:
# uv run pytest tests/test_response_contract.py

from __future__ import annotations

import pytest
from pydantic import ValidationError

from qylo.response_contract import (
    ContractResponse,
    ResponseKind,
    contract_response_to_model_response,
    parse_model_response,
    parse_unsafe_body,
)


# --- parse_model_response: one test per branch -------------------------------


def test_ans_label_parses_as_answer():
    response = parse_model_response("ANS: flogger writes structured logs.")

    assert response.kind is ResponseKind.ANSWER
    assert response.content == "flogger writes structured logs."
    assert response.command is None


def test_general_label_parses_as_general():
    response = parse_model_response("GENERAL: Herman Melville wrote Moby Dick.")

    assert response.kind is ResponseKind.GENERAL
    assert response.content == "Herman Melville wrote Moby Dick."
    assert response.command is None


def test_cmd_label_puts_the_command_in_both_fields():
    response = parse_model_response("CMD: rg -w flogger data/")

    assert response.kind is ResponseKind.COMMAND
    assert response.command == "rg -w flogger data/"
    assert response.content == "rg -w flogger data/"


def test_unsafe_label_splits_reason_from_command():
    response = parse_model_response(
        "UNSAFE: This shuts the machine down immediately.\nCOMMAND: shutdown /s /t 0"
    )

    assert response.kind is ResponseKind.UNSAFE
    assert response.content == "This shuts the machine down immediately."
    assert response.command == "shutdown /s /t 0"


def test_unlabeled_text_falls_back_to_answer():
    # A missing label must stay forgiving for questions, but it must never
    # become a COMMAND - that is what keeps an unlabeled reply unexecutable.
    response = parse_model_response("flogger writes structured logs.")

    assert response.kind is ResponseKind.ANSWER
    assert response.command is None


def test_label_matching_is_case_insensitive():
    assert parse_model_response("cmd: whoami").kind is ResponseKind.COMMAND


# --- parse_unsafe_body -------------------------------------------------------


def test_unsafe_body_without_command_line_returns_none():
    reason, command = parse_unsafe_body("Deleting the whole disk is not recoverable.")

    assert reason == "Deleting the whole disk is not recoverable."
    assert command is None


def test_unsafe_body_keeps_multiline_reason_and_extracts_command():
    reason, command = parse_unsafe_body("Line one.\nLine two.\nCOMMAND: del /f /s /q C:\\")

    assert reason == "Line one.\nLine two."
    assert command == "del /f /s /q C:\\"


# --- ContractResponse: the schema validator, both directions -----------------


def test_contract_accepts_cmd_with_a_command():
    resp = ContractResponse(kind="CMD", content="lists files", command="ls -la")

    assert resp.command == "ls -la"


def test_contract_rejects_cmd_without_a_command():
    # pytest.raises: assert that the block below raises this exception type.
    # Pydantic wraps the validator's ValueError in a ValidationError.
    with pytest.raises(ValidationError):
        ContractResponse(kind="CMD", content="lists files", command=None)


def test_contract_rejects_unsafe_without_a_command():
    with pytest.raises(ValidationError):
        ContractResponse(kind="UNSAFE", content="destructive", command=None)


def test_contract_accepts_ans_without_a_command():
    resp = ContractResponse(kind="ANS", content="grounded answer")

    assert resp.command is None


def test_contract_rejects_ans_that_carries_a_command():
    with pytest.raises(ValidationError):
        ContractResponse(kind="ANS", content="grounded answer", command="rm -rf /")


def test_contract_rejects_general_that_carries_a_command():
    with pytest.raises(ValidationError):
        ContractResponse(kind="GENERAL", content="ungrounded answer", command="whoami")


# --- contract_response_to_model_response -------------------------------------


def test_contract_response_converts_to_model_response():
    resp = ContractResponse(kind="UNSAFE", content="destructive", command="shutdown /s /t 0")

    converted = contract_response_to_model_response(resp)

    assert converted.kind is ResponseKind.UNSAFE
    assert converted.content == "destructive"
    assert converted.command == "shutdown /s /t 0"
    # raw_text keeps the structured payload for debugging rather than a bare string.
    assert "shutdown" in converted.raw_text
