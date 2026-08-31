# syntax=docker/dockerfile:1.7
# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.08.07
# Container image for the Qylo RAG CLI. Installs everything the by-hand host setup
# installs - llama.cpp built from source, the HuggingFace embedding model, tiktoken's BPE
# table, and every Python dependency - so a fresh machine or a CI runner needs only Docker.
#
# Purpose:
# Make the setup reproducible. The host install in the root README works but is a sequence
# of manual steps; this file is that sequence made executable. The resulting image performs
# ZERO network downloads at run time, for either model provider.
#
# Usage examples (see infra/docker/README.md for granular details):
#
# IMPORTANT: the build context is the REPOSITORY ROOT, not this directory.
#
# Full image, Qwen weights baked in (~8GB, runs offline against llama.cpp):
# docker build -f infra/docker/Dockerfile -t qylo .
#
# Slim image, Azure-only (~1.5GB, no local model - use when disk is tight, e.g. CI):
# docker build -f infra/docker/Dockerfile --build-arg BAKE_LLM_WEIGHTS=0 -t qylo:slim .
#
# Ask a question (Azure provider):
# docker run --rm --env-file .env qylo "What is flogger?"
#
# Pin a different llama.cpp release:
# docker build -f infra/docker/Dockerfile --build-arg LLAMACPP_REF=b10298 -t qylo .


# Declared here, BEFORE the first FROM, because that is the only scope Docker will
# expand inside a FROM instruction. An ARG placed between stages belongs to the
# preceding stage instead, expands to empty in `FROM weights-${BAKE_LLM_WEIGHTS}`,
# and the build dies with: failed to parse stage name "weights-".
ARG BAKE_LLM_WEIGHTS=1


# ---------------------------------------------------------------------------
# Stage: base
# Purpose:   Single source of truth for the Python runtime and every cache path
#            used later. Declaring these once means no downstream stage can warm
#            a cache into a directory that the runtime stage does not read back.
# Produces:  A bare interpreter image plus the shared ENV contract.
# Consumed by: python-deps, weights-0, runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS base

# Matches .python-version (3.12) and pyproject.toml's requires-python >=3.12.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/hf-cache \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache \
    MODEL_DIR=/opt/models/qwen \
    LLAMA_CACHE=/models


# ---------------------------------------------------------------------------
# Stage: llamacpp-builder
# Purpose:   Compile llama.cpp from a pinned source ref. Built rather than
#            downloaded so the binary matches a known commit and so build flags
#            are ours to choose - specifically GGML_NATIVE=OFF (see below).
#            Every compiler and header lands here and is discarded with the stage.
# Produces:  /out/bin/llama-* and /out/lib/*.so
# Consumed by: runtime
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim AS llamacpp-builder

# libcurl4-openssl-dev is NOT optional: without it LLAMA_CURL is disabled and
# `llama-server -hf <repo>` cannot download a model at all, which is the fallback
# path used whenever the weights are not baked into the image.
RUN apt-get update && apt-get install --no-install-recommends -y \
        git \
        cmake \
        build-essential \
        libcurl4-openssl-dev \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# A published llama.cpp release tag. Bump deliberately; do not track a branch.
ARG LLAMACPP_REF=b10298

# Compile parallelism. Deliberately NOT $(nproc): each concurrent g++ on this
# codebase can hold ~1GB, and the builder VM's memory is usually far smaller than
# its advertised CPU count suggests. Docker Desktop in particular defaults to a
# low memory ceiling while exposing every host core, so -j$(nproc) fans out 16
# compilations into ~2GB and the daemon dies mid-build with an unhelpful
# "error reading from server: EOF" rather than an OOM message.
#
# Raise it on a machine with memory to spare: --build-arg BUILD_JOBS=8
ARG BUILD_JOBS=4

WORKDIR /src
RUN git clone --depth 1 --branch "${LLAMACPP_REF}" \
        https://github.com/ggml-org/llama.cpp.git .

# GGML_NATIVE=OFF is load-bearing, not a tuning preference.
#
# llama.cpp defaults to -march=native, which bakes the BUILD machine's CPU
# instruction set into the binary. A GitHub runner with AVX-512 would produce a
# binary that dies with SIGILL on a VMWare guest exposing a narrower CPU. Off
# gives up a little throughput to buy an image that runs anywhere.
#
# CPU-only by design: the app never passes a device to the embedding model, and
# llama.cpp publishes no Linux CUDA build, so there is nothing to gain here.
RUN cmake -B build \
        -DCMAKE_BUILD_TYPE=Release \
        -DLLAMA_CURL=ON \
        -DGGML_NATIVE=OFF \
        -DLLAMA_BUILD_TESTS=OFF \
        -DLLAMA_BUILD_EXAMPLES=OFF \
        -DBUILD_SHARED_LIBS=ON \
    && cmake --build build --config Release -j "${BUILD_JOBS}"

# Collect just the artifacts the runtime needs, so the COPY below is a fixed
# shape regardless of how llama.cpp lays out its build tree in a given release.
RUN mkdir -p /out/bin /out/lib \
    && find build -type f -name 'llama-*' -perm -u+x -exec cp {} /out/bin/ \; \
    && find build -type f -name '*.so*' -exec cp -P {} /out/lib/ \; \
    && ls -1 /out/bin


# ---------------------------------------------------------------------------
# Stage: python-deps
# Purpose:   Resolve and install the Python dependency tree with uv, against the
#            committed uv.lock. Split from cache-warm so that editing src/ does
#            not invalidate the (much slower) model download layers.
# Produces:  /app/.venv
# Consumed by: cache-warm, weights-1, runtime
# ---------------------------------------------------------------------------
FROM base AS python-deps

# uv is mandatory rather than a convenience: pyproject.toml declares
# build-backend = "uv_build", so pip alone cannot build this project.
#
# Pinned to the exact uv that produced the committed uv.lock. This is the
# distroless uv image - it has no shell and the binary sits at /uv, not in
# /usr/local/bin. There is no <version>-python<ver>-<distro> combined tag, so do
# not try to fold the Python base in here.
COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Two-step install for layer caching: dependencies first (they change rarely),
# then the project itself (changes constantly).
#
# README.md is copied because pyproject.toml declares readme = "README.md";
# the build fails with a missing-file error without it.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY src/ ./src/

# --no-editable is required, not an optimization. uv sync installs the project in
# editable mode by default, which writes only a .pth pointing back at /app/src.
# The runtime stage copies .venv but not the source tree, so an editable install
# produces a venv whose console script exists and immediately dies with
# "ModuleNotFoundError: No module named 'qylo'". --no-editable copies the
# package into site-packages so the venv is self-contained.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


# ---------------------------------------------------------------------------
# Stage: cache-warm
# Purpose:   Pre-download the two small artifacts the app fetches on first use,
#            so the runtime image never reaches the network. Both are warmed
#            through the app's OWN call paths, guaranteeing the on-disk cache
#            layout matches exactly what the app looks for later.
# Produces:  $HF_HOME (embedding model), $TIKTOKEN_CACHE_DIR (BPE table)
# Consumed by: runtime
# ---------------------------------------------------------------------------
FROM python-deps AS cache-warm

ENV PATH="/app/.venv/bin:$PATH"

# Mirrors rag.py::build_embeddings(), which constructs HuggingFaceEmbeddings with
# no cache_folder argument - so the model must land in the default HF_HOME location.
# Needed by BOTH providers: embeddings are always computed locally, even when the
# chat model is Azure.
RUN python -c "\
from langchain_huggingface import HuggingFaceEmbeddings; \
HuggingFaceEmbeddings(model_name='sentence-transformers/all-MiniLM-L6-v2')"

# The cl100k_base BPE table. Nothing in src/ imports tiktoken any more - the
# telemetry feature that did was removed - but langchain_openai still depends on
# it and exposes token-counting paths, so it is warmed unconditionally: a lazy
# vocab download must never be the thing that turns an air-gapped run into a hard
# failure. Retaining it is a recorded decision - see docs/BACKLOG.md, "The
# tiktoken cache outlived telemetry, deliberately".
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"


# ---------------------------------------------------------------------------
# Stage: weights-0
# Purpose:   The "no baked weights" arm of the BAKE_LLM_WEIGHTS switch. Creates an
#            empty model directory so the runtime COPY below has a valid source
#            either way. The entrypoint detects the empty directory and falls back
#            to downloading at first start.
# Produces:  An empty $MODEL_DIR
# Consumed by: weights (alias)
# ---------------------------------------------------------------------------
FROM base AS weights-0
RUN mkdir -p "${MODEL_DIR}"


# ---------------------------------------------------------------------------
# Stage: weights-1
# Purpose:   The "baked weights" arm. Downloads the Qwen GGUF (~6.5GB) so the
#            local provider works with no network at run time. Derives from
#            python-deps because the `hf` CLI ships with huggingface_hub, which
#            is already a transitive dependency.
# Produces:  $MODEL_DIR populated with a single Q5_K_M .gguf
# Consumed by: weights (alias)
# ---------------------------------------------------------------------------
FROM python-deps AS weights-1

ENV PATH="/app/.venv/bin:$PATH"

RUN hf download unsloth/Qwen3.5-9B-GGUF \
        --include "*Q5_K_M*" \
        --local-dir "${MODEL_DIR}" \
    && find "${MODEL_DIR}" -name '*.gguf' -printf '%f  %s bytes\n'


# ---------------------------------------------------------------------------
# Stage: weights (alias)
# Purpose:   Select one of the two arms above by build arg. This is a stage-level
#            switch, not a `RUN if`, and the difference matters: BuildKit never
#            executes a stage nothing references, so BAKE_LLM_WEIGHTS=0 does not
#            merely skip the download - the 6.5GB layer never enters the build
#            graph or the cache. That is the difference between fitting and not
#            fitting on a disk-constrained CI runner.
# Produces:  $MODEL_DIR, empty or populated
# Consumed by: runtime
# ---------------------------------------------------------------------------
# BAKE_LLM_WEIGHTS is declared at the top of this file, before the first FROM -
# see the note there for why it cannot live at this line.
FROM weights-${BAKE_LLM_WEIGHTS} AS weights


# ---------------------------------------------------------------------------
# Stage: runtime
# Purpose:   Final image. Pure assembly - it copies artifacts from the stages
#            above and installs only shared libraries. No compiler, no git, no
#            cmake, no uv, no build cache reaches this layer.
# Produces:  The published image.
# Consumed by: nobody (this is the default target)
# ---------------------------------------------------------------------------
FROM base AS runtime

# libgomp1 = OpenMP runtime the llama.cpp binaries link against.
# libcurl4  = runtime half of the LLAMA_CURL support compiled in above.
RUN apt-get update && apt-get install --no-install-recommends -y \
        libgomp1 \
        libcurl4 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=llamacpp-builder /out/bin/ /usr/local/bin/
COPY --from=llamacpp-builder /out/lib/ /usr/local/lib/
RUN ldconfig

COPY --from=python-deps  /app/.venv          /app/.venv
COPY --from=cache-warm   /opt/hf-cache       /opt/hf-cache
COPY --from=cache-warm   /opt/tiktoken-cache /opt/tiktoken-cache
COPY --from=weights      /opt/models/qwen    /opt/models/qwen

COPY infra/docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# The default corpus. Overridable at run time with a bind mount onto
# /app/data/documents, or with --documents pointing elsewhere.
COPY data/ /app/data/

ENV PATH="/app/.venv/bin:$PATH"

# Set LAST, after every stage that needed to reach the network. With the caches
# baked above, huggingface_hub has nothing left to fetch - but without this it
# still performs a revision check on every single run, which turns into a long
# stall (not a clean error) on a host with no route to the internet.
#
# Safe for llama.cpp: it downloads via its own libcurl, not huggingface_hub, so
# the not-baked fallback path is unaffected by this.
ENV HF_HUB_OFFLINE=1

# Deliberately NOT set: CHATBOT_EXECUTE_COMMANDS. cli.py::run_command is a
# subprocess.run(..., shell=True) with no allowlist and no audit log, so command
# execution stays opt-in per run (--exe) rather than baked into the image.

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/logs /models \
    && chown -R appuser:appuser /app /models

USER appuser
WORKDIR /app

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["--help"]
