# Backlog

Open work that is not yet started. Ordered roughly by impact within each section.

This file exists because the agenda used to live in three places at once — `CLAUDE.md`'s TODO,
an uncommitted scratch file outside the repo, and nowhere at all. Anything worth remembering
between sessions belongs here.

**Related files, and what goes where:**

- `CLAUDE.md` / `AGENTS.md` `## TODO` -  kept short, and only for caveats that change how you
  should *work in the code right now* (example: "Azure does not converge, so don't trust an Azure
  result as a baseline"). Chores and projects go here in `BACKLOG.md` instead.
- `TROUBLESHOOT.MD` — append-only, dated. Records failures that already happened and how they
  were diagnosed. This file records work not yet done. It is a LARGE File to process. 
- `ARCHITECTURE.md` — how the system works today, not what should change.

---

## Testing and CI

### CI proves the image builds, not that it works

*Found 2026-08-09.* The workflow's five smoke steps check that the CLI starts, the package
compiles, the llama.cpp binary runs on a generic CPU, the caches resolve with no network, and the
weights are present. **No inference happens anywhere.** Not one question is ever answered, so a
change that breaks retrieval, the agent loop, or the response contract would sail through green.

The valuable, narrow thing it does prove: the build works on a machine that is not the author's,
from a clean checkout, with no warm `uv` cache and no uncommitted file quietly satisfying a
`COPY`. Local builds pass for reasons that do not generalize.

Wanted: an end-to-end step that asks a real question through the local provider, and a second one
through Azure. Notes toward it:

- Assert the **response contract**, not answer text — that stdout opens with
  `ANS:`/`GENERAL:`/`CMD:`/`UNSAFE:`, and that a command question resolves to `CMD`. Answer prose
  is nondeterministic; the contract is the load-bearing guardrail and is exactly what regresses.
- Reuse what exists. `entrypoint.sh`'s `batch` mode already runs a questions file and exits
  non-zero if any question fails while still attempting all of them — written for a CI caller.
  `docker-compose.yml` already wires `chatbot` to `llama` over a shared network.
- **No longer blocked.** The compose healthcheck bug that prevented `--profile local` from ever
  coming up was fixed 2026-08-09 (the probe used `curl`, absent from the runtime image; it is now
  a `python3 -c` one-liner). Both local-in-Docker routes are verified working — see
  `TROUBLESHOOT.MD` (2026-08-09) for the exact commands.
- **The Azure half converges again** (2026-08-09) and can now be a real end-to-end gate. Assert
  the response contract, not answer text; leave `CMD` out until the classification defect is
  fixed, since the command branch is only 6/15 reliable and a `CMD`-asserting step would flake.
- **Runner feasibility — measured 2026-08-09, and the old estimate was pessimistic.** Timed
  locally against the containerized 9B with the serve container pinned to 4 CPUs
  (`--cpuset-cpus 0-3`, verified to bite: `sched_getaffinity` reports 4) to emulate a free
  runner: **427s (7m07s)** for a 2-model-call question, extrapolating to ~10.5 min for a
  3-call one. So ~7-11 min per question, not the 10-25 min previously guessed. Against a
  90-minute timeout with ~33 min already spent on the build, two or three questions fit.
  Model load costs only 2-7s and is not a factor.
  - **4 vCPU is only ~1.5x slower than 16, not 4x** (generation 2.9 vs 4.4 t/s; prompt eval
    11.3 vs 16.8 t/s). The workload is memory-bandwidth bound before it is core-count bound.
  - **Step-count variance dominates CPU count.** The same question took 2 model calls (284s)
    one run and 3 calls (628s) another. Size any CI timeout for the worst case; n=1 per
    configuration here.
  - `LLAMA_CTX` still cannot be lowered — `entrypoint.sh` documents that 4096 truncates
    mid-loop and degenerates. `truncated = 0` held on every request in these runs.
- **Azure needs secrets** (endpoint, key, deployment, api-version) as repo secrets.
  `workflow_dispatch`-only means fork PRs cannot trigger it, so exposure is limited to
  collaborators. `infra/docker/README.md` says "No secrets enter the image", which stays true but
  becomes misleading — secrets would enter the *runner*. That line needs a companion sentence.

### The tiktoken cache outlived telemetry, deliberately

*Decided 2026-08-30, during the readability refactor; carried out in Phase B the same day.*
Phase B deleted telemetry entirely, and `telemetry.py` was the only thing in `src/` that imported
`tiktoken`. The tokenizer cache baked into the image **stayed**: the cache-warm in
`infra/docker/Dockerfile`, its `COPY` into the runtime stage, the offline assertion in
`.github/workflows/docker.yml`, and the row in `infra/docker/README.md` are all still there. Only
the direct `tiktoken` declaration in `pyproject.toml` went — the package still installs, because
`langchain-openai` requires it (confirmed: it is still resolved in `uv.lock`).

**Why it does not come out with the feature that motivated it.** `langchain_openai` imports tiktoken
and exposes token-counting paths, so it is *not established* that an air-gapped answer succeeds
without the cache. Nor can the current workflow establish it: it runs no inference at all (see "CI
proves the image builds, not that it works" above), so a green run would prove only that its
remaining checks passed — not that a question can still be answered offline with the cache gone.

Removing it therefore needs its own change, gated on an end-to-end air-gapped question that
actually reaches the model. Worth doing eventually: it is a build stage and a ~1.7MB layer serving
a dependency nothing in this project calls directly. Not worth doing blind — the air-gap property
is the expensive thing to re-establish, at ~33 min per `workflow_dispatch` run.

### GHA cache is upside-down

`cache-to: type=gha,mode=max` writes ~9.6GB against a **10GB per-repo quota**, so it sits at the
ceiling and evicts rather than hits — the first run recorded zero `CACHED` steps. Measured inside
a 30m43s build step (stages overlap, they do not sum):

| | |
|---|---|
| exporting layers to GitHub Actions cache | **18m52s — 57% of the build** |
| llama.cpp cmake build | 5m36s |
| exporting + importing docker image format | 6m00s |
| downloading the 6.5GB Qwen GGUF | 31s |

It spends ~19 minutes to save at most the ~6 minutes of compile it could replay. Options, cheapest
first: `mode=min`; scope the cache to the `llamacpp-builder` stage only; drop `type=gha` entirely.
Worth one measured run each rather than guessing.

### CI hygiene

- **Node 20 deprecation.** `actions/checkout@v4`, `docker/build-push-action@v6` and
  `docker/setup-buildx-action@v3` are being force-run on Node 24. Cosmetic until GitHub stops
  forcing it. Bump to `checkout@v5` / `build-push-action@v7` / `setup-buildx-action@v4`.
- **Unauthenticated Hugging Face downloads.** Both the cache-warm and the 6.5GB `hf download` log
  `You are sending unauthenticated requests to the HF Hub`. A plausible flake source on repeat
  runs; add `HF_TOKEN` as a repo secret if it ever bites.
- **llama.cpp web UI assets** failed to download during cmake (`dist.tar.gz from b1 failed`).
  Non-fatal, build proceeded. Only matters if anyone expects `llama-server`'s browser UI.

---

## Docs

- **`docs/SETUP.md`** opens `# Setup and configuration` immediately followed by `## Setup`. Mildly
  redundant, but `## Configuration` as a sibling is what eight anchors depend on, so collapsing it
  is not free.

---

## Deployment

### Docker is deferred, not broken

*2026-08-30.* Docker packaging has not been rebuilt or re-verified since Phase B removed
telemetry. **No build has failed.** The user is weighing setting the Docker path aside during the
refactor because it *may* prove troublesome to deploy — anticipated difficulty, not an observed
one. Nobody should write it up as a defect, and deferral does not un-verify the air-gap result
recorded in `docs/TROUBLESHOOT.MD` (2026-08-08) — it just means that result predates Phase B.

Assets are preserved: `infra/docker/`, the `workflow_dispatch` workflow, the tokenizer cache and
its offline CI assertion all stay. Revisit when there is a concrete need for that packaging or
for offline deployment.

### A FastAPI service in front of the existing core

*Proposal, not an approved specification. Nothing here is authorized.* Raised by the user
2026-08-30: a FastAPI backend, possibly with a Next.js frontend on Vercel, after the refactor.

**Phase C came first, and the reason was structural rather than tidiness. It has now landed
(2026-08-31), so this prerequisite is met.** `cli.py::main()` used to own the whole sequence:
scan → load → split → embed → build vector store → build model → construct `RagAssistant` →
answer → gate execution. A server needs the first five to happen *once at startup* and only
`answer()` to happen per request. `cli.py::build_assistant()` is now a **candidate** seam for
that: it returns a ready `RagAssistant`, and `main()` no longer has to be rewritten to get one.

Two things it is not, and both matter before anyone builds against it. It **prints progress** to
stdout at every stage, which a server does not want. And it **assumes its caller has already
initialized configuration**: `main()` calls `load_dotenv()` before ingestion so the
`CHATBOT_CHUNK_*` reads see it, while `build_chat_model()` loads `.env` only later, on its own.
Call `build_assistant()` without that first and chunking silently falls back to defaults. So the
seam exists, but configuration ownership and concurrency are still to design - and nothing about
FastAPI, hosting or a frontend is approved.

**What the code already gives a server, and this is checkable today, not aspiration:**

- `RagAssistant.answer()` returns a `ModelResponse` (`kind` / `content` / `command`), and the
  structured path validates through the Pydantic `ContractResponse`. That is already a JSON
  response shape, and Pydantic is FastAPI's native currency. The HTTP layer is genuinely thin.
- Ingestion is already decoupled from answering at the `vector_store` argument. One built index
  can back one long-lived `RagAssistant`.
- `answer()` keeps no per-call state on `self` — every value in it is a local. So one instance
  can serve many requests. **Unverified under concurrency**, and the underlying chat client and
  compiled graph are the things to check before assuming otherwise.

**What a server changes that the CLI never had to answer:** rebuild-every-run is the CLI's
biggest cost and a listed limitation in `README.md`; at startup it becomes a one-time cost and
stops mattering. In exchange, index *staleness* becomes a real question for the first time. Decide
refresh behaviour explicitly — startup-only, on a signal, or on a timer — rather than inheriting
"always fresh" by accident.

**Execution must be absent from the server, not merely disabled.** `run_command` has no allowlist
and no audit log, and the whole `CMD`/`UNSAFE` safety model assumes a human at a terminal on their
own machine opting in per-run with `--exe`/`--yolo`. Neither assumption survives an HTTP boundary.
The API should return the composed command as *data* and let the client decide. That is a cleaner
story than the CLI's, and it should be a hard constraint on the design, not a default someone can
flip with an env var.

**Vercel hosts the frontend. It cannot host this backend.** Every request embeds the query
locally, so torch and `sentence-transformers` are on the request path; combined with rebuilding
or loading the index, that does not fit a serverless function's cold-start and size envelope. Run
FastAPI under Uvicorn as a persistent service somewhere else. A useful arrangement if Next.js on
Vercel does happen: have its server-side route handlers proxy to FastAPI, which keeps the API key
server-side and sidesteps CORS entirely.

**Resource reality, stated plainly.** Dropping Docker simplifies packaging; it does not reduce
memory. The floor is the local embedding stack — torch alone is the bulk of the ~1.4GB of
installed dependencies. **You cannot avoid it by persisting the index**, because the *query* still
has to be embedded on every request. The only real lever is hosted embeddings, and that is its own
change: it trades provider cost, a network dependency, and sending document content to that
provider, and any embedding-model change needs retrieval quality re-verified. Multiple Uvicorn
workers duplicate the model in memory — prefer one worker with bounded concurrency until measured.

**The cheap next step, whenever this is picked up:** measure RSS after startup with the index
loaded, plus startup time and single-request latency, on the host. It is local, free, needs no
provider and no hosting decision, and it is the number every other question here depends on. No
server size, cost, or host has been chosen, and none should be until that exists.

Reference: [FastAPI: run it manually](https://fastapi.tiangolo.com/deployment/manually/) and
[deployment concepts](https://fastapi.tiangolo.com/deployment/concepts/).

## Model behaviour

Only the path-attribution gap below is repeated in `CLAUDE.md` / `AGENTS.md` `## TODO`, because
it changes how you should interpret a result while working in the code. The two command
classification items are deliberately **not** repeated there — they are closed pending planning,
and restating them alongside live work read as a standing instruction to go fix them.

### Command classification — closed pending future planning

*Decided 2026-08-09.* Two items below want the same fix, and the obvious candidate is ruled
out. Recorded here so it is not proposed a third time.

**Rejected: command-text pattern matching.** A hardcoded table of destructive command patterns
(`rm -rf`, `del /f /s /q`, `shutdown`, …) was prototyped and reverted the same day:

1. **It is never complete.** Every new tool or shell idiom is another entry, indefinitely.
2. **It only parses English.** The model can be asked, and will answer, in any language.
3. **It breaks the measurement.** `tools/score_contract.py` scores the command case against
   `{COMMAND, UNSAFE}`, so a deterministic promotion to `UNSAFE` satisfies that assertion
   regardless of what the model did — the harness would report an improvement while having
   stopped measuring the model at all.
4. Found while prototyping: matching bare verbs false-fired on ordinary documentation prose
   ("on shutdown, the logger flushes its buffer"), degrading the grounded path, which is the
   one branch measuring 100%.

**Why this is not urgent.** Execution is gated by design, not by classification. `CMD` needs
`--exe`; `UNSAFE` needs `--exe --yolo`. `--yolo` exists precisely so the decision to run
something destructive rests with the person typing it, who has accepted the precautions. The
`Safety:` doc-tag path has tested well where a matching doc exists. Some requests will get past
it; **enriching the documents is the more promising lever than more code.**

**Do not reopen with a pattern list.** If revisited, the open question is narrow:
`assistant.py::answer()` gates the `Safety: unsafe` override on `kind is ResponseKind.COMMAND`, so a
doc that *did* declare `unsafe` is ignored whenever the model mislabels the request as
`ANS`/`GENERAL`.

- **Command requests misclassify as `ANS`/`GENERAL` (2026-08-09).** Only 6 of 15 command
  requests were labelled `CMD`/`UNSAFE` on Azure. Both wrong labels bypass the deterministic
  `Safety: unsafe` override in `assistant.py::answer()`. Prompt-level fixes have failed four times,
  and added prompt text measurably costs convergence. Deferred — see the decision above.
- **Local path-attribution gap.** The 20-call sample's 2 misses were never attributed to the
  structured-output path versus the text-parsing fallback, so it is unknown which fix applies —
  schema tuning or tool-calling reliability. See `TROUBLESHOOT.MD`, "Two open gaps, explained".
- **Ungrounded-destructive-command gap.** A command request with no matching doc has no `Safety:`
  tag to check, so model judgment alone decides `CMD` vs `UNSAFE`. Deferred — see the decision
  above; `--exe` / `--yolo` is the intended boundary here.
