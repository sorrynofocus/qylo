# qylo

> **Naming.** Qylo grew out of an earlier prototype named `qna-chatbot`; the working title before that was `toolbot-cli`. The package and CLI were renamed to `qylo` on 2026-08-29, so every `uv run qylo ...` example below is current. The old names are kept on purpose in `docs/TROUBLESHOOT.MD` (append-only history) and in the dated "Landed" entries of `CLAUDE.md` / `AGENTS.md`, which record measurements taken against the old image tag.

A local Retrieval-Augmented Generation (RAG) CLI assistant for querying a folder of PDF/Markdown/TXT documentation built for internal CLI-tool docs, where remembering every tool's exact flags is the actual problem. It ingests documents with HuggingFace embeddings into an in-memory vector store, then hands a chat model (Azure OpenAI or a local OpenAI-compatible server) a **retrieval tool** rather than pre-fetched context: the model decides for itself whether and how many times to search the knowledge base before answering, instead of always retrieving up front. Answers are combined with a small safety contract so the same assistant can also propose — and, opt-in, execute — CLI commands grounded in the docs.

This project was designed on my older Laptop - the Lenovo Thinkpad T15G with the following specs:


| HW | Description | 
|---|---|
| CPU | Intel(R) Core(TM) i9-10885H CPU @ 2.40GHz (2.40 GHz) |
| RAM | 64.0 GB (63.7 GB usable) |
| GPU | NVIDIA GeForce RTX 2080 Super with Max-Q Design (8 GB VRAM) |
| Storage | 1.61 TB of 3.64 TB used |

For local work, I've decided NOT to use the GPU, but rather CPU. This research was done to assume placing it on a system with limited GPU resources. 


## Overview

### Why this exists

Internal CLI tools accumulate flags faster than anyone can remember them. The documentation usually exists — it's just spread across a folder of READMEs nobody rereads. This is an attempt at the obvious fix: point a model at that folder and ask in plain English, then let it go one step further and *compose the command* for you, with a safety gate in front of actually running it.

It is also, deliberately, a learning project. The code favors being readable over being clever, uses `argparse` and plain console output instead of a TUI framework, and keeps each stage visible rather than hidden behind abstraction. Where a design decision was reversed, the reasoning is recorded in `docs/TROUBLESHOOT.MD` rather than quietly deleted.

### What kind of RAG this is

RAG implementations sit on a spectrum. This one is **agentic RAG**, which is a step above the most common starting point but well short of the state of the art:

| Approach | How retrieval happens | Where this project sits |
|---|---|---|
| **Naive RAG** | Always retrieve top-k, stuff into the prompt, generate. One shot, no decision. | Not this. |
| **Agentic RAG** | Retrieval is a *tool*. The model decides whether to search, and can search repeatedly with refined queries before answering. | **This project.** |
| **Advanced RAG** | Everything above, plus reranking, hybrid keyword+vector search, query rewriting/decomposition, HyDE, graph-based retrieval, persistent and incrementally-updated indexes, evaluation harnesses. | Not attempted. |

The agentic part is genuine — `RagAssistant` hands `create_agent` a `retrieve_document_context` tool and the model chooses when to call it — but everything *around* retrieval is deliberately basic. Retrieval is pure cosine similarity over one embedding model, with no reranking, no hybrid search, no query rewriting, and no filtering by metadata. Chunking is fixed-size character splitting, not semantic or structure-aware. If you are evaluating RAG approaches, treat this as a well-documented reference point, not a recommendation.

### Technology overview

| Layer | Choice | Note |
|---|---|---|
| Orchestration | `langchain.agents.create_agent` (LangChain 1.x / LangGraph) | Tool-calling loop, capped at 10 steps |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` | 384-dim, runs locally, always free |
| Vector store | `InMemoryVectorStore` | Rebuilt every run; nothing persists to disk |
| Chat model | Azure OpenAI **or** local llama.cpp | Chosen by `CHATBOT_MODEL_PROVIDER`; `model_provider.py` is the only seam |
| Response validation | Pydantic `ContractResponse` via `ToolStrategy` | Schema-enforced, with a text-parsing fallback |
| Telemetry | Opt-in `--usage` / `--usagelog` | Two layers: LangChain callbacks + httpx wire hooks |

### A dependency worth knowing about: structured outputs

The most important thing this project relies on isn't a library — it's an API *capability*. The `ANS`/`GENERAL`/`CMD`/`UNSAFE` contract is what decides whether anything is allowed to execute, so getting that label right matters more than getting the prose right. Rather than trusting the model to write the label correctly as free text, `RagAssistant.__init__` passes `response_format=ToolStrategy(schema=ContractResponse)` to `create_agent`, which forces the answer through a validated Pydantic schema.

That only works if the backend supports **structured outputs**, and support is uneven:

- **Azure OpenAI** — supported, and gated on the API version. Structured outputs landed in `2024-08-01-preview`, which is the concrete reason `AZURE_OPENAI_API_VERSION` is pinned in `.env` rather than left to a default (see [Configuration](docs/SETUP.md#configuration)). Point this at an older API version and the reliable path silently stops being available.
- **Local llama.cpp** — depends on the GGUF chat template, not on llama.cpp itself. Measured at 90% (18/20) on a sample batch, versus 10/10 for Azure after a schema rewrite.

That gap is why `parse_model_response` still exists. It is not dead code and not legacy: it is the fallback for backends that don't reliably honor a forced structured response. Both paths converge on the same `ModelResponse`, so the rest of the app never has to know which one ran.

### Limitations and expectations

Known and deliberate, not oversights:

- **No persistence.** Every run rescans, re-chunks, re-embeds. Fine for a folder of READMEs; unworkable for a large corpus. There is no cache, no incremental update, and no index on disk.
- **Retrieval quality is basic.** Similarity search only. A question phrased differently from the documentation may miss, and `-k` is the only tuning knob exposed.
- **Executed commands are not sandboxed or allowlisted.** `cli.py::run_command` runs through the system shell with `shell=True`. The safety model is the `CMD`/`UNSAFE` contract plus explicit `--exe`/`--yolo` opt-in — there is no allowlist, no deny-pattern matching, and no audit log. This is a known gap, documented rather than hidden.
- **Ungrounded command requests rely on model judgment.** When a command request matches no document, there's no `Safety:` tag to check and nothing deterministic backs up the `CMD` vs `UNSAFE` call. See `docs/TROUBLESHOOT.MD`'s "Two open gaps."
- **Local inference is slow without a GPU.** ~4.9 tok/s on the hardware above means minutes per answer, not seconds. See [Provider comparison](docs/USAGE.md#provider-comparison-measured).
- **Token estimates are approximate.** `cl100k_base` is applied uniformly across providers; the provider-reported counts are the billing truth.
- **No automated test suite.** Verification is smoke-test style.

Reasonable expectations: this answers questions about a folder of documentation accurately and with citations, and composes plausible CLI commands from documented tools. It is not a production knowledge base, not a general coding agent, and not a safe autonomous command executor.

## Project structure

```text
.
├── src/qylo/
│   ├── cli.py                 # argparse entry point, orchestration, execution-safety gate
│   ├── rag.py                  # ingestion pipeline + agentic RagAssistant (retrieval tool + create_agent)
│   ├── response_contract.py    # ANS/GENERAL/CMD/UNSAFE parser
│   ├── model_provider.py       # Azure / local chat-model construction
│   ├── telemetry.py            # opt-in --usage/--usagelog AI-usage measurement (calls, bytes, tokens, retries)
│   └── string_table.py         # centralized user-facing/error string constants, imported by every module above
├── data/documents/              # sample knowledge base (CLI-tool READMEs)
├── infra/
│   ├── azure/                   # Bicep template + deploy.py to (re)provision the Azure OpenAI resource
│   └── docker/                  # Dockerfile + compose to run the app with no host install
├── docs/
│   ├── BACKLOG.md                 # Open work that has YET not started!
│   ├── SETUP.md                 # install, provider choice, .env reference
│   ├── USAGE.md                 # flags, examples, telemetry, error cases
│   ├── ARCHITECTURE.md          # concepts, design rationale, full call-flow diagram
│   └── TROUBLESHOOT.MD          # dated debugging log / known gotchas
├── AGENTS.md                    # agent operating instructions (Codex, Cursor, Copilot, Claude Code)
├── CLAUDE.md                    # one-line pointer that imports AGENTS.md
├── .env.example                 # config template — copy to .env and fill in
└── pyproject.toml
```

## How it works

> For the full function-by-function call sequence of one invocation
> (diagram + numbered walkthrough), see
> [Application workflow](docs/ARCHITECTURE.md#application-workflow-current) in
> `docs/ARCHITECTURE.md`.

This is "agentic RAG," not the more common "naive RAG" (always retrieve top-k, stuff into the prompt, generate). `RagAssistant` (in `rag.py`) builds one retrieval tool, `retrieve_document_context`, bound to the in-memory vector store, and hands it to a `langchain.agents.create_agent` tool-calling loop along with the chat model. For each question:

1. The agent receives the plain question — no context is pre-fetched.
2. It decides whether to call `retrieve_document_context(query)`, and can call it more than once with a refined query if the first results look incomplete.
3. Once it has enough (or decides a lookup won't help), it writes a final answer labeled with the contract below.

The model classifies every request by **intent first** — is this a command/tool-execution request, or a knowledge question — before considering whether anything was found in the knowledge base. A command request always resolves to `CMD:`/`UNSAFE:`, grounded or not (composing it from general knowledge if nothing relevant was retrieved); a knowledge question resolves to `ANS:`/`GENERAL:`. This matters because "nothing grounded" means something different for each: an ungrounded command should still get a real answer, while an ungrounded question gets a disclaimed general-knowledge one.

The model response uses a small STT-style contract:

```text
ANS: normal grounded answer
GENERAL: answer from general knowledge when context doesn't address the question
CMD: one non-destructive executable command
UNSAFE: safety reason
COMMAND: proposed command for an unsafe request
```

Command execution is opt-in. `--exe` executes `CMD:` responses. `UNSAFE:` responses are blocked unless both `--exe` and `--yolo` are provided. This keeps the safety decision separate from the model's answer. `GENERAL:` responses are treated the same as `ANS:` for execution purposes — they never run anything, regardless of `--exe`/`--yolo`.

The final answer above is schema-enforced, not just a label the model is trusted to write correctly as free text: `RagAssistant.__init__` passes `response_format=ToolStrategy(schema=ContractResponse)` to `create_agent` (`rag.py`), so `kind`/`content`/`command` come back as a validated `ContractResponse` (`response_contract.py`) whenever the backend produces one. The old text-parsing (`parse_model_response`) is kept as a fallback for backends that don't produce a forced structured response, not removed. A retrieved doc's own `Safety: unsafe` tag also wins deterministically over the model's own classification — if that tag shows up in this turn's retrieved context, a `CMD` verdict is force-upgraded to `UNSAFE` in code, regardless of what the model concluded. See `docs/TROUBLESHOOT.MD` for the measured reliability numbers behind both changes.

### Grounding a tool's safety in its own doc

A knowledge-base doc can declare whether the tool/command it describes is safe to run unattended, instead of leaving that judgment entirely to the model. Add a `Safety: safe` or `Safety: unsafe` line near the top of the file:

```text
# TagEXE
Safety: safe

Embeds Message tags/data/info at the end of any file.
```

`rag.py::extract_safety_tag` strips this line out of the indexed content at load time and stores it as metadata; `retrieve_document_context` surfaces it alongside the citation (`Source: win-shutdown.md (Safety: unsafe)`), and the model is instructed to prefer it over its own guess when present. Docs with no invocable command (plain libraries/APIs, e.g. `Flogger-README.md`) don't need this line — the model still classifies safety itself for command requests it can't ground.

## Documentation

- [docs/SETUP.md](docs/SETUP.md) — install, provider choice, `.env` reference
- [docs/USAGE.md](docs/USAGE.md) — flags, examples, telemetry, error cases
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — concepts, design rationale, call-flow and sequence diagrams
- [docs/TROUBLESHOOT.MD](docs/TROUBLESHOOT.MD) — dated debugging log and known gotchas
- [docs/BACKLOG.md](docs/BACKLOG.md) — open work: known gaps, planned changes, and why they matter

## Build

```sh
uv build .
```

The package artifact will be written to `dist`.

## Verification

No automated test suite exists yet; verification is smoke-test style (see `docs/TROUBLESHOOT.MD`):

```sh
python -m compileall src
uv lock
uv run qylo --help
```

## References
- https://docs.langchain.com/oss/python/integrations/chat/azure_chat_openai
- https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
- https://github.com/henrytanner52/all-MiniLM-L6-v2

## Credit

This project's original inspiration and a quick leg-up came from:
- https://github.com/AMit090912/PDF-Question-Bot---RAG
- Coding and documentation assistance from ChatGPT (OpenAI), Claude Code (Anthropic), and Co-Pilot (Microsoft)
