# Usage

Flags, the parameter walkthrough, and error cases. 

Back to [README.md](../README.md) from here.

## Run

### Parameters

| Flag | Required | Default | Description |
|---|---|---|---|
| `question` | yes (positional) | — | The question to ask, in plain English. |
| `--documents <path>` | no | `data/documents` | Folder to scan recursively for supported files (`.pdf`, `.md`, `.txt`). Mutually exclusive with `--doc`. |
| `--doc <path>` | no | — | Load exactly one file instead of scanning a folder. Mutually exclusive with `--documents`. |
| `-k <n>` | no | `4` | Number of chunks the retrieval tool returns per search. See "Tuning `-k`" below. |
| `--exe` | no | off | Execute a `CMD:` response. Also required (alongside `--yolo`) to execute an `UNSAFE:` response. Setting `CHATBOT_EXECUTE_COMMANDS=true` in `.env` does the same thing for every run, without the flag — see [Configuration](SETUP.md#configuration). |
| `--yolo` | no | off | Additionally allow executing an `UNSAFE:` response. Has no effect without `--exe`. |
| `--system-prompt <path>` | no | bundled system_prompt.txt | Custom system prompt file to use instead of the bundled default. |

### Parameter walkthrough

Longer reference for each flag, with an example and the edge cases people actually hit. If you just need the shape of a flag, the table above is enough — this section is for "what happens if..." questions when you don't remember the exact behavior.

#### `question` (positional, required)

The natural-language question to ask, regardless of provider. Always quote it — especially on Windows, where `&`, `|`, and unescaped quotes inside the question can confuse `cmd.exe` before the CLI even sees them.

```sh
uv run qylo "What is flogger and what logging features does it support?"
```

**What if...**
- **...I forget to quote a multi-word question?** Only the first word becomes `question`; the rest are parsed as unrecognized arguments and argparse errors out before anything runs.
- **...I run the CLI with no question at all?** Immediate argparse error: `the following arguments are required: question`. Nothing is scanned, embedded, or sent anywhere — this fails before any cost is incurred.
- **...the question is an empty string (`""`)?** Argparse accepts it (a string is a string), but the model has nothing real to reason about — expect a low-quality `GENERAL:` answer, not an error.

#### `--documents <path>` / `--doc <path>`

Choose the knowledge base for this run: `--documents` scans a folder recursively for `.pdf`/`.md`/`.txt` files; `--doc` loads exactly one file. They're mutually exclusive (enforced by `argparse`, not application code). Omitting both falls back to the bundled `data/documents` folder.

```sh
uv run qylo "What does this document say?" --documents path\to\knowledge-base
uv run qylo "What does this file explain?" --doc path\to\README.md
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

Execution is opt-in and layered: `--exe` alone executes a `CMD:` response; an `UNSAFE:` response additionally requires `--yolo`. `--yolo` by itself, without `--exe`, does nothing at all. Setting `CHATBOT_EXECUTE_COMMANDS=true` in `.env` (see [Configuration](SETUP.md#configuration)) is the always-on equivalent of passing `--exe` on every run; there's no `.env` equivalent of `--yolo`, so `UNSAFE:` execution always has to be asked for on the command line.

```sh
uv run qylo "shutdown windows with a comment that the machine was software updated" --exe
uv run qylo "shutdown windows with a comment that the machine was software updated" --exe --yolo
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
uv run qylo "What is flogger and what logging features does it support?" --system-prompt path\to\custom_prompt.txt
```

**What if...**
- **...the file doesn't exist?** A plain, unhandled `FileNotFoundError: [Errno 2] No such file or directory: '<path>'` from `Path.read_text()` — there's no custom error message here yet, so you'll see a Python traceback rather than a friendly one-liner.
- **...my custom prompt doesn't mention the ANS/GENERAL/CMD/UNSAFE contract at all?** You'll still get a validly-labeled response either way — the schema-enforced structured-output path (`ContractResponse`) forces a valid `kind` regardless of what the prompt says — but classification *quality* will likely suffer, since the model has lost its guidance on how to classify correctly.

#### Tuning `-k`

`-k` controls how many document chunks the retrieval tool (`retrieve_document_context`) pulls back from the vector store *each time* the model decides to search — it's not how many times the model searches, and not how much of a document exists in total. Every document is split into ~1000-character chunks with 200 characters of overlap before indexing — those are just the defaults, and both are configurable per-machine via `CHATBOT_CHUNK_SIZE`/`CHATBOT_CHUNK_OVERLAP` in `.env` (see [Configuration](SETUP.md#configuration)). `-k` itself has no `.env` equivalent; it stays a CLI flag, and it's "how many of those chunks come back per lookup."

You don't need to touch it for normal use — the default of `4` is enough for most single-document or small-knowledge-base questions. Reach for a different value when:

- **Increase it** (`-k 8`, `-k 12`, ...) if the answer seems to be missing something you know is in the docs. The default may simply not be pulling back the specific chunk that has it, especially once `data/documents` has many files instead of one.
- **Decrease it** (`-k 2`) for a small, single-file question, where a higher `k` just adds noise and cost without adding anything useful.

There's no universal "right" number, but as a rule of thumb: `1` is a practical floor, `3`–`10` covers most normal cases, and `10`–`25` starts to be "deliberately over-fetching for a large document" territory. Pushing it far beyond that tends to flood the model's context with marginally-relevant chunks — raising cost and latency, and often making the answer *worse*, not better. At that point the fix is better chunking or filtering, not a bigger `-k`. See `ARCHITECTURE.md`'s "Chunking and top `-k`" section for the fuller rationale.

Ask against all supported files in `data/documents`:

```sh
uv run qylo "What is flogger and what logging features does it support?"
```

Use a different document folder or file:

```sh
uv run qylo "What does this document say?" --documents path\to\knowledge-base
```

Load one documentation file:

```sh
uv run qylo "What does this file explain?" --doc path\to\README.md
```

Ask something the knowledge base doesn't cover — the model falls back to a `GENERAL:` answer instead of forcing a bad citation:

```sh
uv run qylo "Who wrote the novel Moby Dick?"
```

Retrieve more or fewer chunks per tool call (default is 4):

```sh
uv run qylo "What is flogger and what logging features does it support?" -k 8
```

Use a custom system prompt file instead of the bundled default:

```sh
uv run qylo "What is flogger and what logging features does it support?" --system-prompt path\to\custom_prompt.txt
```

Execute a command response — grounded in `data/documents/win-shutdown.md`, this is the kind of internal-tool-command generation the safety contract exists for:

```sh
uv run qylo "shutdown windows with a comment that the machine was software updated" --exe
```

A shutdown is system-changing, so expect the model to label it `UNSAFE:` rather than `CMD:` — execute it only when you explicitly accept the risk:

```sh
uv run qylo "shutdown windows with a comment that the machine was software updated" --exe --yolo
```

### Progress tags

Every progress print carries a `[stage] [locality]` prefix (e.g. `[ingestion] [local] Scanning data\documents...`, `[call model] [cloud] Connecting to azure chat model...`). The tags are always on, cost nothing to compute, and need no flag: they say which pipeline stage you are in and whether that stage runs locally or crosses the network to a provider.

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
- **...`AZURE_OPENAI_ENDPOINT` still has `/openai/v1` on the end** (a common copy-paste from the Azure Portal)**?** Caught specifically: a `RuntimeError` explaining the endpoint should be the resource root (`https://<resource>.openai.azure.com/`), not the `/openai/v1` path — see [Configuration](SETUP.md#configuration).
- **...the question isn't covered by anything in the knowledge base?** The model is expected to self-report `GENERAL:` — an ungrounded, general-knowledge answer, printed with a `(not grounded in the knowledge base)` disclaimer — rather than fabricate a citation. If you get a confidently-cited `ANS:` for something you know isn't in `data/documents`, that's the failure mode to report, not the expected one.
- **...the agent gets stuck searching the knowledge base and never produces an answer?** `RagAssistant` caps the tool-calling loop at 10 LangGraph steps (`DEFAULT_MAX_AGENT_STEPS`, `rag.py`) — if that's hit, you get a `GENERAL:`-style response explaining the agent didn't converge, instead of the CLI hanging. This isn't a hypothetical: see `TROUBLESHOOT.MD`'s "Runaway agent loop..." entry for a real, measured case that ran ~21 minutes and 5.36M billed tokens on a single question before this cap existed.
- **...I set `CHATBOT_EXECUTE_COMMANDS=true` and forget about it?** Every run behaves as if `--exe` were passed, so any `CMD:` response executes immediately with no prompt. `--exe` on the command line is additive, not an override — there's no flag to turn execution back off for a single run, so unset the variable if you want the safe default back.
- **...I set `CHATBOT_CHUNK_SIZE=abc` or a negative number?** `rag.py::etoi` raises `RuntimeError: CHATBOT_CHUNK_SIZE must be a positive whole number, got: abc` (same for `CHATBOT_CHUNK_OVERLAP`) during the ingestion stage, before the embedding model loads — a typo fails loudly instead of silently reverting to the default. Setting an overlap that isn't smaller than the chunk size fails the same way, with a message naming both variables.
- **...I run the exact same question twice in a row?** Full re-scan, re-embedding, and a fresh model call happen both times — there's no cross-run cache (see `ARCHITECTURE.md`'s "Why in-memory, not persistent, vector store"). Expect similar latency both times, and — since the model's output isn't guaranteed deterministic — possibly a different answer, not an identical one.
- **...I want to see every flag and its one-line description without leaving the terminal?** `uv run qylo --help`.
