# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.31
# Print the answer, and the progress tags that lead up to it.
#
# Stage 7 of the request flow. Called by cli.py only.
#
# Purpose:
# Everything Qylo writes to the console, in one place, so cli.py is the entry
# point and not also the display layer. Two jobs and nothing more:
#
#   1. print_stage() - the "[stage] [locality] message" progress echo, so a
#      long ingestion run says which stage it is in and whether that stage is
#      local work or a cloud call.
#   2. print_model_response() - render a parsed ModelResponse for a person,
#      without leaking the ANS:/GENERAL:/CMD:/UNSAFE: contract labels as noise.
#
# This is not a logging subsystem and must not grow into one. Deciding whether
# a command runs is execution.py's job, not this module's - printing a proposed
# command is not the same as offering to run it.
#
# Usage examples (see README for granular details):
#
# Echo one pipeline stage:
# print_stage(string_table.TAG_INGESTION, string_table.TAG_LOCAL, "Scanning docs...")
#
# Show the final answer:
# print_model_response(model_response)
#

from __future__ import annotations

from qylo import string_table
from qylo.response_contract import ModelResponse, ResponseKind


def stage_prefix(stage_tag: str, locality_tag: str) -> str:
    """
    Build a "[stage] [local] " prefix for a progress message.
    """
    return f"{stage_tag} {locality_tag} "


def print_stage(stage_tag: str, locality_tag: str, message: str) -> None:
    """
    Print one progress line with its stage and locality tags.

    Parameters:
        stage_tag: Which pipeline stage this is - string_table.TAG_INGESTION,
            TAG_EMBEDDING or TAG_MODEL_CALL.
        locality_tag: Where the work happens - string_table.TAG_LOCAL or
            TAG_CLOUD.
        message: Already-formatted message text from string_table.

    Exists so the caller reads as one statement per pipeline stage. The eight
    progress prints in main() previously ran 122-148 characters each, over the
    project's own 120-char limit, and buried the pipeline inside them.
    """

    print(stage_prefix(stage_tag, locality_tag) + message)


def print_model_response(response: ModelResponse) -> None:
    """
    Print the parsed response without exposing contract labels as noise.

    Parameters:
        response: Parsed ANS/CMD/UNSAFE response from the model.
    """

    if response.kind is ResponseKind.ANSWER:
        print(response.content)
        return

    if response.kind is ResponseKind.GENERAL:
        print(string_table.MSG_NOT_GROUNDED)
        print(response.content)
        return

    if response.kind is ResponseKind.COMMAND:
        print(string_table.LABEL_COMMAND)
        print(response.command or response.content)
        return

    print(string_table.LABEL_UNSAFE_REQUEST)
    print(response.content or string_table.MSG_UNSAFE_DEFAULT_REASON)

    if response.command:
        print()
        print(string_table.LABEL_PROPOSED_COMMAND)
        print(response.command)
