# tools/ — diagnostic harnesses

Throwaway-quality measurement scripts, kept because rebuilding them costs more than
storing them. **These are not tests.** They call a real model provider, cost real tokens,
and have no assertions about correctness beyond what they print (with one exception,
noted below).

They are not part of the package and are not installed by `uv sync` — they simply import
`qna_chatbot` from the project environment.

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
in `rag.py`, or to retrieval settings.

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

**Sample sizes are small.** 5 rounds per case distinguishes "always" from "never", not
70% from 85%. Treat convergence figures as roughly ±2 out of 20. A `0/9` is meaningful —
zero successes across nine trials is not a variance artifact — but the gap between 17/20
and 18/20 is not.

**Two failure modes, very different severity.** An exhausted retry is loud and harmless.
A command request classified `ANS` is silent and dangerous: the `Safety: unsafe` override
in `answer()` only fires when `kind is ResponseKind.COMMAND`, so an `ANS`-labelled command
bypasses the safety gate entirely. Watch the `<<WRONG` markers on the `command` row more
closely than the totals.

## Cost

Every script makes live model calls. `score_contract.py` at the default 5 rounds is
roughly 20 agent runs; on `gpt-5-nano` that measured around 16k tokens per run. Point
`CHATBOT_MODEL_PROVIDER` at `local` to measure without spend — and note that the local
backend has **not** been re-measured against the current prompt, which is item 2 on the
open list in `TROUBLESHOOT.MD`.
