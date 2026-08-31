# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.31
# Defaults and .env resolution for every later stage.
#
# Stage 1a of the request flow. Called by cli.py; used by documents.py,
# retrieval.py and assistant.py.
#
# Purpose:
# One place to answer "what is the default, and which .env variable overrides
# it?". Plain module constants and a call-time environment reader - no config
# object, no framework, nothing to construct. Every value here was previously a
# constant near the code that used it, which meant the defaults for one run were
# spread across two files.
#
# Reads happen when a function is called, never at import, so load_dotenv() in
# cli.py::main() still runs before anything looks at the environment. Importing
# this module must not be able to fail on a bad .env value.
#
# Usage examples (see README for granular details):
#
# Fall back to a default unless .env overrides it:
# size = positive_int_from_env(string_table.ENV_CHUNK_SIZE, DEFAULT_CHUNK_SIZE)
#
# Use a default directly:
# assistant = RagAssistant(store, model, retrieval_k=DEFAULT_RETRIEVAL_K)
#

from __future__ import annotations

import os
from pathlib import Path

from qylo import string_table

# Where cli.py looks for documents when neither --documents nor --doc is given.
DEFAULT_DOCS_PATH = Path("data") / "documents"

# Default local embedding model. It maps text into a 384-dimensional vector
# space so semantically similar chunks can be found with similarity search.
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Chunking defaults. Both are overridable from .env (CHATBOT_CHUNK_SIZE /
# CHATBOT_CHUNK_OVERLAP) - see documents.py::split_documents(). Sizes are in
# characters, not tokens: overlap is how much text adjacent chunks share so a
# sentence split across a boundary still appears whole in at least one chunk.
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200

# How many chunks the retrieval tool returns per search. The -k CLI flag
# overrides this per run.
DEFAULT_RETRIEVAL_K = 4

# create_agent's compiled LangGraph graph does NOT inherit langchain_core's
# well-known RunnableConfig default of 25 - langgraph 1.x sets its own
# internal default (DEFAULT_RECURSION_LIMIT, langgraph/_internal/_config.py)
# of 10,007 graph steps, which is effectively no cap at all for a chat agent.
# One "step" is one node execution (one model call OR one tool call), so a
# model that never converges to a final answer can run to ~5,000 real model
# calls before LangGraph itself would ever intervene - see TROUBLESHOOT.MD
# for a measured real-world case that hit 118 model calls / 114 retrievals
# for a single question before it happened to converge on its own. 10 steps
# is enough headroom for the system prompt's own stated behavior ("call it
# again with a refined query if the first results seem incomplete" - up to
# ~4 retrieval round trips) plus the final answer, while still failing fast
# and cheaply instead of silently running away.
DEFAULT_MAX_AGENT_STEPS = 10

# How many times to run the whole agent for one question before giving up.
#
# Non-convergence on this stack is stochastic, not deterministic: the same
# question, prompt and model either terminates or loops depending only on
# sampling. gpt-5-nano rejects an explicit temperature, so that randomness
# cannot be turned off from here.
#
# Measured on Azure (2026-08-08, 5 rounds x 4 cases, TROUBLESHOOT.MD): a single
# attempt converged 13/20, while allowing up to 3 attempts converged 18/20 -
# and for the three real query shapes (grounded / ungrounded / command) retrying
# took 12/15 to 15/15. Failures behave as independent draws, so a bounded retry
# is worth far more here than any further prompt wording.
#
# The cost is real and bounded: a retry re-runs the model calls (not ingestion
# or embedding, which happen once per process), so a worst case is 3x the model
# spend on a question that was going to fail anyway. Retrying only ever happens
# after a GraphRecursionError, never on a successful answer.
DEFAULT_MAX_AGENT_ATTEMPTS = 3


def positive_int_from_env(name: str, default: int) -> int:
    """
    Read a positive integer from the environment and convert it to int
    - or fall to a default.
    similar to atoi() since env are strings and we need an int

    Parameters:
        name: Environment variable to read. Unset or empty falls back.
        default: Value used when the variable isn't set.

    Raises RuntimeError with the offending variable named when the value isn't
    a positive integer, so a typo in .env fails loudly instead of silently
    reverting to the default.
    """

    raw_val = os.getenv(name)

    if not raw_val:
        return default
    #  ok, so
    try: # and try again.
        value = int(raw_val)
    except ValueError:
        raise RuntimeError(string_table.MSG_INVALID_INT_ENV.format(name=name, value=raw_val)) from None

    if value <= 0:
        raise RuntimeError(string_table.MSG_INVALID_INT_ENV.format(name=name, value=raw_val))
    return value
