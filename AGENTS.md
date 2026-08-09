# AGENTS.md

This file provides guidance to OpenAI Codex and other AGENTS.md-reading tools when working with code in this repository.

## Project overview

The intention of this project is to create a QnA ChatBot that can answer questions based on a given knowledge base. The chatbot's answers should be grounded in the knowledge base provided — it should not generate answers outside of the knowledge base and should reference the source of the information when responding. The chatbot can also be used to determine CLI tool usage using typical NLP, returning an executable command as part of its response.

For example:

Q: `Find all gpt turbo models in westus region in Azure, in detailed table`

A: `az cognitiveservices model list --location westus --query "[?contains(name, 'turbo')].{name:name,version:version}" -o table`

Command execution is disabled by default. Setting `CHATBOT_EXECUTE_COMMANDS=true`, or passing `--exe` for a single invocation, enables execution of `CMD:` responses. `UNSAFE:` responses additionally require `--yolo`. See `CLAUDE.md` for the full ANS/CMD/UNSAFE response contract and how it's implemented.

## Setup and build commands

This project uses the `uv` package manager. Building uses `pyproject.toml` to determine the build configuration.

### Setup commands

1. **Create virtual environment and install dependencies:**
   ```sh
   uv venv
   uv sync
   ```

   Activate the virtual environment to use the tool:
    ```sh
    .venv\Scripts\activate
    ```

2. **Build as an application:**

    ```sh
    uv build .
    ```

    See README's [Build](README.md#build) section for installing the built wheel.

## Repository map

Start with `README.md` for layout/usage. See `ARCHITECTURE.md` for concepts, design rationale, and the full call-flow diagram. Docker packaging and Azure provisioning both live under `infra/` — see `infra/README.md` for which is which.

## Coding style

- Type-hinted signatures (`from __future__ import annotations`, PEP 604 unions).
- `snake_case` functions/variables/modules; `PascalCase` classes/dataclasses.
- PEP 8; lines under 120 chars; prefer f-strings.
- No comments unless the *why* is non-obvious.
- Reuse existing functions/utilities over new abstractions; no speculative features.
- User-facing and error strings live in `string_table.py`, one section per module (`# --- rag.py ---`, etc.) — new or changed strings go there as named constants (`MSG_*`/`ENV_*`), not inline literals.

## File headers (planned — not yet applied to existing files)

New Python files should start with a one-line purpose comment plus `# Author: <name> | Date: YYYY-MM-DD`. Do not retrofit this onto existing files as incidental cleanup — new files only, or when explicitly asked for a header pass.

## Git

Do not stage files or create commits unless the user explicitly asks.

## Pull requests

Follow `.github/pull_request_template.md`. Blank `Description` is not accepted — it feeds release notes. `Details`/`JIRA`/`Related` are optional.

## Guardrails (don't relax without being asked)

This project is built and maintained across multiple models over time (Claude Sonnet 5 originally; later passes may come from other Claude versions or OpenAI models). Every rule below maps to something that broke in practice and was fixed once already — not a stylistic preference. Before removing or "simplifying" any of them, check `TROUBLESHOOT.MD` for the incident it closes.

- Response contract: every reply starts with `ANS:`/`GENERAL:`/`CMD:`/`UNSAFE:` (+ `COMMAND:` line for `UNSAFE`). `ANS`/`GENERAL` never execute; `CMD` needs `--exe`; `UNSAFE` needs `--exe --yolo`. Never collapse these execution paths.
- `rag.py::system_prompt()` classifies intent (command vs. question) before grounding — a command request always resolves to `CMD`/`UNSAFE`, never `GENERAL`, grounded or not. Don't reintroduce the old "grounded-first" reasoning; it's what caused labels to go missing (see `TROUBLESHOOT.MD`).
- Docs may declare `Safety: safe`/`Safety: unsafe` near the top (`rag.py::extract_safety_tag`) for tools with a real invocable command; the model prefers this over its own guess. Only add it to docs describing an actual OS/CLI command, not plain libraries.
- `RagAssistant` only exposes `__init__`/`answer()` — don't reintroduce factory constructors (`from_pdf`, etc.) without a real caller; a previous set were dead code and were removed. `answer()` returns a `ModelResponse`, not a raw string: it tries the schema-enforced structured-response path first (`ToolStrategy(schema=ContractResponse)`), falling back to `parse_model_response()` only if structured output wasn't produced — that fallback stays, it's not dead code.
- Heavy imports (`langchain_huggingface`, etc.) stay deferred inside `main()` so `--help` stays fast.
- `model_provider.py` is the sole abstraction boundary between `rag.py` and the chat backend.
- `cli.py::run_command` has no allowlist/audit logging yet — known gap, not an oversight to silently patch. Windows `cmd.exe` quoting is handled inline in `main()` right after parsing (single-quote-to-double-quote rewrite, `SINGLE_QUOTED_SEGMENT`) — don't reintroduce a second normalization point in `run_command` itself.
- Tool-calling reliability is backend-dependent (Azure reliable; local llama.cpp depends on the GGUF template) — see `TROUBLESHOOT.MD`.

## Current focus / open work

- Landed: intent-first response contract + doc-level `Safety:` tagging (2026-07-29) — fixed `CMD`/`UNSAFE` label reliability on Azure.
- Landed: Windows `cmd.exe` single-quote normalization (2026-07-29) — inline in `cli.py::main()`.
- Landed: telemetry preview redaction fix (2026-08-05) — dropped the `or joined` fallback in `telemetry.py::on_chat_model_start`. `joined` holds every message (system prompt + retrieved chunks); it still feeds the token estimate and content hash, but no longer `preview`. A missing or empty human turn now yields an empty preview instead of system-prompt text in `--usagelog` output.
- Landed: Docker packaging (2026-08-07/08) — `infra/` split into `infra/azure/` + `infra/docker/`, six-stage Dockerfile, first GitHub Actions workflow. Also pinned torch to the CPU wheel index, which required declaring `torch` in `[project.dependencies]` since `[tool.uv.sources]` only binds direct deps. **Built and verified air-gapped**: 9.63GB image with the Qwen GGUF baked in produces a grounded answer on a `--internal` Docker network (no DNS, no egress), and the `CMD`/`UNSAFE` contract still gates execution correctly. `serve` defaults to `-c 16384 --parallel 1` — 4096 silently truncates the agentic loop and the model degenerates. See `TROUBLESHOOT.MD` (2026-08-07, 2026-08-08).
- Landed: schema-enforced response (`ContractResponse` via `create_agent(response_format=ToolStrategy(...))`, 2026-07-29) — Azure fixed via a schema field-description rewrite plus a deterministic `Safety: unsafe` override (CMD→UNSAFE gap: 10/13 → 10/10); local came back 90% (18/20) over a 20-call sample. The text-parsing fallback is intentionally kept, not removed — local isn't proven reliable enough yet to drop it.

## TODO

- CI unverified: `.github/workflows/docker.yml` has never run (no remote yet). Expected first failure is `ENOSPC` from the ~6.5GB model pull against a free runner's ~10-20GB; diagnostic ladder is in the workflow comments. The image itself is verified locally.
- **Azure agent no longer converges (2026-08-08).** Every Azure run burns 5 retrieval calls and stops at the 10-step limit without a final answer — including `GENERAL` questions needing no retrieval. Reproduces on the host, so it is not container-related; the local provider converges fine on the same stack. This inverts the reliability ordering the notes below record. Not bisectable (no commits). See `TROUBLESHOOT.MD` (2026-08-08).
- Local path-attribution gap: the 20-call batch's 2 misses weren't attributed to the structured-output path vs. the text-parsing fallback, so which fix applies (schema tuning vs. tool-calling reliability) is unknown. See `TROUBLESHOOT.MD`'s "Two open gaps, explained" section.
- Ungrounded-destructive-command gap: a command request with no matching doc (no `Safety:` tag to check) has no deterministic safety-net — model judgment alone decides `CMD` vs `UNSAFE`. See `TROUBLESHOOT.MD`'s "Two open gaps, explained" section for why this needs a code change (command-text pattern matching), not just more grounding data.
- See `TROUBLESHOOT.MD` for full detail.

## Testing

There is no automated test suite yet. Verify changes by running the CLI against `data/documents` and checking that answers stay grounded with citations; see `TROUBLESHOOT.MD` for known failure modes and `CLAUDE.md` for smoke-test commands.

## Security considerations

Do not enable execution (`--exe`/`--yolo`) against untrusted input — see the `run_command` guardrail above for why.
