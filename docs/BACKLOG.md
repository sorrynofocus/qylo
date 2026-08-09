# Backlog

Open work that is not yet started. Ordered roughly by impact within each section.

This file exists because the agenda used to live in three places at once — `CLAUDE.md`'s TODO,
an uncommitted scratch file outside the repo, and nowhere at all. Anything worth remembering
between sessions belongs here.

**Related files, and what goes where:**

- `CLAUDE.md` / `AGENTS.md` `## TODO` — kept short, and only for caveats that change how you
  should *work in the code right now* (e.g. "Azure does not converge, so don't trust an Azure
  result as a baseline"). Chores and projects go here in `BACKLOG.md` instead.
- `TROUBLESHOOT.MD` — append-only, dated. Records failures that already happened and how they
  were diagnosed. This file records work not yet done.
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
- **Blocked on the healthcheck bug below**, which prevents `--profile local` from ever coming up.
- **The Azure half fails today** — see "Azure agent no longer converges". Build it as the
  regression harness for that bug, but it cannot be a green gate until the bug is fixed.
- **Runner feasibility is unmeasured.** The baked model is Qwen3.5-9B `Q5_K_M` on a free runner's
  4 vCPU / 16GB, no GPU. Expect low single-digit tokens/sec, and an agentic loop is several round
  trips. One question could take 10-25 minutes on top of the existing 33-minute build, against a
  90-minute timeout. `LLAMA_CTX` cannot be lowered to save memory — `entrypoint.sh` documents that
  4096 truncates mid-loop and degenerates. Time a local run before committing to a CI step.
- **Azure needs secrets** (endpoint, key, deployment, api-version) as repo secrets.
  `workflow_dispatch`-only means fork PRs cannot trigger it, so exposure is limited to
  collaborators. `infra/docker/README.md` says "No secrets enter the image", which stays true but
  becomes misleading — secrets would enter the *runner*. That line needs a companion sentence.

### Compose healthcheck can never pass

*Found 2026-08-09.* `infra/docker/docker-compose.yml` healthchecks the `llama` service with
`["CMD", "curl", "-fsS", "http://localhost:8080/health"]`, but **there is no `curl` binary in the
runtime image** (nor `wget`) — verified by running both against `qna-chatbot:latest`. The
Dockerfile installs `libcurl4`, which is the shared library `llama-server` links against for its
own downloads, not a command-line tool.

So `llama` never reports healthy, and `chatbot`'s `depends_on: condition: service_healthy` has no
signal to wait on. Fix: use a Python one-liner for the healthcheck (Python is guaranteed present
in the image and needs no new package), or add the `curl` package to the runtime stage.

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

## Naming

### Finish the rename to `qylo`

`README.md:3` promises the project "will take that name soon". That means renaming
`src/qna_chatbot/` to `src/qylo/`, the `[project]` name, the console-script entry point, and every
`uv run qna-chatbot ...` example across `README.md`, `docs/SETUP.md`, `docs/USAGE.md`, `CLAUDE.md`
and `AGENTS.md` — roughly 158 occurrences across ~25 files. **Do it as its own commit with nothing
else in it.**

The `toolbot-cli` mention in `README.md:3` is deliberate and stays; it documents naming history.

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

These are also summarised in `CLAUDE.md` / `AGENTS.md` `## TODO`, because they change how you
should interpret any result while working in the code.

- **Azure agent no longer converges (2026-08-08).** Every Azure run burns 5 retrieval calls and
  stops at the 10-step limit without producing a final answer — including `GENERAL` questions that
  need no retrieval at all. Reproduces on the host, so it is not container-related; the local
  provider converges fine on the same stack. This inverts the reliability ordering the older notes
  record. Not bisectable (the work predates the first commit). See `TROUBLESHOOT.MD` (2026-08-08).
- **Local path-attribution gap.** The 20-call sample's 2 misses were never attributed to the
  structured-output path versus the text-parsing fallback, so it is unknown which fix applies —
  schema tuning or tool-calling reliability. See `TROUBLESHOOT.MD`, "Two open gaps, explained".
- **Ungrounded-destructive-command gap.** A command request with no matching doc has no `Safety:`
  tag to check and therefore no deterministic safety net — model judgment alone decides `CMD` vs
  `UNSAFE`. Needs a code change (command-text pattern matching), not more grounding data.
