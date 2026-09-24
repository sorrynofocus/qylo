Name: llama.cpp build and usage guide
Description: How to build llama.cpp from source with CMake, Ninja and clang (CPU, CUDA, Vulkan, HIP, Metal), which executables it produces (llama-server, llama-cli, llama-quantize, llama-bench), and how to run a GGUF model, serve an OpenAI-compatible API, download models, convert and quantize models.

Safety: safe

# llama.cpp build and usage guide

## What llama.cpp is and which executable to use

llama.cpp runs large language models in GGUF format on CPU and GPU. It builds several executables,
all starting with `llama-`:

- `llama-server` — HTTP server with an OpenAI-compatible API and a web UI.
- `llama-cli` — run a model interactively or with a single prompt in the terminal.
- `llama-quantize` — convert a GGUF model to a smaller quantization.
- `llama-bench` — measure prompt processing and generation speed.
- `llama-perplexity` — measure model quality on a text file.
- `llama-embedding` — compute embeddings.
- `llama-tokenize` — show how text is tokenized.
- `llama-gguf-split` — split or merge large GGUF files.
- `llama-mtmd-cli` — multimodal (image/audio) prompts.

The llama.cpp option reference (`llamacpp.md`) is the `llama-server --help` output. Most of its
common, sampling and speculative options are shared by `llama-cli`.

## llama.cpp: get the source

    git clone https://github.com/ggml-org/llama.cpp
    cd llama.cpp

## llama.cpp: build for CPU with CMake

    cmake -B build
    cmake --build build --config Release -j 8

Executables are written to `build/bin` (on Windows with Visual Studio: `build\bin\Release`).

## llama.cpp: build with Ninja and clang

    cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++
    ninja -C build

Build only the server:

    ninja -C build llama-server

Build only the CLI:

    ninja -C build llama-cli

On Windows, llama.cpp ships CMake presets that use clang and Ninja. Run them from a Visual Studio
Developer Command Prompt:

    cmake --preset x64-windows-llvm-release
    cmake --build build-x64-windows-llvm-release

## llama.cpp: GPU builds

NVIDIA CUDA (needs the CUDA toolkit):

    cmake -B build -DGGML_CUDA=ON
    cmake --build build --config Release -j 8

Vulkan (needs the Vulkan SDK):

    cmake -B build -DGGML_VULKAN=ON
    cmake --build build --config Release -j 8

AMD ROCm/HIP:

    cmake -B build -DGGML_HIP=ON
    cmake --build build --config Release -j 8

Apple Metal is enabled by default on macOS; disable it with `-DGGML_METAL=OFF`.

## llama.cpp: other useful CMake options

- `-DGGML_NATIVE=OFF` — do not optimize for the build machine's CPU (for portable binaries).
- `-DBUILD_SHARED_LIBS=OFF` — link libllama and ggml statically.
- `-DLLAMA_BUILD_TESTS=OFF` and `-DLLAMA_BUILD_EXAMPLES=OFF` — shorter builds.
- `-DLLAMA_CURL=OFF` — build without libcurl if CMake cannot find CURL (disables `-hf` downloads).

List every option with its current value:

    cmake -B build -LH

## llama.cpp: clean and rebuild

    cmake --build build --target clean
    cmake --build build --config Release -j 8

Rebuild from scratch by deleting the `build` folder and configuring again.

## llama.cpp: generate LLVM IR for a llama.cpp source file

Configure with clang and a compilation database:

    cmake -S . -B build -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_EXPORT_COMPILE_COMMANDS=ON

`build/compile_commands.json` holds the exact clang command for every llama.cpp source file. Take
the command for a file, replace `-c` with `-S -emit-llvm` and set `-o` to a `.ll` file to get its
LLVM IR. `ninja -C build -t commands llama-server` prints the same commands.

## llama-server: serve a local GGUF model

    llama-server -m models/model.gguf --host 127.0.0.1 --port 8080

Recommended starting point, with a 16k context, all layers on the GPU, and chat templates enabled
for tool calling:

    llama-server -m models/model.gguf -c 16384 -ngl 99 --jinja --host 127.0.0.1 --port 8080

- `-m, --model FNAME` — path to the GGUF model.
- `-c, --ctx-size N` — context size in tokens (0 = the model's value).
- `-ngl, --n-gpu-layers N` — number of layers to offload to the GPU.
- `--jinja` — use the model's Jinja chat template (needed for tool/function calling).
- `--parallel N` — number of request slots; the context is divided between slots.
- `--api-key KEY` — require a key on requests.
- `--host`, `--port` — listen address. Use `127.0.0.1` to stay local.

## llama-server: download and serve a model from Hugging Face

    llama-server -hf ggml-org/gemma-3-1b-it-GGUF

Pick a quantization with a `:` suffix:

    llama-server -hf ggml-org/GLM-4.7-Flash-GGUF:Q4_K_M

`-hf` downloads from the internet and stores the model in the local cache; `llama-server -cl`
lists cached models.

## llama-server: call the OpenAI-compatible API

Health check:

    curl http://127.0.0.1:8080/health

List models:

    curl http://127.0.0.1:8080/v1/models

Chat completion:

    curl http://127.0.0.1:8080/v1/chat/completions -H "Content-Type: application/json" -d "{\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}]}"

Any OpenAI client works with base URL `http://127.0.0.1:8080/v1`. The web UI is at
`http://127.0.0.1:8080`.

## llama-cli: run a model in the terminal

Interactive chat:

    llama-cli -m models/model.gguf

Single prompt, generate up to 128 tokens:

    llama-cli -m models/model.gguf -p "Explain what LLVM IR is." -n 128

With GPU offload and a larger context:

    llama-cli -m models/model.gguf -ngl 99 -c 8192

## llama.cpp: convert a Hugging Face model to GGUF

Install the Python requirements from the llama.cpp repository, then convert:

    pip install -r requirements.txt
    python convert_hf_to_gguf.py path/to/hf-model --outfile model-f16.gguf --outtype f16

## llama-quantize: make a model smaller

    llama-quantize model-f16.gguf model-Q4_K_M.gguf Q4_K_M

Common types, from largest to smallest: `Q8_0`, `Q6_K`, `Q5_K_M`, `Q4_K_M`, `Q3_K_M`, `Q2_K`.
`Q4_K_M` is a common balance of size and quality. Run `llama-quantize --help` to list all types.

## llama-bench: measure speed

    llama-bench -m models/model.gguf

Measure 512-token prompt processing and 128-token generation with full GPU offload:

    llama-bench -m models/model.gguf -p 512 -n 128 -ngl 99

## llama-perplexity: measure quality

    llama-perplexity -m models/model.gguf -f wiki.test.raw

## llama.cpp: troubleshooting

- Output stops or degrades on long conversations: the context is too small. Raise `-c`, and note
  that `--parallel N` splits the context between N slots.
- Tool calling does not work: start `llama-server` with `--jinja`, or supply a template with
  `--chat-template-file`.
- Slow generation on a GPU machine: `-ngl` was not set, so layers run on the CPU.
- CMake cannot find CURL: add `-DLLAMA_CURL=OFF`, or install the libcurl development package.
