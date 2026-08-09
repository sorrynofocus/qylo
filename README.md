# qylo

> **Naming.** The repo is now `qylo`, and the project will take that name soon. `qna-chatbot` (the package name and CLI command) and the earlier working title `toolbot-cli` are the old names. **For now, treat `qna-chatbot` as the project** — every `uv run qna-chatbot ...` example below is current, not stale. Renaming the package itself would touch `pyproject.toml`, the console-script entry point, and every doc's example commands, so it's deliberately deferred.

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

It is also, deliberately, a learning project. The code favors being readable over being clever, uses `argparse` and plain console output instead of a TUI framework, and keeps each stage visible rather than hidden behind abstraction. Where a design decision was reversed, the reasoning is recorded in `TROUBLESHOOT.MD` rather than quietly deleted.

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

- **Azure OpenAI** — supported, and gated on the API version. Structured outputs landed in `2024-08-01-preview`, which is the concrete reason `AZURE_OPENAI_API_VERSION` is pinned in `.env` rather than left to a default (see [Configuration](#configuration)). Point this at an older API version and the reliable path silently stops being available.
- **Local llama.cpp** — depends on the GGUF chat template, not on llama.cpp itself. Measured at 90% (18/20) on a sample batch, versus 10/10 for Azure after a schema rewrite.

That gap is why `parse_model_response` still exists. It is not dead code and not legacy: it is the fallback for backends that don't reliably honor a forced structured response. Both paths converge on the same `ModelResponse`, so the rest of the app never has to know which one ran.

### Limitations and expectations

Known and deliberate, not oversights:

- **No persistence.** Every run rescans, re-chunks, re-embeds. Fine for a folder of READMEs; unworkable for a large corpus. There is no cache, no incremental update, and no index on disk.
- **Retrieval quality is basic.** Similarity search only. A question phrased differently from the documentation may miss, and `-k` is the only tuning knob exposed.
- **Executed commands are not sandboxed or allowlisted.** `cli.py::run_command` runs through the system shell with `shell=True`. The safety model is the `CMD`/`UNSAFE` contract plus explicit `--exe`/`--yolo` opt-in — there is no allowlist, no deny-pattern matching, and no audit log. This is a known gap, documented rather than hidden.
- **Ungrounded command requests rely on model judgment.** When a command request matches no document, there's no `Safety:` tag to check and nothing deterministic backs up the `CMD` vs `UNSAFE` call. See `TROUBLESHOOT.MD`'s "Two open gaps."
- **Local inference is slow without a GPU.** ~4.9 tok/s on the hardware above means minutes per answer, not seconds. See [Provider comparison](#provider-comparison-measured).
- **Token estimates are approximate.** `cl100k_base` is applied uniformly across providers; the provider-reported counts are the billing truth.
- **No automated test suite.** Verification is smoke-test style.

Reasonable expectations: this answers questions about a folder of documentation accurately and with citations, and composes plausible CLI commands from documented tools. It is not a production knowledge base, not a general coding agent, and not a safe autonomous command executor.

## Project structure

```text
.
├── src/qna_chatbot/
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
├── ARCHITECTURE.md              # concepts, design rationale, full call-flow diagram
├── CLAUDE.md                    # Claude Code operating instructions
├── AGENTS.md                    # cross-tool agent instructions (Codex, etc.)
├── TROUBLESHOOT.MD              # debugging log / known gotchas
├── .env.example                 # config template — copy to .env and fill in
└── pyproject.toml
```

## How it works

> For the full function-by-function call sequence of one invocation
> (diagram + numbered walkthrough), see
> [Application workflow](ARCHITECTURE.md#application-workflow-current) in
> `ARCHITECTURE.md`.

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

The final answer above is schema-enforced, not just a label the model is trusted to write correctly as free text: `RagAssistant.__init__` passes `response_format=ToolStrategy(schema=ContractResponse)` to `create_agent` (`rag.py`), so `kind`/`content`/`command` come back as a validated `ContractResponse` (`response_contract.py`) whenever the backend produces one. The old text-parsing (`parse_model_response`) is kept as a fallback for backends that don't produce a forced structured response, not removed. A retrieved doc's own `Safety: unsafe` tag also wins deterministically over the model's own classification — if that tag shows up in this turn's retrieved context, a `CMD` verdict is force-upgraded to `UNSAFE` in code, regardless of what the model concluded. See `TROUBLESHOOT.MD` for the measured reliability numbers behind both changes.

### Grounding a tool's safety in its own doc

A knowledge-base doc can declare whether the tool/command it describes is safe to run unattended, instead of leaving that judgment entirely to the model. Add a `Safety: safe` or `Safety: unsafe` line near the top of the file:

```text
# TagEXE
Safety: safe

Embeds Message tags/data/info at the end of any file.
```

`rag.py::extract_safety_tag` strips this line out of the indexed content at load time and stores it as metadata; `retrieve_document_context` surfaces it alongside the citation (`Source: win-shutdown.md (Safety: unsafe)`), and the model is instructed to prefer it over its own guess when present. Docs with no invocable command (plain libraries/APIs, e.g. `Flogger-README.md`) don't need this line — the model still classifies safety itself for command requests it can't ground.

## Setup

### 1. Create the Python environment

```sh
uv venv
uv sync
```

Activate it on Windows:

```sh
.venv\Scripts\activate
```

### 2. Choose a model provider

`CHATBOT_MODEL_PROVIDER` in `.env` picks which one the app uses — see [Configuration](#configuration) below for the exact `.env` fields once you've set one up.

#### Option A: Local inference (llama.cpp)

Runs a model on your own machine via [llama.cpp](https://github.com/ggml-org/llama.cpp)'s OpenAI-compatible server, free and private, but slower without a GPU (see [Provider comparison](#provider-comparison-measured) below).

1. **Check for an NVIDIA GPU** (optional; llama.cpp falls back to CPU if you skip this or don't have one):
   ```sh
   nvidia-smi
   ```
   Note the reported CUDA version.

2. **Install llama.cpp.** Go to the [releases page](https://github.com/ggml-org/llama.cpp/releases)
   and download the asset matching your setup — always take the *latest*
   release's build, not a pinned one (`XXX` below stands for that release's
   build number, e.g. `b9946`):
   - **CPU-only** (no GPU, or skipping GPU acceleration — this project's own
     measurements in [Provider comparison](#provider-comparison-measured)
     below used this build): `llama-bXXX-bin-win-cpu-x64.zip`
   - **NVIDIA GPU, CUDA 12.x**: `llama-bXXX-bin-win-cuda-12.4-x64.zip`

   Extract it somewhere like `C:\Program Files\llamacpp` and add that folder
   to your `PATH`.

Verify:

   ```sh
   llama-cli --version
   ```

If you installed the GPU build, confirm your NVIDIA drivers/CUDA toolkit are set up correctly — you should see these GPU-specific DLLs under `C:\Program Files\llamacpp`:

```text
cublas64_*.dll
cudart64_*.dll
cusparse64_*.dll
cublasLt64_*.dll
```

Their presence confirms the GPU build is installed; their absence is normal and expected for the CPU-only build.

3. **Install the Hugging Face CLI** (used to fetch and cache models):
   ```sh
   pip install --upgrade huggingface_hub
   ```
4. **Start the server.** This downloads the model on first run (cached under `~/.cache/huggingface`) and serves it on `http://127.0.0.1:8080`:
   ```sh
   llama-server -hf unsloth/Qwen3.5-9B-GGUF:Q5_K_M -c 4096 -ngl 99 --host 127.0.0.1 --port 8080
   ```
   `-ngl 99` offloads layers to a GPU; it's silently ignored on a CPU-only build, so it's safe to always include. For more CPU throughput, add `--threads 8 --threads-batch 8 --flash-attn on`.
5. **Sanity-check it directly** (optional): run `hf cache ls` to find the cached `.gguf` path, then:
   ```sh
   llama-cli -m <path-from-hf-cache-ls> -p "hello" -ngl 99
   ```

Point `.env` at it with `LOCAL_OPENAI_BASE_URL=http://localhost:8080/v1` (see [Configuration](#configuration)).

#### Option B: Cloud inference (Azure OpenAI)

1. In Azure AI Foundry, deploy a chat model (e.g. `gpt-5-nano`) using a standard deployment.
2. Copy the deployment's endpoint and API key into `.env` (see [Configuration](#configuration)).

### Prefer not to install any of this?

Everything above — Python, `uv`, llama.cpp, the embedding model, the GGUF — is also
available prebuilt as a container image, so a machine with Docker needs none of it. See
[infra/docker/README.md](infra/docker/README.md).

## Configuration

Create a `.env` file in the project root:

```env
CHATBOT_MODEL_PROVIDER=azure

AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<your-api-key>
AZURE_OPENAI_CHAT_DEPLOYMENT=<your-chat-deployment-name>
AZURE_OPENAI_API_VERSION=2024-12-01-preview
```

**API version (`AZURE_OPENAI_API_VERSION`) — where that value comes from**

This is the one field you can't look up from your own resource, and the one most likely to send you to the wrong documentation. It is **not** the model version.

| | What it is | How to find it |
|---|---|---|
| **API version** (`2024-12-01-preview`) | Which revision of the Azure OpenAI REST contract you're speaking. A property of the *API*, not of anything you deployed. | Microsoft's docs, or copied from a Foundry code sample (below). No `az` command returns it. |
| **Model version** (`2025-08-07`) | Which snapshot of `gpt-5-nano` is deployed. Used by `infra/azure/main.bicepparam`, not by `.env`. | `az cognitiveservices account deployment show --name <account> --resource-group <rg> --deployment-name <deployment> --query "properties.model" -o jsonc` |

Two practical ways to get a correct API version:

1. **Copy it from Azure AI Foundry.** Open your deployment in the Foundry portal and look at the sample code it generates — the `api_version` is filled in with a working value. This is the fastest route and needs no doc-hunting.
2. **Pick one from the changelog.** [Azure OpenAI API version lifecycle](https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle) (Microsoft Learn) lists every dated version and what each one added.

**Don't look for this on `developers.openai.com`.** OpenAI's own API reference documents *OpenAI's* service, which has entirely separate versioning. Azure OpenAI is a distinct REST surface maintained by Microsoft, so no Azure `api-version` string will ever appear in OpenAI's docs regardless of which model you deployed.

**Why it's pinned rather than defaulted.** The API version gates *features*, not just wire format — structured outputs, which this project relies on for `ContractResponse`/`ToolStrategy`, arrived in `2024-08-01-preview`. Pinning it means a server-side default shift can't silently change which response path works. It's also genuinely required: omitting it fails at client construction with `Must provide either the api_version argument or the OPENAI_API_VERSION environment variable` (raised by the OpenAI SDK, not by this project's code — `model_provider.py::env_required` just catches it earlier with a clearer message).

Microsoft now also offers a **v1 API** that drops `api-version` entirely, but it's a code change rather than a config change: it uses the plain `OpenAI()` client against a `/openai/v1/` base URL instead of `AzureChatOpenAI`. That's why `AZURE_OPENAI_ENDPOINT` here must stay the resource root with **no** `/openai/v1` suffix — see the endpoint-format error in ["What if...?"](#what-if-errors-and-edge-cases-not-tied-to-one-flag).

To use a local OpenAI-compatible model server such as llama.cpp:

```env
CHATBOT_MODEL_PROVIDER=local
LOCAL_OPENAI_BASE_URL=http://localhost:8080/v1
LOCAL_OPENAI_API_KEY=local-not-used
LOCAL_MODEL_NAME=qwen3.5-9b
```

**Command execution (`CHATBOT_EXECUTE_COMMANDS`)**

```env
CHATBOT_EXECUTE_COMMANDS=true
```

The `.env` equivalent of passing `--exe` on every run: a `CMD:` response executes immediately, with no flag and no prompt. It does **not** cover `UNSAFE:` responses — those still require `--yolo` on the command line, which has no `.env` equivalent by design, so the riskiest execution path always stays a deliberate, per-run decision. Any value other than `true` (case-insensitive) leaves execution off; `cli.py::main()` reads it as `os.getenv(...).lower() == "true"`.

**Chunking (`CHATBOT_CHUNK_SIZE` / `CHATBOT_CHUNK_OVERLAP`)**

```env
# CHATBOT_CHUNK_SIZE=1000
# CHATBOT_CHUNK_OVERLAP=200
```

Both are optional — leave them out (or commented, as above) and the shown defaults apply. The units are **characters, not tokens**. `CHATBOT_CHUNK_OVERLAP` is how much text two adjacent chunks share, so a sentence straddling a chunk boundary still appears whole in at least one chunk; it must be smaller than `CHATBOT_CHUNK_SIZE`, and both must be positive whole numbers. Raise the chunk size for long, continuous prose where the answer spans several paragraphs; lower it for short reference/flag docs, where tighter chunks retrieve more precisely and an oversized chunk just drags unrelated flags along with the one you asked about. This is a different knob from `-k`, which is a CLI flag for how many chunks come back per search — see ["Tuning `-k`"](#tuning--k).

The selected provider is built by `ModelProvider` in `model_provider.py`. `rag.py` receives a normal LangChain chat model and does not need to know whether the model is Azure-hosted or local.

To (re)provision the Azure OpenAI resource itself declaratively instead of via the Portal, see [infra/azure/README.md](infra/azure/README.md).

Embeddings are always local, via HuggingFace:

```text
sentence-transformers/all-MiniLM-L6-v2
```

## Run

### Parameters

| Flag | Required | Default | Description |
|---|---|---|---|
| `question` | yes (positional) | — | The question to ask, in plain English. |
| `--documents <path>` | no | `data/documents` | Folder to scan recursively for supported files (`.pdf`, `.md`, `.txt`). Mutually exclusive with `--doc`. |
| `--doc <path>` | no | — | Load exactly one file instead of scanning a folder. Mutually exclusive with `--documents`. |
| `-k <n>` | no | `4` | Number of chunks the retrieval tool returns per search. See "Tuning `-k`" below. |
| `--exe` | no | off | Execute a `CMD:` response. Also required (alongside `--yolo`) to execute an `UNSAFE:` response. Setting `CHATBOT_EXECUTE_COMMANDS=true` in `.env` does the same thing for every run, without the flag — see [Configuration](#configuration). |
| `--yolo` | no | off | Additionally allow executing an `UNSAFE:` response. Has no effect without `--exe`. |
| `--system-prompt <path>` | no | bundled system_prompt.txt | Custom system prompt file to use instead of the bundled default. |
| `--usage` | no | off | Print a per-stage AI-usage telemetry summary (calls, bytes, tokens, retries) after the answer. See "AI-usage telemetry" below. |
| `--usagelog [path]` | no | off | Also write telemetry events to a JSON-lines log file. Requires `--usage`. Bare flag defaults to `<today's date>-usage.log`. |

### Parameter walkthrough

Longer reference for each flag, with an example and the edge cases people actually hit. If you just need the shape of a flag, the table above is enough — this section is for "what happens if..." questions when you don't remember the exact behavior.

#### `question` (positional, required)

The natural-language question to ask, regardless of provider. Always quote it — especially on Windows, where `&`, `|`, and unescaped quotes inside the question can confuse `cmd.exe` before the CLI even sees them.

```sh
uv run qna-chatbot "What is flogger and what logging features does it support?"
```

**What if...**
- **...I forget to quote a multi-word question?** Only the first word becomes `question`; the rest are parsed as unrecognized arguments and argparse errors out before anything runs.
- **...I run the CLI with no question at all?** Immediate argparse error: `the following arguments are required: question`. Nothing is scanned, embedded, or sent anywhere — this fails before any cost is incurred.
- **...the question is an empty string (`""`)?** Argparse accepts it (a string is a string), but the model has nothing real to reason about — expect a low-quality `GENERAL:` answer, not an error.

#### `--documents <path>` / `--doc <path>`

Choose the knowledge base for this run: `--documents` scans a folder recursively for `.pdf`/`.md`/`.txt` files; `--doc` loads exactly one file. They're mutually exclusive (enforced by `argparse`, not application code). Omitting both falls back to the bundled `data/documents` folder.

```sh
uv run qna-chatbot "What does this document say?" --documents path\to\knowledge-base
uv run qna-chatbot "What does this file explain?" --doc path\to\README.md
```

**What if...**
- **...I pass both?** Whichever one you write second on the command line is rejected, referencing the one already set — e.g. `--doc foo.md --documents bar/` fails with `argument --documents: not allowed with argument --doc`. Nothing runs.
- **...the path doesn't exist?** `rag.py::scan_document_paths` raises `FileNotFoundError: Document path not found: <resolved path>` before the embedding model even loads — fails fast, no wasted local work and no network call.
- **...the folder exists but has nothing supported in it** (empty, or only e.g. `.docx`/`.json`)**?** `FileNotFoundError: No supported documents found in <path> (.md, .pdf, .txt)` — same fail-fast behavior, extensions spelled out so you know what's missing.
- **...I pass a relative path?** It's resolved against the current working directory you ran the command from (`Path.expanduser().resolve()`), not the repo root — either `cd` to where the path makes sense first, or use an absolute path.

#### `-k <n>`

How many chunks the retrieval tool returns *per search* — default `4`. See ["Tuning `-k`"](#tuning--k) just below for the full rationale on choosing a value.

**What if...**
- **...I set `-k 0`?** The retrieval tool still runs but has nothing to return, so it comes back with `No relevant context found in the knowledge base.` — expect the model to treat the question as ungrounded (`GENERAL:`) even if the knowledge base actually covers it.
- **...I set `-k` higher than the total number of chunks that exist?** No error — the vector store just returns everything it has, the same as any similarity search bounded by available results.
- **...I pass a non-integer, e.g. `-k abc`?** Immediate argparse error: `argument -k: invalid int value: 'abc'`.

#### `--exe` / `--yolo`

Execution is opt-in and layered: `--exe` alone executes a `CMD:` response; an `UNSAFE:` response additionally requires `--yolo`. `--yolo` by itself, without `--exe`, does nothing at all. Setting `CHATBOT_EXECUTE_COMMANDS=true` in `.env` (see [Configuration](#configuration)) is the always-on equivalent of passing `--exe` on every run; there's no `.env` equivalent of `--yolo`, so `UNSAFE:` execution always has to be asked for on the command line.

```sh
uv run qna-chatbot "shutdown windows with a comment that the machine was software updated" --exe
uv run qna-chatbot "shutdown windows with a comment that the machine was software updated" --exe --yolo
```

**What if...**
- **...the response is `ANS:` or `GENERAL:`?** Nothing executes, regardless of `--exe`/`--yolo` — these two kinds can never carry a command in the first place (`ContractResponse`'s validator, `response_contract.py`, enforces this at the schema level).
- **...the response is `CMD:` but I didn't pass `--exe`?** The command is printed under a `Command:` label but never run — execution logic isn't invoked at all when `--exe` is absent.
- **...the response is `UNSAFE:` and I pass `--exe` but not `--yolo`?** The safety reason and proposed command are printed, but blocked: `Unsafe command blocked. Re-run with --exe --yolo to execute it.`
- **...I pass `--yolo` without `--exe`?** No effect, no warning — `--yolo` only changes anything when `--exe` is also present.
- **...the model returns `CMD:` with no actual command text?** Caught explicitly: `The model returned CMD but no command text. Nothing was run.`
- **...the model returns `UNSAFE:` with no actual command text?** The safety reason is printed with no `Proposed command:` block after it, and `apply_exe_request()` then reports `The model marked this unsafe but did not provide a command. Nothing was run.` (`MSG_UNSAFE_NO_COMMAND`). This can only happen on the text-parsing fallback path: on the schema-enforced path, `ContractResponse`'s validator (`response_contract.py`) already rejects an `UNSAFE` with a null command.
- **...I'm on Windows and the model composes a command with single quotes** (e.g. `rg -w 'flogger' data/`)**?** `cli.py::main()` rewrites single-quoted segments to double quotes before executing, since `cmd.exe` — unlike a POSIX shell — doesn't strip single quotes as argument delimiters. The printed command and the executed command are always identical either way.

#### `--system-prompt <path>`

Swap the bundled `system_prompt.txt` for your own instructions file — useful for experimenting with the classification/grounding rules without editing the package.

```sh
uv run qna-chatbot "What is flogger and what logging features does it support?" --system-prompt path\to\custom_prompt.txt
```

**What if...**
- **...the file doesn't exist?** A plain, unhandled `FileNotFoundError: [Errno 2] No such file or directory: '<path>'` from `Path.read_text()` — there's no custom error message here yet, so you'll see a Python traceback rather than a friendly one-liner.
- **...my custom prompt doesn't mention the ANS/GENERAL/CMD/UNSAFE contract at all?** You'll still get a validly-labeled response either way — the schema-enforced structured-output path (`ContractResponse`) forces a valid `kind` regardless of what the prompt says — but classification *quality* will likely suffer, since the model has lost its guidance on how to classify correctly.

#### Tuning `-k`

`-k` controls how many document chunks the retrieval tool (`retrieve_document_context`) pulls back from the vector store *each time* the model decides to search — it's not how many times the model searches, and not how much of a document exists in total. Every document is split into ~1000-character chunks with 200 characters of overlap before indexing — those are just the defaults, and both are configurable per-machine via `CHATBOT_CHUNK_SIZE`/`CHATBOT_CHUNK_OVERLAP` in `.env` (see [Configuration](#configuration)). `-k` itself has no `.env` equivalent; it stays a CLI flag, and it's "how many of those chunks come back per lookup."

You don't need to touch it for normal use — the default of `4` is enough for most single-document or small-knowledge-base questions. Reach for a different value when:

- **Increase it** (`-k 8`, `-k 12`, ...) if the answer seems to be missing something you know is in the docs. The default may simply not be pulling back the specific chunk that has it, especially once `data/documents` has many files instead of one.
- **Decrease it** (`-k 2`) for a small, single-file question, where a higher `k` just adds noise and cost without adding anything useful.

There's no universal "right" number, but as a rule of thumb: `1` is a practical floor, `3`–`10` covers most normal cases, and `10`–`25` starts to be "deliberately over-fetching for a large document" territory. Pushing it far beyond that tends to flood the model's context with marginally-relevant chunks — raising cost and latency, and often making the answer *worse*, not better. At that point the fix is better chunking or filtering, not a bigger `-k`. See `ARCHITECTURE.md`'s "Chunking and top `-k`" section for the fuller rationale.

Ask against all supported files in `data/documents`:

```sh
uv run qna-chatbot "What is flogger and what logging features does it support?"
```

Use a different document folder or file:

```sh
uv run qna-chatbot "What does this document say?" --documents path\to\knowledge-base
```

Load one documentation file:

```sh
uv run qna-chatbot "What does this file explain?" --doc path\to\README.md
```

Ask something the knowledge base doesn't cover — the model falls back to a `GENERAL:` answer instead of forcing a bad citation:

```sh
uv run qna-chatbot "Who wrote the novel Moby Dick?"
```

Retrieve more or fewer chunks per tool call (default is 4):

```sh
uv run qna-chatbot "What is flogger and what logging features does it support?" -k 8
```

Use a custom system prompt file instead of the bundled default:

```sh
uv run qna-chatbot "What is flogger and what logging features does it support?" --system-prompt path\to\custom_prompt.txt
```

Execute a command response — grounded in `data/documents/win-shutdown.md`, this is the kind of internal-tool-command generation the safety contract exists for:

```sh
uv run qna-chatbot "shutdown windows with a comment that the machine was software updated" --exe
```

A shutdown is system-changing, so expect the model to label it `UNSAFE:` rather than `CMD:` — execute it only when you explicitly accept the risk:

```sh
uv run qna-chatbot "shutdown windows with a comment that the machine was software updated" --exe --yolo
```

Print a per-stage AI-usage summary after the answer:

```sh
uv run qna-chatbot "What is flogger and what logging features does it support?" --usage
```

Also write one JSON line per telemetry event to a log file (defaults to `<today's date>-usage.log`) for cross-run comparison:

```sh
uv run qna-chatbot "What is flogger and what logging features does it support?" --usage --usagelog
```

### AI-usage telemetry (`--usage` / `--usagelog`)

Both flags are opt-in and additive: omitting `--usage` leaves every code path byte-for-byte identical to before this feature existed (`model_provider.py::_telemetry_http_client` returns `None` and `RagAssistant` never attaches a callback handler). `--usagelog` requires `--usage` — passing it alone is a parser error.

With `--usage`, the CLI prints a table with one row per pipeline stage — `ingestion`, `embedding`, `model_call`, `retrieval` — showing call count, bytes, an estimated input-token count, actual input/output/total tokens, summed latency, and retry count. Bytes and actual token counts are `0`/`n/a` for every stage except `model_call`: `ingestion`/`embedding` are pure local file I/O and model loading, and `retrieval` is a local vector-store search — none of that crosses the network. Estimated tokens use OpenAI's `cl100k_base` tokenizer (via `tiktoken`) applied uniformly across providers, including the local llama.cpp backend, since no model-specific tokenizer is vendored — treat it as same-order-of-magnitude, not exact, and prefer the actual provider-reported counts (Azure only, via `usage_metadata`) whenever both are shown. `--usagelog` additionally appends one JSON line per recorded event to a log file, for diffing usage across runs.

**On what lands in a usage log.** Each logged event carries a short `preview` field containing only your question or the retrieval query — never system-prompt or retrieved-document text. This is enforced in code rather than merely intended: `preview` is taken from the human turn alone, and a run with an empty question (or any future entry point that invokes the agent without a human turn) produces an empty preview rather than falling back to the full message text. That fallback existed until 2026-08-05; see `TROUBLESHOOT.MD` under "Telemetry preview can fall back to system-prompt text" for the write-up. Full message text still feeds the token estimate and content hash, which never leave the local process as text.

This is a separate, unrelated thing from the `[stage] [locality]` prefix now on every progress print (e.g. `[ingestion] [local] Scanning data\documents...`, `[call model] [cloud] Connecting to azure chat model...`) — those tags are always on, cost nothing to compute, and don't require `--usage`. See [AI-usage telemetry](ARCHITECTURE.md#ai-usage-telemetry-two-instrumentation-layers-one-call-type) in `ARCHITECTURE.md` for the instrumentation mechanism and an important finding about what a "call" actually represents in this pipeline.

### Provider comparison (measured)

Both providers were smoke-tested with the same two questions — a Flogger question (grounded `ANS`) and "Who wrote the novel Moby Dick?" (ungrounded `GENERAL`):

| | Grounded (`ANS`) | Ungrounded (`GENERAL`) | Never executes under `--exe --yolo` | Speed |
|---|---|---|---|---|
| **Local** (llama-server, Qwen3.5-9B) | ✅ correct citation | ✅ correctly flagged + correct answer | ✅ confirmed | ~4.9 tok/s — minutes per answer |
| **Azure** (`gpt-5-nano-deploy`) | ✅ correct citation | ✅ correctly flagged + correct answer | ✅ confirmed | seconds |

Local numbers were measured on a Lenovo ThinkPad T15G: Intel Core i9-10885H @ 2.40GHz, 64GB RAM, NVIDIA GeForce RTX 2080 Super Max-Q (8GB) + Intel UHD Graphics (128MB). `llama-server` was not offloading to the GPU (no CUDA build in use) for this test, so generation ran CPU-only — the ~4.9 tok/s reflects that, not a hardware limit. GPU-accelerated local inference would likely close much of the gap with Azure.

This table covers `ANS`/`GENERAL` only. `CMD`/`UNSAFE` label reliability is a separate, more involved story — Azure needed a prompt-design fix to be reliable, and local remains inconsistent — see `TROUBLESHOOT.MD` for the full incident history and current state.

The CLI uses Python's standard `argparse` module and plain console output to keep the learning path simple.

### What if...? (errors and edge cases not tied to one flag)

Scenarios that come from configuration or runtime state rather than any single CLI flag — the things people usually hit once, forget the fix for, and have to relearn.

- **...a required `.env` value is missing** (e.g. `AZURE_OPENAI_API_KEY` unset while `CHATBOT_MODEL_PROVIDER=azure`)**?** `model_provider.py::env_required` raises `RuntimeError: Missing required environment variable: <NAME>` before any network call is attempted.
- **...`CHATBOT_MODEL_PROVIDER` is set to something other than `azure`/`local`?** `RuntimeError: Unsupported CHATBOT_MODEL_PROVIDER value: <value>. Use one of: azure, local.`
- **...`AZURE_OPENAI_ENDPOINT` still has `/openai/v1` on the end** (a common copy-paste from the Azure Portal)**?** Caught specifically: a `RuntimeError` explaining the endpoint should be the resource root (`https://<resource>.openai.azure.com/`), not the `/openai/v1` path — see [Configuration](#configuration).
- **...the question isn't covered by anything in the knowledge base?** The model is expected to self-report `GENERAL:` — an ungrounded, general-knowledge answer, printed with a `(not grounded in the knowledge base)` disclaimer — rather than fabricate a citation. If you get a confidently-cited `ANS:` for something you know isn't in `data/documents`, that's the failure mode to report, not the expected one.
- **...the agent gets stuck searching the knowledge base and never produces an answer?** `RagAssistant` caps the tool-calling loop at 10 LangGraph steps (`DEFAULT_MAX_AGENT_STEPS`, `rag.py`) — if that's hit, you get a `GENERAL:`-style response explaining the agent didn't converge, instead of the CLI hanging. This isn't a hypothetical: see `TROUBLESHOOT.MD`'s "Runaway agent loop..." entry for a real, measured case that ran ~21 minutes and 5.36M billed tokens on a single question before this cap existed.
- **...I set `CHATBOT_EXECUTE_COMMANDS=true` and forget about it?** Every run behaves as if `--exe` were passed, so any `CMD:` response executes immediately with no prompt. `--exe` on the command line is additive, not an override — there's no flag to turn execution back off for a single run, so unset the variable if you want the safe default back.
- **...I set `CHATBOT_CHUNK_SIZE=abc` or a negative number?** `rag.py::etoi` raises `RuntimeError: CHATBOT_CHUNK_SIZE must be a positive whole number, got: abc` (same for `CHATBOT_CHUNK_OVERLAP`) during the ingestion stage, before the embedding model loads — a typo fails loudly instead of silently reverting to the default. Setting an overlap that isn't smaller than the chunk size fails the same way, with a message naming both variables.
- **...`--usagelog` is passed without `--usage`?** Rejected immediately: `qna-chatbot: error: --usagelog requires --usage.` Nothing runs.
- **...I run the exact same question twice in a row?** Full re-scan, re-embedding, and a fresh model call happen both times — there's no cross-run cache (see `ARCHITECTURE.md`'s "Why in-memory, not persistent, vector store"). Expect similar latency both times, and — since the model's output isn't guaranteed deterministic — possibly different `--usage` numbers between the two runs, not identical ones.
- **...I Ctrl+C mid-run while using `--usage`/`--usagelog`?** Nothing gets printed or logged for that run — `TelemetrySession` only persists data at the very end of a run that's allowed to finish; a killed process loses whatever was recorded so far. Any cost already incurred against your provider up to that point still happened, it's just not visible in the output.
- **...I want to see every flag and its one-line description without leaving the terminal?** `uv run qna-chatbot --help`.

## Build

```sh
uv build .
```

The package artifact will be written to `dist`.

## Verification

No automated test suite exists yet; verification is smoke-test style (see `TROUBLESHOOT.MD`):

```sh
python -m compileall src
uv lock
uv run qna-chatbot --help
```

## References
- https://docs.langchain.com/oss/python/integrations/chat/azure_chat_openai
- https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
- https://github.com/henrytanner52/all-MiniLM-L6-v2

## Credit

This project's original inspiration and a quick leg-up came from:
- https://github.com/AMit090912/PDF-Question-Bot---RAG
- Coding and documentation assistance from ChatGPT (OpenAI), Claude Code (Anthropic), and Co-Pilot (Microsoft)
