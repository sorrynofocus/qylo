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

*Decided 2026-08-30, during the readability refactor. **The removal itself has not happened yet** —
this records the decision that governs it.* Phase B deletes telemetry entirely, and `telemetry.py`
is the only thing in `src/` that imports `tiktoken`. When it goes, the tokenizer cache baked into
the image **stays**: the cache-warm at `infra/docker/Dockerfile:188-191`, its `COPY` at `:266`, the
offline assertion at `.github/workflows/docker.yml:162-169`, and the row in
`infra/docker/README.md:78` are all retained. Only the direct `tiktoken` declaration in
`pyproject.toml` goes — the package will still install, because `langchain-openai` requires it.

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

- **`TROUBLESHOOT.MD` owes two dated entries.** (1) The naming decision, including the rejected
  candidates and why — `incant`, `qrun`, `askr`, `ragu`, `farad`, `sygil`, `orac`, `wardn`, `quta`,
  `mango`, `manqo` — so nobody repeats the collision search. (2) The first CI run's findings: what
  it did and did not prove, the cache cost, and the `/app/src` false green. Append only; never edit
  in place.
- **Mermaid line breaks.** `ARCHITECTURE.md` lines ~174-199 use `\n` in 14 flowchart node labels;
  the documented Mermaid form is `<br/>` and support is renderer-dependent. Check the rendered page
  on GitHub first — if labels show a literal `\n`, it is a mechanical find-replace. The sequence
  diagram below the flowchart was rewritten and contains none.
- **`docs/SETUP.md`** opens `# Setup and configuration` immediately followed by `## Setup`. Mildly
  redundant, but `## Configuration` as a sibling is what eight anchors depend on, so collapsing it
  is not free.

---

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
`rag.py::answer()` gates the `Safety: unsafe` override on `kind is ResponseKind.COMMAND`, so a
doc that *did* declare `unsafe` is ignored whenever the model mislabels the request as
`ANS`/`GENERAL`.

- **Command requests misclassify as `ANS`/`GENERAL` (2026-08-09).** Only 6 of 15 command
  requests were labelled `CMD`/`UNSAFE` on Azure. Both wrong labels bypass the deterministic
  `Safety: unsafe` override in `rag.py::answer()`. Prompt-level fixes have failed four times,
  and added prompt text measurably costs convergence. Deferred — see the decision above.
- **Local path-attribution gap.** The 20-call sample's 2 misses were never attributed to the
  structured-output path versus the text-parsing fallback, so it is unknown which fix applies —
  schema tuning or tool-calling reliability. See `TROUBLESHOOT.MD`, "Two open gaps, explained".
- **Ungrounded-destructive-command gap.** A command request with no matching doc has no `Safety:`
  tag to check, so model judgment alone decides `CMD` vs `UNSAFE`. Deferred — see the decision
  above; `--exe` / `--yolo` is the intended boundary here.
