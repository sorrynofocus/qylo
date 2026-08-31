# tools/ — diagnostic harnesses

Throwaway-quality measurement scripts, kept because rebuilding them costs more than
storing them. **These are not tests.** They call a real model provider, cost real tokens,
and have no assertions about correctness beyond what they print (with one exception,
noted below).

They are not part of the package and are not installed by `uv sync` — they simply import
`qylo` from the project environment.

## Why these exist

The Azure backend is stochastic and cannot be pinned: `gpt-5-nano` rejects an explicit
`temperature`, the OpenAI/Azure chat API exposes no `top_k`, and `seed` is best-effort at
most. A single run therefore proves nothing about a change.

That is not a theoretical concern. Over one session (see `TROUBLESHOOT.MD`, 2026-08-08),
**three separate changes were argued convincingly and then measured worse** — an added
pre-emit intent check, a conversational clarification, and the removal of the
CONVERSATIONAL category. Each looked correct on paper. One of them dropped convergence
from 12/20 to 4/20.

Run these before and after any change to `system_prompt.txt`, to the agent construction
in `assistant.py`, or to retrieval settings.

## The scripts

| Script | Answers |
| --- | --- |
| `score_contract.py` | How often does the agent terminate, and how often is the classification right? |
| `stream_agent.py` | *Why* is a particular run looping? |
| `verify_retry.py` | Does the bounded retry in `answer()` actually run? |

### `score_contract.py`

Scores one case per response-contract branch — grounded (`ANS`), ungrounded (`GENERAL`),
command (`CMD`/`UNSAFE`), conversational (`GENERAL`) — through the real
`RagAssistant.answer()` path, so the retry and the deterministic `Safety: unsafe`
override are both included.

```sh
uv run python tools/score_contract.py        # 5 rounds per case
uv run python tools/score_contract.py 10     # tighter estimate, 2x the tokens
```

Reference figures, Azure, `k=4`, 10-step limit:

| Prompt | Answered | Correct |
| --- | --- | --- |
| Original (pre-2026-08-08) | 0/9 | — |
| Current | 18/20 | 16/20 |

### `stream_agent.py`

The one that cracked the original bug. `.invoke()` raises `GraphRecursionError` on the
step limit and discards every intermediate message, so a loop is invisible from the
exception. This streams with `stream_mode="values"` and prints each message as produced.

```sh
uv run python tools/stream_agent.py
uv run python tools/stream_agent.py "How do I shut down Windows in 30 minutes?"
uv run python tools/stream_agent.py "What is flogger?" data/documents/Flogger-README.md
```

**Read the tool-call arguments, not just the count.** Repeated calls with *different*
arguments mean the model is exploring — it may need better context or a larger budget.
Repeated calls with the *same* argument mean it has no reachable terminal state, which is
a control-flow problem, not a model-quality one. Those have opposite fixes.

### `verify_retry.py`

Sets `max_agent_steps=1` so every attempt is guaranteed to raise, then counts
invocations. This is the only script here that asserts — it fails loudly if the retry
count is wrong or if exhaustion stops degrading to `GENERAL`.

```sh
uv run python tools/verify_retry.py
```

Live traffic cannot confirm this: a healthy run converges on the first attempt and never
touches the retry path.

## Reading the numbers

**"Correct" means the label matched, and nothing more.** The check is literally
`response.kind.name in expected` — did the response come back `ANSWER`, `GENERAL`,
`COMMAND` or `UNSAFE` as the case expects. It says nothing about whether the answer was
factually right, whether the citation was real, or whether the command would actually
work. Record a score as *classification* correctness, never as answer accuracy.

**Sample sizes are small.** A handful of rounds can flag a large failure — `0/9` is worth
acting on — but it cannot establish that a true success rate is zero or one, and it cannot
separate 70% from 85% at all. Read a `0/9` as "something is badly wrong here", not as proof
that the case never works; read the gap between 17/20 and 18/20 as nothing.

**The ±2-out-of-20 rule of thumb is a heuristic, not a confidence interval.** It was
inherited, not computed. Do not use it to wave away every smaller movement, and do not
treat a larger one as proof of a regression on its own.

**A perfect row going imperfect is a trigger to look, not a verdict.** An unchanged
process succeeding independently 90% of the time still misses at least once in five trials
about 41% of the time (1 − 0.9⁵). That is an illustration of how weak n=5 is, not an
estimate of this model's success rate. Read the failure detail and repeat the observation
before concluding anything.

**Two failure modes, very different severity.** An exhausted retry is loud and harmless.
A command request classified `ANS` is the quiet one: the `Safety: unsafe` override in
`answer()` only fires when `kind is ResponseKind.COMMAND`, so an `ANS`-labelled command
bypasses the safety-*classification* override and is presented to the user as an ordinary
answer rather than as a gated command. It does **not** bypass execution gating —
`apply_exe_request()` returns immediately for `ANSWER` and `GENERAL` regardless of `--exe`
or `--yolo`, and `tests/test_execution_gate.py` asserts exactly that across all 16
combinations. Watch the `<<WRONG` markers on the `command` row more closely than the
totals.

## Cost and runtime

Every script makes live model calls. The figures below are for `score_contract.py` at the
default 5 rounds — 4 cases × 5 rounds = 20 full agent runs.

**Runtime: ~23 minutes** on Azure `gpt-5-nano`, measured end to end on 2026-08-30 (18:18 →
18:41, including the one-time ingestion of 168 chunks).

Do not extrapolate from the early cases — the first two finished in ~7 minutes, which projects
to 15 and is wrong by a third. Cases are not equal cost: every `EXHAUSTED` result means the
bounded retry ran all three attempts for that round, so the slow cases are slow *because* they
are failing. Worse convergence therefore tends to cost more wall clock, not less — a tendency
across stochastic runs, not a guaranteed ordering between any two. Passing a round count
(`... score_contract.py 10`) scales the wall clock with it.

**Tokens: an inherited ~16k-per-agent-run figure, extrapolating to ~320k for a default run.**
Treat this as unverified. `score_contract.py` collects no usage totals of its own, the older
"per run" wording never established its unit, and the underlying measurement has not been
located. The one instrument that could have produced a real number was `qylo --usage`, which Phase
B of the readability refactor removed — so the totals now have to come from the provider's own
usage reporting. What is structurally certain: each additional model call in the tool-calling loop resends the whole
growing message history, so a 2-call run sends the system prompt twice, not once.

**Money: cents, with the exact figure depending on a split nobody has measured.** Using only
the rates quoted here (`gpt-5-nano` ~$0.05/M input, ~$0.40/M output, not independently
re-checked, before any discount), 320k tokens costs **$0.016 if entirely input and $0.128 if
entirely output**. Any tighter estimate assumes a mix. Cheap enough to run a before/after pair
without thinking about it; not cheap enough — and nowhere near fast enough — to sit in a loop.

That gap is the whole reason `tests/` and `tools/` are separate directories: the offline suite
in `tests/` runs in ~13 seconds and costs nothing, so it can gate every change. These cost
money and minutes, so they gate prompt and agent-construction changes only.

Point `CHATBOT_MODEL_PROVIDER` at `local` to measure without spend — and note that the local
backend has **not** been re-measured against the current prompt, which is item 2 on the
open list in `TROUBLESHOOT.MD`.
