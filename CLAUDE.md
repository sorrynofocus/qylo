# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup, build, run

Start with `README.md` for the overview; `docs/SETUP.md` has full setup/install detail and `docs/USAGE.md` has every flag and example. Below are quick start commands during development/testing:

```sh
uv venv
uv sync
.venv\Scripts\activate        # Windows
```

Run a question against the default `data/documents` folder:

```sh
uv run qna-chatbot "What is flogger and what logging features does it support?"
```

Other useful flags: `--documents <folder>` (custom folder), `--doc <file>` (single file), `-k <n>` (retrieved chunk count, default 4), `--exe` (execute a `CMD:` response), `--yolo` (also execute `UNSAFE:` responses, only combined with `--exe`), `--system-prompt <file>` (custom system prompt file instead of the bundled default).

Build the package:

```sh
uv build .
```

No automated test suite exists yet. Verification is currently manual/smoke-test style (see `TROUBLESHOOT.MD`):

```sh
python -m compileall src
uv lock
uv run qna-chatbot --help
```

Docker and Azure provisioning both live under `infra/` — see `infra/README.md` for which is which.

## Configuration (.env)

Model provider is chosen via `CHATBOT_MODEL_PROVIDER=azure|local` (see `.env.example`; full setup/install steps are in `docs/SETUP.md`).

- Azure: `AZURE_OPENAI_ENDPOINT` (resource root only — do **not** append `/openai/v1`), `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_CHAT_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`. Newer models (e.g. `gpt-5-nano`) reject an explicit `temperature` other than the default.
- Local: `LOCAL_OPENAI_BASE_URL`, `LOCAL_MODEL_NAME`, optional `LOCAL_OPENAI_API_KEY` — points at a running llama.cpp server.
- `CHATBOT_EXECUTE_COMMANDS=true` is an env-var equivalent of passing `--exe`.


## Repository map

Start with `README.md` for layout, `docs/SETUP.md` for setup/config, `docs/USAGE.md` for flags and examples. See `ARCHITECTURE.md` for concepts, design rationale, and the full call-flow diagram.

## Coding style

- Type-hinted signatures (`from __future__ import annotations`, PEP 604 unions).
- `snake_case` functions/variables/modules; `PascalCase` classes/dataclasses.
- PEP 8; lines under 120 chars; prefer f-strings.
- Add comments with descriptions and parameter explanations as in summaries in C#. Shorter functions that are obvious do not need comments.
- Reuse existing functions/utilities over new abstractions; no speculative features.
- User-facing and error strings live in `string_table.py`, one section per module (`# --- rag.py ---`, etc.) — new or changed strings go there as named constants (`MSG_*`/`ENV_*`), not inline literals.

## File headers 

- Follow `.github/src_header_template.md` for new Python files for header information.
- Do not retrofit this onto existing files as incidental cleanup, new files only, or when explicitly asked for a header pass.

## Git

- Do not stage files or create commits unless the user explicitly asks.

## Pull requests

- Follow `.github/pull_request_template.md`. Blank `Description` is not accepted; it feeds release notes. `Details`/`JIRA`/`Related` are optional.

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
- Landed: first CI run (2026-08-08, run 31290501806) — `.github/workflows/docker.yml` passed on the first attempt, 32m57s, 9.63GB image matching the local build, air-gap reconfirmed under `--network none`. Disk was never the constraint (145G root, 88G free before reclaim). Trigger is now `workflow_dispatch` only; a full build is too expensive to spend on every push.
- Landed: schema-enforced response (`ContractResponse` via `create_agent(response_format=ToolStrategy(...))`, 2026-07-29) — Azure fixed via a schema field-description rewrite plus a deterministic `Safety: unsafe` override (CMD→UNSAFE gap: 10/13 → 10/10); local came back 90% (18/20) over a 20-call sample. The text-parsing fallback is intentionally kept, not removed — local isn't proven reliable enough yet to drop it.

## TODO

- CI cache is upside-down: `cache-to: type=gha,mode=max` writes ~9.6GB against a 10GB per-repo quota, so it evicts rather than hits — 18m52s of a 30m43s build step (57%) spent exporting a cache that recorded zero hits. Options, cheapest first: `mode=min`, scope the cache to the `llamacpp-builder` stage, or drop `type=gha`. See the comments in `.github/workflows/docker.yml`.
- **Azure agent no longer converges (2026-08-08).** Every Azure run burns 5 retrieval calls and stops at the 10-step limit without a final answer — including `GENERAL` questions needing no retrieval. Reproduces on the host, so it is not container-related; the local provider converges fine on the same stack. This inverts the reliability ordering the notes below record. Not bisectable (no commits). See `TROUBLESHOOT.MD` (2026-08-08).
- Local path-attribution gap: the 20-call batch's 2 misses weren't attributed to the structured-output path vs. the text-parsing fallback, so which fix applies (schema tuning vs. tool-calling reliability) is unknown. See `TROUBLESHOOT.MD`'s "Two open gaps, explained" section.
- Ungrounded-destructive-command gap: a command request with no matching doc (no `Safety:` tag to check) has no deterministic safety-net — model judgment alone decides `CMD` vs `UNSAFE`. See `TROUBLESHOOT.MD`'s "Two open gaps, explained" section for why this needs a code change (command-text pattern matching), not just more grounding data.
- See `TROUBLESHOOT.MD` for full detail.
