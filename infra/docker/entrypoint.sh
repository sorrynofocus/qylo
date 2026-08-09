#!/bin/sh
# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.07
# Container entrypoint for the QnA-Chatbot image. Dispatches between the one-shot CLI,
# a batched run over a file of questions, and the bundled llama.cpp server.
#
# Purpose:
# The image ships two executables that matter (qna-chatbot and llama-server) and one
# convenience mode (batch). Rather than publishing separate images or making callers
# remember --entrypoint, this script routes on the first argument.
#
# Usage examples (see infra/docker/README.md for granular details):
#
# Ask one question (the default path - anything unrecognized is passed straight through):
# docker run --rm --env-file .env qna-chatbot "What is flogger?"
#
# Ask several, one per line, from a mounted file:
# docker run --rm --env-file .env -v ./questions.txt:/q.txt qna-chatbot batch /q.txt
#
# Run the local model server instead of the CLI:
# docker run --rm -p 8080:8080 qna-chatbot serve

set -eu

MODEL_DIR="${MODEL_DIR:-/opt/models/qwen}"
LLAMA_CACHE="${LLAMA_CACHE:-/models}"

# Repo and quantization used when the weights were not baked into the image and
# have to be fetched at first start. Kept in sync with the Dockerfile's weights-1 stage.
LLAMA_HF_REPO="${LLAMA_HF_REPO:-unsloth/Qwen3.5-9B-GGUF}"
LLAMA_HF_QUANT="${LLAMA_HF_QUANT:-Q5_K_M}"

# Server tuning. -c is the context window; -ngl offloads layers to a GPU and is
# silently ignored on a CPU-only build, so it is safe to always pass.
#
# LLAMA_CTX is deliberately NOT the 4096 used by the README's host-side example.
# That figure is fine for a single-shot chat and is far too small here: this is an
# AGENTIC loop, so each retrieval tool call appends more retrieved chunks to the
# conversation. Measured at 4096, a two-call run hit "n_tokens = 4095,
# truncated = 1" and the model then degenerated into repeating its final answer
# over and over. Truncation mid-loop does not surface as an error - it surfaces as
# a garbage answer, which is far harder to diagnose.
#
# LLAMA_PARALLEL is 1 because llama-server divides the context pool across slots
# and this CLI is one-shot: 4 slots would quarter the usable window for no gain.
LLAMA_CTX="${LLAMA_CTX:-16384}"
LLAMA_PARALLEL="${LLAMA_PARALLEL:-1}"
LLAMA_NGL="${LLAMA_NGL:-99}"
LLAMA_PORT="${LLAMA_PORT:-8080}"


# --- serve -----------------------------------------------------------------
# Start llama.cpp's OpenAI-compatible server. Prefers the GGUF baked into the
# image; falls back to downloading on first start when built with
# BAKE_LLM_WEIGHTS=0, in which case $LLAMA_CACHE should be a persistent volume
# so the ~6.5GB pull happens once rather than per container.
#
# Binds 0.0.0.0 rather than 127.0.0.1: inside a container, loopback is not
# reachable from anywhere else, so a localhost bind would serve nobody.
serve() {
    baked_model="$(find "${MODEL_DIR}" -name '*.gguf' -type f 2>/dev/null | head -n 1)"

    if [ -n "${baked_model}" ]; then
        echo "entrypoint: serving baked model ${baked_model}" >&2
        exec llama-server \
            -m "${baked_model}" \
            -c "${LLAMA_CTX}" \
            --parallel "${LLAMA_PARALLEL}" \
            -ngl "${LLAMA_NGL}" \
            --host 0.0.0.0 \
            --port "${LLAMA_PORT}"
    fi

    echo "entrypoint: no baked model in ${MODEL_DIR}; fetching ${LLAMA_HF_REPO}:${LLAMA_HF_QUANT}" >&2
    echo "entrypoint: this needs network access and caches to ${LLAMA_CACHE}" >&2
    exec llama-server \
        -hf "${LLAMA_HF_REPO}:${LLAMA_HF_QUANT}" \
        -c "${LLAMA_CTX}" \
        --parallel "${LLAMA_PARALLEL}" \
        -ngl "${LLAMA_NGL}" \
        --host 0.0.0.0 \
        --port "${LLAMA_PORT}"
}


# --- batch -----------------------------------------------------------------
# Run one question per line from $1.
#
# Note this loops the PROCESS, not the work: rag.py builds an InMemoryVectorStore
# that is discarded at exit, so every question re-scans, re-chunks and re-embeds
# the entire corpus. Fine for a handful of questions; genuinely wasteful for
# hundreds. Real batching would need the vector store to persist across
# questions, which is a code change, not an entrypoint change.
#
# Exits non-zero if ANY question failed, while still attempting all of them - a
# CI caller wants the full list of failures, not just the first.
batch() {
    questions_file="${1:-}"

    if [ -z "${questions_file}" ]; then
        echo "entrypoint: 'batch' needs a file path, e.g. batch /questions.txt" >&2
        exit 2
    fi

    if [ ! -r "${questions_file}" ]; then
        echo "entrypoint: cannot read questions file: ${questions_file}" >&2
        exit 2
    fi

    failures=0
    total=0

    # The redirect on `done` (not a pipe) keeps the loop in this shell so the
    # counters survive it.
    while IFS= read -r question || [ -n "${question}" ]; do
        # Skip blanks and #-comments so question files can be annotated.
        case "${question}" in
            ''|'#'*) continue ;;
        esac

        total=$((total + 1))
        echo "--- [${total}] ${question}"

        if ! qna-chatbot "${question}"; then
            failures=$((failures + 1))
            echo "entrypoint: question failed: ${question}" >&2
        fi
    done < "${questions_file}"

    echo "entrypoint: ${total} question(s), ${failures} failure(s)" >&2
    [ "${failures}" -eq 0 ] || exit 1
}


# --- dispatch --------------------------------------------------------------
case "${1:-}" in
    serve)
        shift
        serve "$@"
        ;;
    batch)
        shift
        batch "$@"
        ;;
    *)
        # Default: hand everything to the CLI unchanged, so every documented
        # qna-chatbot flag works as-is against the container.
        exec qna-chatbot "$@"
        ;;
esac
