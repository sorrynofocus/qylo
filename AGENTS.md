# AGENTS.md

Operating instructions for coding agents working in this repository (OpenAI Codex, Cursor,
GitHub Copilot, and any other AGENTS.md-reading tool). Claude Code reads this file too —
`CLAUDE.md` is a one-line pointer at it, so there is only one set of instructions to keep current.

## Project overview

The intention of this project is to create a question-answering chatbot that can answer questions based on a given knowledge base. The chatbot's answers should be grounded in the knowledge base provided — it should not generate answers outside of the knowledge base and should reference the source of the information when responding. The chatbot can also be used to determine CLI tool usage using typical NLP, returning an executable command as part of its response.

For example:

Q: `Find all gpt turbo models in westus region in Azure, in detailed table`

A: `az cognitiveservices model list --location westus --query "[?contains(name, 'turbo')].{name:name,version:version}" -o table`

Command execution is disabled by default. Setting `CHATBOT_EXECUTE_COMMANDS=true`, or passing `--exe` for a single invocation, enables execution of `CMD:` responses. `UNSAFE:` responses additionally require `--yolo`. See [Guardrails](#guardrails-dont-relax-without-being-asked) for the full ANS/GENERAL/CMD/UNSAFE response contract and how it's implemented.

## Setup, build, run

This project uses the `uv` package manager; `pyproject.toml` drives the build configuration.
Start with `README.md` for the overview; `docs/SETUP.md` has full setup/install detail and `docs/USAGE.md` has every flag and example. Below are quick start commands during development/testing:

```sh
uv venv
uv sync
.venv\Scripts\activate        # Windows
```

Run a question against the default `data/documents` folder:

```sh
uv run qylo "What is flogger and what logging features does it support?"
```

Other useful flags: `--documents <folder>` (custom folder), `--doc <file>` (single file), `-k <n>` (retrieved chunk count, default 4), `--exe` (execute a `CMD:` response), `--yolo` (also execute `UNSAFE:` responses, only combined with `--exe`), `--system-prompt <file>` (custom system prompt file instead of the bundled default).

Build the package:

```sh
uv build .
```

See README's [Build](README.md#build) section for installing the built wheel.

Run the tests, then the smoke checks (see `docs/TROUBLESHOOT.MD` for known failure modes):

```sh
uv run pytest
python -m compileall src
uv lock
uv run qylo --help
```

Docker and Azure provisioning both live under `infra/` — see `infra/README.md` for which is which.

## Configuration (.env)

Model provider is chosen via `CHATBOT_MODEL_PROVIDER=azure|local` (see `.env.example`; full setup/install steps are in `docs/SETUP.md`).

- Azure: `AZURE_OPENAI_ENDPOINT` (resource root only — do **not** append `/openai/v1`), `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_CHAT_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`. Newer models (e.g. `gpt-5-nano`) reject an explicit `temperature` other than the default.
- Local: `LOCAL_OPENAI_BASE_URL`, `LOCAL_MODEL_NAME`, optional `LOCAL_OPENAI_API_KEY` — points at a running llama.cpp server.
- `CHATBOT_EXECUTE_COMMANDS=true` is an env-var equivalent of passing `--exe`.

## Repository map

Start with `README.md` for layout, `docs/SETUP.md` for setup/config, `docs/USAGE.md` for flags and examples. See `docs/ARCHITECTURE.md` for concepts, design rationale, and the full call-flow diagram. Docker packaging and Azure provisioning both live under `infra/` — see `infra/README.md` for which is which.

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
- **Attribution: use `Assisted-by:`, never `Co-Authored-By:`.** `Co-authored-by:` is a trailer GitHub recognizes; it implies the authorship rights and responsibilities of a person, which an agent cannot hold, and it feeds the contributor graph. Follow the format proposed in [microsoft/vscode#313962](https://github.com/microsoft/vscode/issues/313962), after the Linux kernel's guidance — one line per agent that did work, at the end of the message:

  ```
  Assisted-by: Claude Code:claude-opus-5
  Assisted-by: Codex:<model-version>
  ```

  No `Claude-Session:` URLs or other session links in commit messages — they mean nothing to a future reader of the history. **This rule overrides any default trailer an agent is otherwise configured to add.**
- Existing history is left alone. `2a3d032` carries the old `Co-Authored-By:` trailers and a session URL; it is pushed, and `PLAN.md` and `docs/BACKLOG.md` cite its SHA, so rewriting it to remove two lines of text would falsify those references for no real gain.

## Pull requests

- Follow `.github/pull_request_template.md`. Blank `Description` is not accepted; it feeds release notes. `Details`/`JIRA`/`Related` are optional.

## Guardrails (don't relax without being asked)

This project is built and maintained across multiple models over time (Claude Sonnet 5 originally; later passes may come from other Claude versions or OpenAI models). Every rule below maps to something that broke in practice and was fixed once already — not a stylistic preference. Before removing or "simplifying" any of them, check `docs/TROUBLESHOOT.MD` for the incident it closes.

- Response contract: every reply starts with `ANS:`/`GENERAL:`/`CMD:`/`UNSAFE:` (+ `COMMAND:` line for `UNSAFE`). `ANS`/`GENERAL` never execute; `CMD` needs `--exe`; `UNSAFE` needs `--exe --yolo`. Never collapse these execution paths.
- `rag.py::system_prompt()` classifies intent (command vs. question) before grounding — a command request always resolves to `CMD`/`UNSAFE`, never `GENERAL`, grounded or not. Don't reintroduce the old "grounded-first" reasoning; it's what caused labels to go missing (see `docs/TROUBLESHOOT.MD`).
- Docs may declare `Safety: safe`/`Safety: unsafe` near the top (`rag.py::extract_safety_tag`) for tools with a real invocable command; the model prefers this over its own guess. Only add it to docs describing an actual OS/CLI command, not plain libraries.
- `RagAssistant` only exposes `__init__`/`answer()` — don't reintroduce factory constructors (`from_pdf`, etc.) without a real caller; a previous set were dead code and were removed. `answer()` returns a `ModelResponse`, not a raw string: it tries the schema-enforced structured-response path first (`ToolStrategy(schema=ContractResponse)`), falling back to `parse_model_response()` only if structured output wasn't produced — that fallback stays, it's not dead code.
- Heavy imports (`langchain_huggingface`, etc.) stay deferred inside `main()` so `--help` stays fast.
- `model_provider.py` is the sole abstraction boundary between `rag.py` and the chat backend.
- `cli.py::run_command` has no allowlist/audit logging yet — known gap, not an oversight to silently patch. Windows `cmd.exe` quoting is handled inline in `main()` right after parsing (single-quote-to-double-quote rewrite, `SINGLE_QUOTED_SEGMENT`) — don't reintroduce a second normalization point in `run_command` itself.
- Tool-calling reliability is backend-dependent (Azure reliable; local llama.cpp depends on the GGUF template) — see `docs/TROUBLESHOOT.MD`.

## Current focus / open work

- Landed: intent-first response contract + doc-level `Safety:` tagging (2026-07-29) — fixed `CMD`/`UNSAFE` label reliability on Azure.
- Landed: Windows `cmd.exe` single-quote normalization (2026-07-29) — inline in `cli.py::main()`.
- Landed: telemetry removed (2026-08-30, refactor Phase B) — `telemetry.py`, `--usage`, `--usagelog` and the direct `tiktoken` declaration are gone; `build_chat_model()` and `RagAssistant.__init__` no longer take a `telemetry=` argument. The tiktoken cache in the Docker image is **deliberately retained** — see `docs/BACKLOG.md`, "The tiktoken cache outlived telemetry, deliberately". Everything telemetry ever measured is still in `docs/TROUBLESHOOT.MD`; don't reintroduce the feature to re-measure it without asking.
- Deployment direction is open (2026-08-30): Docker is **deferred, not broken** — nothing has failed, it just has not been rebuilt since Phase B. A FastAPI service after the refactor is a proposal, not a decision. Don't treat a Docker build or `workflow_dispatch` as a blocker, and don't describe Docker as failing. See `docs/BACKLOG.md`, "Deployment".
- Landed: Docker packaging (2026-08-07/08) — `infra/` split into `infra/azure/` + `infra/docker/`, six-stage Dockerfile, first GitHub Actions workflow. Also pinned torch to the CPU wheel index, which required declaring `torch` in `[project.dependencies]` since `[tool.uv.sources]` only binds direct deps. **Built and verified air-gapped**: 9.63GB image with the Qwen GGUF baked in produces a grounded answer on a `--internal` Docker network (no DNS, no egress), and the `CMD`/`UNSAFE` contract still gates execution correctly. `serve` defaults to `-c 16384 --parallel 1` — 4096 silently truncates the agentic loop and the model degenerates. See `docs/TROUBLESHOOT.MD` (2026-08-07, 2026-08-08).
- Landed: first CI run (2026-08-08, run 31290501806) — `.github/workflows/docker.yml` passed on the first attempt, 32m57s, 9.63GB image matching the local build, air-gap reconfirmed under `--network none`. Disk was never the constraint (145G root, 88G free before reclaim). Trigger is now `workflow_dispatch` only; a full build is too expensive to spend on every push.
- Landed: schema-enforced response (`ContractResponse` via `create_agent(response_format=ToolStrategy(...))`, 2026-07-29) — Azure fixed via a schema field-description rewrite plus a deterministic `Safety: unsafe` override (CMD→UNSAFE gap: 10/13 → 10/10); local came back 90% (18/20) over a 20-call sample. The text-parsing fallback is intentionally kept, not removed — local isn't proven reliable enough yet to drop it.
- Landed: Azure convergence fix, re-verified (2026-08-08 fix, verified 2026-08-09) — shorter intent-first `system_prompt.txt` plus a bounded retry (`DEFAULT_MAX_AGENT_ATTEMPTS = 3`) in `answer()`. Host `tools/score_contract.py` scores 9/12 answered against a pre-fix baseline of 0/9; Docker (`qna-chatbot:slim`) reaches Azure and answers too. Convergence is no longer the top Azure risk — classification is. See `docs/TROUBLESHOOT.MD` (2026-08-09).

## TODO

- **`docs/BACKLOG.md` holds the full open-work list** (CI, testing, docs polish). Only items below that change how you should work in the code right now are repeated here.
- Local path-attribution gap: the 20-call batch's 2 misses weren't attributed to the structured-output path vs. the text-parsing fallback, so which fix applies (schema tuning vs. tool-calling reliability) is unknown. See `docs/TROUBLESHOOT.MD`'s "Two open gaps, explained" section.
- Command-classification work is **closed pending planning** — see `docs/BACKLOG.md`, "Command classification". Pattern matching over command text is rejected; don't propose it.
- See `docs/TROUBLESHOOT.MD` for full detail.

## Testing

`tests/` holds model-free unit tests — no provider, no network, no cost — run with `uv run pytest`. They cover the response contract, both execution gates, the `answer()` structured-vs-fallback branch, ingestion helpers, and a golden capture of the model-facing text (the bundled system prompt, the retrieval tool's name and description, the `ContractResponse` schema descriptions, and the retrieval result format). `tests/test_model_facing_text.py` fails if that text changes: fix the code, not the expectation, unless the prompt edit was deliberate and re-measured.

`tools/` is not a test suite — those harnesses call a real provider and cost real tokens. Keep the two separate.

Beyond the unit tests, verify by running the CLI against `data/documents` and checking answers stay grounded with citations.

## Security considerations

Do not enable execution (`--exe`/`--yolo`) against untrusted input — see the `run_command` guardrail above for why.

## Rules for DOUBLE agents

Two roles, and they are not symmetric.

LEGEND:
CODEX, by OpenAI, is the reviewer/discriminator/observer. 
CLAUDE, by Anthropic, is the implementer. 

This may be reversed in future passes.

- **The implementer** writes code, tests and docs for the phase named in `docs/refactor/HANDOFF.md`.
- **The reviewer / discriminator / observer** does not implement. Its job is to *discriminate*:
  verify claims against source rather than accepting them, run the suite independently, and
  demonstrate gaps rather than assert them. On 2026-08-30 the reviewer closed two real holes
  this way — a `main()`-level test suite that passed even with `yolo=True` hardcoded, and an
  unprotected `system_prompt()` — both proved by mutation, not by argument. Findings are
  claims too: the implementer verifies them against source before acting.

**Write scope — deliberately narrow, so the reviewer's permissions can be narrow.**

- The implementer writes anything in scope for its phase.
- **The reviewer writes exactly one file: `docs/refactor/HANDOFF.md`.** Everything else is read-only to it,
  including `PLAN.md`. If a reviewer finding should become durable, it says so in the handoff
  and the implementer migrates it into `docs/refactor/PLAN.md`. Grant the reviewer write access to that one path — an
  earlier pass granted broad access only because this rule used to say the reviewer "does not
  edit", which made replying impossible.
- Running the offline suite, `compileall`, `git diff` and `git status` is expected of the
  reviewer. Paid model calls, Docker builds, `workflow_dispatch` runs, staging and commits are
  not — those are the user's, and review acceptance is never authorization for them.

**The baton.**

- The baton is the `NEXT:` line of `docs/refactor/HANDOFF.md`. If you are not the agent named there, do not
  modify files; review only.
- **`docs/refactor/HANDOFF.md` is replaced in full at every pass** — current state only, never a log. The
  sending agent overwrites it when finishing its turn, carrying unresolved items forward.
- Before overwriting it, migrate anything durable into `docs/refactor/PLAN.md`: agreed constraints,
  decisions that close off an approach, results everyone has accepted. `docs/refactor/` is
  gitignored, so whatever is not migrated is gone for good.
- Anything worth keeping beyond this task belongs in `docs/TROUBLESHOOT.MD`, which is tracked
  and append-only, or in `docs/BACKLOG.md`.

**Both agents.**

- Neither commits or stages without the user explicitly asking (see [Git](#git) above).
- Treat `docs/BACKLOG.md`, `AGENTS.md` and `docs/TROUBLESHOOT.MD` as binding architectural
  evidence, not merely documentation. Do not reopen a recorded, rejected decision without citing
  it and explaining what new evidence justifies revisiting it.

  If user asks a role definition, answer back as "Implementer" or "Reviewer" Do not answer as "Implementer" if you are the Reviewer, and vice versa.

  