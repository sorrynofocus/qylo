# Docker: containerized install for QnA-Chatbot

This directory packages the application itself. It is the counterpart to
[`../azure/`](../azure/README.md), which provisions the *cloud model* — see
[`../README.md`](../README.md) for how the two relate.

## Why this exists

The `## Setup` section of the [root README](../../README.md) describes a working install:
create a `uv` venv, download a llama.cpp release, extract it, put it on `PATH`, install the
HuggingFace CLI, start a server, fill in `.env`. It works. It is also a sequence of manual
steps that were performed once, on one Windows machine, and partially written down after
the fact.

That is fine until you need to do it again — on a fresh VM, or on a CI runner that has
none of it. This directory is those steps made executable. Everything the host install
puts on a machine, the image builds in.

The design goal is blunt: **the built image performs zero network downloads at run time,
for either model provider.** If a container needs the internet to answer a question that
isn't going to Azure, something here is broken.

## Prerequisites

Docker. That is the entire list.

No Python, no `uv`, no llama.cpp, no `PATH` edits, no HuggingFace CLI on the host.

**Give Docker enough memory.** Docker Desktop in particular exposes every host CPU while
defaulting to a small memory ceiling, and both limits matter here:

| Task | Needs |
| --- | --- |
| Building the image | ~4GB (or lower `--build-arg BUILD_JOBS`) |
| Running the CLI against Azure | ~2GB |
| Running the local provider (`serve`) | **~8GB** — the Q5_K_M GGUF must fit in RAM |

Building with too little memory fails as `error reading from server: EOF`, or hangs
indefinitely during the model download — neither mentions memory. See
[Troubleshooting](#troubleshooting).

**On Windows, where you change it depends on the backend:**

- **Hyper-V backend** — Docker Desktop → Settings → Resources → Memory. There is a slider.
- **WSL 2 backend** (the default) — *there is no slider*. Docker inherits whatever WSL 2
  allows, set in `%UserProfile%\.wslconfig`:

  ```ini
  [wsl2]
  memory=16GB
  ```

  **Restarting Docker Desktop does not apply this.** The WSL 2 utility VM survives Docker
  restarts and only reads `.wslconfig` when it boots, so the old ceiling silently persists.
  You must shut the VM down:

  ```powershell
  wsl --shutdown          # stops ALL WSL distros, not just docker-desktop
  ```

  then start Docker Desktop again and confirm with:

  ```powershell
  docker info --format "{{.MemTotal}}"
  ```

  `wsl --terminate docker-desktop` is *not* sufficient — the memory ceiling belongs to the
  shared utility VM, which stays alive as long as any distro is running. Note that Docker
  Desktop's WSL integration keeps integrated distros running, which is often why one appears
  `Running` that you never started yourself.

## What is inside the image

| Component | Size | Why it is baked in |
| --- | --- | --- |
| llama.cpp (`llama-server`, `llama-cli`) | ~20MB | Built from a pinned source ref, CPU-only |
| `sentence-transformers/all-MiniLM-L6-v2` | ~88MB | Embeddings are **always** local — needed even in Azure mode |
| `cl100k_base` tiktoken BPE table | ~1.7MB | `--usage` must not turn an offline run into a hard failure |
| Python 3.12 + all `uv.lock` dependencies | ~1.4GB | CPU-only torch; the CUDA stack is pinned out |
| Qwen3.5-9B Q5_K_M GGUF | ~6.5GB | Optional — see the build arg below |

Two build variants:

| Build | Size | Works offline | Use for |
| --- | --- | --- | --- |
| default (`BAKE_LLM_WEIGHTS=1`) | ~9.5GB | Both providers | VM installs, air-gapped hosts, the normal case |
| `--build-arg BAKE_LLM_WEIGHTS=0` | ~3GB (measured 3.05GB) | Azure only | Disk-constrained CI; escape hatch, not the default |

CPU-only torch accounts for ~1.4GB of that baseline on its own, before transformers, scipy
and scikit-learn. The CUDA pin is still doing its job — without it this would be several GB
larger again.

## How it works

The build is six stages. Each does one job and produces one artifact, so changing your
source code does not re-download a 6.5GB model, and changing the llama.cpp ref does not
re-resolve the Python tree.

| Stage | Produces | Notes |
| --- | --- | --- |
| `base` | Shared `ENV` paths | Cache locations declared once so no stage can drift |
| `llamacpp-builder` | `llama-server`, `llama-cli`, `*.so` | Compiles from a pinned tag; toolchain discarded here |
| `python-deps` | `/app/.venv` | `uv sync --frozen` against the committed lock |
| `cache-warm` | Embedding model + BPE table | Warmed through the app's own code paths |
| `weights-0` / `weights-1` → `weights` | `/opt/models/qwen` | Stage-level switch on `BAKE_LLM_WEIGHTS` |
| `runtime` | The final image | Assembly only — no compiler, `git`, `cmake`, or `uv` |

Two details in there are load-bearing rather than stylistic:

**`-DGGML_NATIVE=OFF`.** llama.cpp defaults to `-march=native`, which bakes the *build
machine's* CPU instruction set into the binary. Build on a CI runner with AVX-512 and the
binary dies with `SIGILL` on a VM exposing a narrower CPU. Off costs a little throughput
and buys an image that runs anywhere.

**The `weights-0`/`weights-1` split is a stage switch, not a `RUN if`.** BuildKit never
executes a stage nothing references, so `BAKE_LLM_WEIGHTS=0` doesn't merely skip the
download — the 6.5GB layer never enters the build graph or the cache at all. A `RUN if`
cannot do that, and on a disk-constrained runner it is the difference between fitting
and not.

### The build context is the repository root

The image needs `src/`, `pyproject.toml`, `uv.lock`, `README.md` and `data/`, none of which
live in this directory. So always build from the repo root with `-f`:

```sh
docker build -f infra/docker/Dockerfile -t qna-chatbot .
```

`cd infra/docker && docker build .` will fail, and the error will not obviously point here.
For the same reason `.dockerignore` lives at the **repo root**, not next to the Dockerfile:
Docker reads it from the context root.

## Usage

All commands run from the repository root.

### Build

```sh
# Default: fully self-contained, ~8GB
docker build -f infra/docker/Dockerfile -t qna-chatbot .

# Slim: Azure-only, ~1.5GB
docker build -f infra/docker/Dockerfile --build-arg BAKE_LLM_WEIGHTS=0 -t qna-chatbot:slim .

# Different llama.cpp release
docker build -f infra/docker/Dockerfile --build-arg LLAMACPP_REF=b10298 -t qna-chatbot .
```

### Ask a question (Azure provider)

`.env` is never baked into the image — it holds a live API key. Pass it at run time:

```sh
docker run --rm --env-file .env qna-chatbot "What is flogger?"
```

### Use your own documents

The image ships `data/documents` as a default corpus. Mount over it to use another:

```sh
docker run --rm --env-file .env \
  -v "$PWD/my-docs:/app/data/documents:ro" \
  qna-chatbot "What does this document say?"
```

Every `qna-chatbot` flag works unchanged — anything the entrypoint doesn't recognize is
passed straight through to the CLI.

### Batch mode

One question per line; blank lines and `#` comments are skipped:

```sh
printf 'What is flogger?\nWhat does TagEXE do?\n' > questions.txt
docker run --rm --env-file .env -v "$PWD/questions.txt:/q.txt" qna-chatbot batch /q.txt
```

Exits non-zero if any question failed, having attempted all of them.

> **This loops the process, not the work.** `rag.py` builds an `InMemoryVectorStore` that is
> discarded at exit, so every question re-scans, re-chunks and re-embeds the whole corpus.
> Fine for a handful of questions, genuinely wasteful for hundreds. Real batching needs the
> vector store to persist across questions — a code change, not an entrypoint change.

### Local provider (llama.cpp in Docker)

```sh
docker compose -f infra/docker/docker-compose.yml --profile local up -d llama
docker compose -f infra/docker/docker-compose.yml --profile local run --rm chatbot "What is flogger?"
```

Set `CHATBOT_MODEL_PROVIDER=local` in `.env` first.

Server tuning is exposed as environment variables on the `llama` service, with defaults that
matter:

| Variable | Default | Why |
| --- | --- | --- |
| `LLAMA_CTX` | `16384` | **Not** the 4096 from the root README's host example. This is an agentic loop — each retrieval tool call appends more chunks to the conversation. At 4096 the second model call is silently truncated and the answer degenerates into repetition, with no error raised |
| `LLAMA_PARALLEL` | `1` | llama-server divides its context pool across slots and defaults to 4; the CLI is one-shot, so extra slots just quarter the usable window |
| `LLAMA_NGL` | `99` | GPU layer offload; silently ignored on the CPU-only build, safe to always pass |

Two things compose handles that a bare `docker run` will not:

- **`LOCAL_OPENAI_BASE_URL`.** `.env` sets `http://localhost:8080/v1`, which *inside a
  container* means the container itself. Compose overrides it to `http://llama:8080/v1`.
  If you instead run llama-server on the host, set
  `LOCAL_OPENAI_BASE_URL=http://host.docker.internal:8080/v1` and uncomment the
  `extra_hosts` block in `docker-compose.yml`.
- **Relative paths.** Compose resolves them against *this file's* directory, not your shell's
  working directory, which is why the volume paths read `../../`. Always invoke with
  `-f infra/docker/docker-compose.yml` from the repo root.

## Workflow

Three lanes this is built to serve:

**Local development.** Keep using the host `uv` venv from the root README — it is faster to
iterate against. Use the container to check that a change works on a clean machine before
you claim it does.

**CI/CD.** `.github/workflows/docker.yml` builds the image and runs smoke checks. No secrets
enter the image: `.env` is in `.dockerignore`, and configuration is passed at run time.
See the timing notes in that file — the GitHub Actions cache export, not disk, is what
dominates the ~33 minute build. The workflow is manual (`workflow_dispatch`) for that reason.

**Air-gapped install.** Build the default image (weights baked), `docker save` it, move the
tarball to the target machine, `docker load`. Nothing on that machine needs internet access,
Python, or llama.cpp.

```sh
docker build -f infra/docker/Dockerfile -t qna-chatbot .
docker save qna-chatbot | gzip > qna-chatbot.tar.gz
# ...transfer...
gunzip -c qna-chatbot.tar.gz | docker load
```

Verify the claim rather than trusting it — `--network none` is the real test:

```sh
docker run --rm --network none qna-chatbot "What is flogger?"
```

With `CHATBOT_MODEL_PROVIDER=local` this must produce an answer. With `azure` it must reach
the model-call stage and fail *only* on the Azure connection — never on a HuggingFace or
tiktoken download. A download failure there means a cache did not bake correctly.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `SIGILL` / "Illegal instruction" from `llama-server` | Binary built with a wider CPU instruction set than the host has | Confirm `-DGGML_NATIVE=OFF` in the Dockerfile; rebuild on/for the target |
| Long stall on startup with no error, offline host | `HF_HUB_OFFLINE` not set, so `huggingface_hub` is waiting on a revision check | It is set last in the `runtime` stage — verify it survived your edit |
| `llama-server -hf` fails to download | `LLAMA_CURL` was off at build time | `libcurl4-openssl-dev` must be present in `llamacpp-builder`, `libcurl4` in `runtime` |
| Build fails on a missing `pyproject.toml` / `src` | Built from this directory instead of the repo root | `docker build -f infra/docker/Dockerfile .` from the root |
| `exec /usr/local/bin/entrypoint.sh: no such file or directory` | `entrypoint.sh` checked out with CRLF line endings | `.gitattributes` forces LF; re-clone or `git add --renormalize .` |
| `error reading from server: EOF` partway through the llama.cpp compile | Build VM OOM-killed — too many parallel compiles for the allocated memory | Raise Docker memory, or lower `--build-arg BUILD_JOBS` (default 4) |
| Model download hangs for hours with no output, daemon stops responding | Same memory shortage, but during the 6.5GB pull it wedges instead of dying | Raise Docker memory; see the WSL 2 note below |
| `docker info` reports far less memory than you configured | **Docker Desktop on WSL 2**: restarting Docker Desktop does *not* re-read `.wslconfig` | `wsl --shutdown`, then restart Docker Desktop — see below |
| `ModuleNotFoundError: No module named 'qna_chatbot'` | The venv was built with an editable install, whose `.pth` points at a source tree the runtime stage does not copy | `uv sync` must use `--no-editable`; already set in the `python-deps` stage |
| `failed to parse stage name "weights-"` | `BAKE_LLM_WEIGHTS` declared after a `FROM`, so it is stage-scoped and invisible to `FROM` | The `ARG` must stay above the first `FROM` |
| `ENOSPC` during a CI build | Free-runner disk exhausted by the 6.5GB model | See the diagnostic ladder in `.github/workflows/docker.yml` |
| Permission denied writing `--usagelog` | Bind-mount source created root-owned by Docker | `logs/` is committed with a `.gitkeep` so it exists with your ownership |
| Local answers are repetitive, rambling, or repeat a "final answer" several times | Context window exhausted mid-agent-loop; llama-server truncated the conversation **without erroring** | Check `truncated =` in `docker logs <llama container>`. Raise `LLAMA_CTX` (default 16384). Do **not** assume the model is at fault |

## Notes

- The image runs as non-root (`appuser`, uid 1000).
- `CHATBOT_EXECUTE_COMMANDS` is deliberately **not** set. `cli.py::run_command` is a
  `subprocess.run(..., shell=True)` with no allowlist and no audit log, so command execution
  stays opt-in per run via `--exe` rather than baked into the image. A container is a
  reasonable blast-radius limit for that feature, but it is not a sandbox.
- `--exe` behaves slightly differently here than on Windows: `cli.py` rewrites POSIX single
  quotes to double quotes only when `os.name == "nt"`, so that rewrite is skipped in Linux
  containers. That is correct — `sh` handles single quotes natively — but it means the two
  platforms take different code paths.
