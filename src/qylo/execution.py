# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.31
# Gate a model-proposed command, then run it.
#
# Stage 8 of the request flow, and the last one. Called by cli.py only.
#
# Purpose:
# "Where does Qylo decide to run something?" should be answerable with a
# filename, and this is it. Two gates guard execution and they are deliberately
# separate: cli.py::main() decides whether execution was authorized at all
# (--exe, or CHATBOT_EXECUTE_COMMANDS=true), and apply_exe_request() below
# decides what a given response kind is allowed to do with that authorization.
# ANS and GENERAL never execute, whatever the flags say. Do not collapse these
# paths - see AGENTS.md, "Guardrails".
#
# normalize_command_for_shell() lives here rather than inline in main() so it
# can be tested. It stays a single call site in main(): a second normalization
# point is the defect TROUBLESHOOT.MD records for 2026-07-29.
#
# Usage examples (see README for granular details):
#
# Gate a parsed response after it has been printed:
# apply_exe_request(model_response, yolo=args.yolo)
#
# Rewrite POSIX quoting before cmd.exe sees it:
# command = normalize_command_for_shell("rg -w 'flogger' data/")
#

from __future__ import annotations

import re
import subprocess

from qylo import string_table
from qylo.response_contract import ModelResponse, ResponseKind

# Matches a POSIX-style 'single-quoted' segment with no embedded double quote.
SINGLE_QUOTED_SEGMENT = re.compile(r"'([^'\"]*)'")


def normalize_command_for_shell(command: str) -> str:
    """
    Rewrite POSIX-style single quotes so cmd.exe treats them as delimiters.

    Parameters:
        command: Command text as the model composed it.

    Models often compose commands with POSIX-style single quotes (rg -w
    'flogger' data/). run_command() runs through cmd.exe, which doesn't treat
    single quotes as argument delimiters - they'd pass through as literal
    characters, so the command would silently search for 'flogger' quotes and
    all. Double quotes are what cmd.exe and most Windows console apps
    understand.

    The Windows check is the caller's, not this function's: keeping the rewrite
    itself platform-independent is what makes it testable anywhere.
    """

    return SINGLE_QUOTED_SEGMENT.sub(r'"\1"', command)


def run_command(command: str) -> None:
    """
    Execute one command string through the system shell.

    Parameters:
        command: Command text produced by a CMD response, or by an UNSAFE
            response when the user also passed --yolo.

    This is intentionally small and visible for learning. Future governance can
    add allowlists, deny patterns, confirmation prompts, and audit logging here.
    """

    print()
    print(string_table.MSG_EXECUTING_COMMAND.format(command=command), flush=True)

    result = subprocess.run(command, shell=True, check=False)

    print(string_table.MSG_COMMAND_EXIT_CODE.format(code=result.returncode))


def apply_exe_request(response: ModelResponse, *, yolo: bool) -> None:
    """
    Apply execution rules after the model response has been printed.

    Parameters:
        response: Parsed model response.
        yolo: Whether the user explicitly allowed UNSAFE command execution.

    Rules:
        ANS: never execute.
        GENERAL: never execute (same guarantee as ANS, regardless of --exe/--yolo).
        CMD: execute when --exe was provided.
        UNSAFE: show reason and command, execute only with --exe --yolo.
    """

    match response.kind:
        case ResponseKind.ANSWER:
            print()
            print(string_table.MSG_NO_COMMAND_PROVIDED)
            return

        case ResponseKind.GENERAL:
            print()
            print(string_table.MSG_GENERAL_NOT_RUN)
            return

        case ResponseKind.COMMAND:
            if not response.command:
                print()
                print(string_table.MSG_CMD_NO_TEXT)
                return
            run_command(response.command)
            return

        case ResponseKind.UNSAFE:
            if not response.command:
                print()
                print(string_table.MSG_UNSAFE_NO_COMMAND)
                return
            if not yolo:
                print()
                print(string_table.MSG_UNSAFE_BLOCKED)
                return
            run_command(response.command)
