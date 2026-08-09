# Setup and configuration

Environment creation, model-provider choice, and the `.env` field reference. Back to [README.md](../README.md).

## Setup

### 1. Create the Python environment

```sh
uv venv
uv sync
```

Activate it on Windows:

```sh
.venv\Scripts\activate
```

### 2. Choose a model provider

`CHATBOT_MODEL_PROVIDER` in `.env` picks which one the app uses — see [Configuration](#configuration) below for the exact `.env` fields once you've set one up.

#### Option A: Local inference (llama.cpp)

Runs a model on your own machine via [llama.cpp](https://github.com/ggml-org/llama.cpp)'s OpenAI-compatible server, free and private, but slower without a GPU (see [Provider comparison](USAGE.md#provider-comparison-measured) below).

1. **Check for an NVIDIA GPU** (optional; llama.cpp falls back to CPU if you skip this or don't have one):
   ```sh
   nvidia-smi
   ```
   Note the reported CUDA version.

2. **Install llama.cpp.** Go to the [releases page](https://github.com/ggml-org/llama.cpp/releases)
   and download the asset matching your setup — always take the *latest*
   release's build, not a pinned one (`XXX` below stands for that release's
   build number, e.g. `b9946`):
   - **CPU-only** (no GPU, or skipping GPU acceleration — this project's own
     measurements in [Provider comparison](USAGE.md#provider-comparison-measured)
     below used this build): `llama-bXXX-bin-win-cpu-x64.zip`
   - **NVIDIA GPU, CUDA 12.x**: `llama-bXXX-bin-win-cuda-12.4-x64.zip`

   Extract it somewhere like `C:\Program Files\llamacpp` and add that folder
   to your `PATH`.

Verify:

   ```sh
   llama-cli --version
   ```

If you installed the GPU build, confirm your NVIDIA drivers/CUDA toolkit are set up correctly — you should see these GPU-specific DLLs under `C:\Program Files\llamacpp`:

```text
cublas64_*.dll
cudart64_*.dll
cusparse64_*.dll
cublasLt64_*.dll
```

Their presence confirms the GPU build is installed; their absence is normal and expected for the CPU-only build.

3. **Install the Hugging Face CLI** (used to fetch and cache models):
   ```sh
   pip install --upgrade huggingface_hub
   ```
4. **Start the server.** This downloads the model on first run (cached under `~/.cache/huggingface`) and serves it on `http://127.0.0.1:8080`:
   ```sh
   llama-server -hf unsloth/Qwen3.5-9B-GGUF:Q5_K_M -c 4096 -ngl 99 --host 127.0.0.1 --port 8080
   ```
   `-ngl 99` offloads layers to a GPU; it's silently ignored on a CPU-only build, so it's safe to always include. For more CPU throughput, add `--threads 8 --threads-batch 8 --flash-attn on`.
5. **Sanity-check it directly** (optional): run `hf cache ls` to find the cached `.gguf` path, then:
   ```sh
   llama-cli -m <path-from-hf-cache-ls> -p "hello" -ngl 99
   ```

Point `.env` at it with `LOCAL_OPENAI_BASE_URL=http://localhost:8080/v1` (see [Configuration](#configuration)).

#### Option B: Cloud inference (Azure OpenAI)

1. In Azure AI Foundry, deploy a chat model (e.g. `gpt-5-nano`) using a standard deployment.
2. Copy the deployment's endpoint and API key into `.env` (see [Configuration](#configuration)).

### Prefer not to install any of this?

Everything above — Python, `uv`, llama.cpp, the embedding model, the GGUF — is also
available prebuilt as a container image, so a machine with Docker needs none of it. See
[infra/docker/README.md](../infra/docker/README.md).

## Configuration

Create a `.env` file in the project root:

```env
CHATBOT_MODEL_PROVIDER=azure

AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<your-api-key>
AZURE_OPENAI_CHAT_DEPLOYMENT=<your-chat-deployment-name>
AZURE_OPENAI_API_VERSION=2024-12-01-preview
```

**API version (`AZURE_OPENAI_API_VERSION`) — where that value comes from**

This is the one field you can't look up from your own resource, and the one most likely to send you to the wrong documentation. It is **not** the model version.

| | What it is | How to find it |
|---|---|---|
| **API version** (`2024-12-01-preview`) | Which revision of the Azure OpenAI REST contract you're speaking. A property of the *API*, not of anything you deployed. | Microsoft's docs, or copied from a Foundry code sample (below). No `az` command returns it. |
| **Model version** (`2025-08-07`) | Which snapshot of `gpt-5-nano` is deployed. Used by `infra/azure/main.bicepparam`, not by `.env`. | `az cognitiveservices account deployment show --name <account> --resource-group <rg> --deployment-name <deployment> --query "properties.model" -o jsonc` |

Two practical ways to get a correct API version:

1. **Copy it from Azure AI Foundry.** Open your deployment in the Foundry portal and look at the sample code it generates — the `api_version` is filled in with a working value. This is the fastest route and needs no doc-hunting.
2. **Pick one from the changelog.** [Azure OpenAI API version lifecycle](https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle) (Microsoft Learn) lists every dated version and what each one added.

**Don't look for this on `developers.openai.com`.** OpenAI's own API reference documents *OpenAI's* service, which has entirely separate versioning. Azure OpenAI is a distinct REST surface maintained by Microsoft, so no Azure `api-version` string will ever appear in OpenAI's docs regardless of which model you deployed.

**Why it's pinned rather than defaulted.** The API version gates *features*, not just wire format — structured outputs, which this project relies on for `ContractResponse`/`ToolStrategy`, arrived in `2024-08-01-preview`. Pinning it means a server-side default shift can't silently change which response path works. It's also genuinely required: omitting it fails at client construction with `Must provide either the api_version argument or the OPENAI_API_VERSION environment variable` (raised by the OpenAI SDK, not by this project's code — `model_provider.py::env_required` just catches it earlier with a clearer message).

Microsoft now also offers a **v1 API** that drops `api-version` entirely, but it's a code change rather than a config change: it uses the plain `OpenAI()` client against a `/openai/v1/` base URL instead of `AzureChatOpenAI`. That's why `AZURE_OPENAI_ENDPOINT` here must stay the resource root with **no** `/openai/v1` suffix — see the endpoint-format error in ["What if...?"](USAGE.md#what-if-errors-and-edge-cases-not-tied-to-one-flag).

To use a local OpenAI-compatible model server such as llama.cpp:

```env
CHATBOT_MODEL_PROVIDER=local
LOCAL_OPENAI_BASE_URL=http://localhost:8080/v1
LOCAL_OPENAI_API_KEY=local-not-used
LOCAL_MODEL_NAME=qwen3.5-9b
```

**Command execution (`CHATBOT_EXECUTE_COMMANDS`)**

```env
CHATBOT_EXECUTE_COMMANDS=true
```

The `.env` equivalent of passing `--exe` on every run: a `CMD:` response executes immediately, with no flag and no prompt. It does **not** cover `UNSAFE:` responses — those still require `--yolo` on the command line, which has no `.env` equivalent by design, so the riskiest execution path always stays a deliberate, per-run decision. Any value other than `true` (case-insensitive) leaves execution off; `cli.py::main()` reads it as `os.getenv(...).lower() == "true"`.

**Chunking (`CHATBOT_CHUNK_SIZE` / `CHATBOT_CHUNK_OVERLAP`)**

```env
# CHATBOT_CHUNK_SIZE=1000
# CHATBOT_CHUNK_OVERLAP=200
```

Both are optional — leave them out (or commented, as above) and the shown defaults apply. The units are **characters, not tokens**. `CHATBOT_CHUNK_OVERLAP` is how much text two adjacent chunks share, so a sentence straddling a chunk boundary still appears whole in at least one chunk; it must be smaller than `CHATBOT_CHUNK_SIZE`, and both must be positive whole numbers. Raise the chunk size for long, continuous prose where the answer spans several paragraphs; lower it for short reference/flag docs, where tighter chunks retrieve more precisely and an oversized chunk just drags unrelated flags along with the one you asked about. This is a different knob from `-k`, which is a CLI flag for how many chunks come back per search — see ["Tuning `-k`"](USAGE.md#tuning--k).

The selected provider is built by `ModelProvider` in `model_provider.py`. `rag.py` receives a normal LangChain chat model and does not need to know whether the model is Azure-hosted or local.

To (re)provision the Azure OpenAI resource itself declaratively instead of via the Portal, see [infra/azure/README.md](../infra/azure/README.md).

Embeddings are always local, via HuggingFace:

```text
sentence-transformers/all-MiniLM-L6-v2
```
