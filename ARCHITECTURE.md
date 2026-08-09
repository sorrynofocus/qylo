# Architecture and how this works

This project is a local, agentic RAG CLI assistant for querying internal CLI-tool documentation and, via a safety contract, turning grounded answers into runnable commands. This doc explains the concepts behind the design and how one invocation actually flows end to end -for future-you- and for anyone else who needs to understand it without re-deriving it from the code.

TL;DR for what it supports:

- Azure Foundry and models (this project uses gpt-5-nano and the intention is for quick deployments of cloud-based models)
- Local LLMs (this project was widely intended to support local LLMs to deploy on a as-needed basis. I've always wanted to supply a tool-based system to generate commands from unstructured data, or execute them). I chose qwen3.5-9b as it is a good balance of speed and quality for my needs.
- configuration style `.env` file for easy deployment and configuration
- A model deployer using BiCep for cloud based Azure models. (see infra/azure/README.md)
- Answer/Response system to generate answers from unstructured data, and generate commands from those answers. If the queries were not grounded in the unstructured data, the system will treat it as a general query and answer from what the model already knows from pretraining -labeled `GENERAL` so you can see it wasn't grounded.
- Embeddings are done in-memory.
- CPU friendly embedding model, but can support GPU
- Designed with LLama.cpp in mind. Ollama, could work, but I have not tested it. Llama.cpp is great and have more control.

## Concepts

### Why embeddings, not just "send everything to the model"?!?

The chat model never touches the embedding model directly. Embedding happens *before* the chat call, as a separate local step:

```
User query
  ↓
Scan documents 
  ↓
Load documents
  ↓
Split into chunks
  ↓
Embedding model converts each chunk into a vector (once, per run)
  ↓
Embedding model converts the user query into a vector
  ↓
Vector store finds chunks closest to the query vector
  ↓
Only those chunks are made available to the model
```

An embedding is a numeric representation of meaning. Semantically similar text ends up closer together in vector space, so "What is this document about?" lands near overview/intro chunks even if the document never uses that exact phrase.

You _could_ skip embeddings entirely and just send whole documents to the model. For one small file that's often fine, maybe even faster. Embeddings start earning their keep once you have many documents, documents too large to fit in context, a need for per-chunk citations, or (the actual goal here) grounded CLI-command generation across a whole folder of tool docs. The alternative to embeddings is keyword/full-text search, which is fast but brittle. 

A question like "How do I list turbo models in westus?" only keyword-matches "turbo"/"westus," while embedding search also surfaces chunks about model listing, location filters, and output formats that never use those literal words.

I have _failed_ with previous projects because the complexities in _trying_ to get it to work loading all docs first, then trying to perform simple BM25 search. Even my STT project was a bit complex using BM25 search and tried to _improve_ the search inside.

I chose to do this because I stumbled on another naive rag project using langchain and embeddings. This piqued my interest. Using embeddings was a large  interesting topic. I looked into the automatic things Azure can do, but I wanted to see it work myself. Largely, I wanted to create a small system I can deploy using a small model, embeddings, and create an answer/response tool based on unstructured data.

### Naive RAG → Agentic RAG

This project started as **naive RAG** (retrieve-then-read): always fetch the top-`k` chunks (a shortlist of the chunks scoring closest to the query) up front and stuff them into the prompt, whether or not they're actually relevant to the question. It has since evolved into **agentic RAG**: the model is handed a `retrieve_document_context` tool (`rag.py::build_retrieval_tool`) inside a `langchain.agents.create_agent` tool-calling loop, and decides for itself whether to search at all, and whether to refine the query and search again, before writing a final answer. See "Application workflow" below for the exact call sequence.

Naming this matters because it's a spectrum, not just two options:

```
Dense retrieval RAG / Retrieve-then-read RAG / Semantic search RAG   → naive RAG (where this started)
Agentic RAG (model chooses tools/search steps)                       → where this is now
Persistent RAG (Chroma/FAISS/LanceDB instead of rebuilding each run) → not done yet, planning! See below
Hybrid RAG (keyword + vector search) / Reranked RAG                  → not needed at current scale
```

### Chunking and top `-k`

Documents are split with `RecursiveCharacterTextSplitter` using a default chunk size of 1000 characters and a default overlap of 200 (`DEFAULT_CHUNK_SIZE`/`DEFAULT_CHUNK_OVERLAP`, `rag.py`). Those are defaults, not fixed constants: `split_documents()` takes both as optional keyword arguments and, when they're left as `None` (which is what `cli.py` does), resolves `CHATBOT_CHUNK_SIZE`/`CHATBOT_CHUNK_OVERLAP` from `.env` via `etoi()` (an `atoi`-style env-string-to-int reader for all you C lovers out there!) before falling back to the defaults -so chunking can be tuned per-machine without touching code, while an explicit argument still wins over `.env`. A non-integer, zero, or negative value raises rather than silently reverting to the default, and an overlap that isn't smaller than the chunk size raises a message naming both variables. 

The retrieval tool then asks the vector store for the `k` nearest chunks per call (`-k`, default 4). There's no hard universal max for `k`, but as a rule of thumb: 1 is a floor, 3–10 is normal, 10–25 is "large-doc experiment" territory. Pushing `k` far beyond that floods the prompt, raises cost/latency, and tends to confuse rather than help the answer. For very large corpora the fix is better chunking, metadata filters, or reranking after retrieval, not just a bigger `k`. For this prototype, I chose a small default `k` (4) due to my small corpus of CLI docs and relative small prompts. 

### There are challenges: Time. Where does it go?

Per invocation, roughly in order: 

Python/`uv` startup  
    ↓
importing LangChain/Torch/sentence-transformers 
    ↓
loading `.env` and building the chat client
    ↓
scanning/loading/splitting documents
    ↓
loading embedding-model weights 
    ↓
embedding all chunks
    ↓
building the in-memory vector store
    ↓
the agent loop itself (embedding the query, similarity search, one or more model calls ).
    ↓
Determine final answer/response (command or query) and print it.


For a handful of small markdown files, the expensive parts are import startup, the embedding model load, and the model call(s); scanning/loading/splitting is close to free by comparison. The friendly status (thanks!) like "`Loading weights: 100%|...`" line that appears on every run is the *local* HuggingFace embedding model initializing, not the chat model. From the workflow, you'll notice it's a fresh process every invocation, so weights load into RAM every time even though the files are cached on disk.

### Why in-memory, not persistent, vector store?

This is my first project that I feel _great_ about! I've got to get it working first! 

Every run repeats `load docs → split → embed chunks → build vector store` from scratch. There's no caching of embeddings across invocations and that's the deliberate current tradeoff (simplicity, zero moving parts, nothing to go stale), not an oversight. A persistent store (Chroma, FAISS) would let embeddings survive between runs and cut startup time substantially after the first index. This is worth revisiting if per-invocation latency becomes the actual bottleneck (planning to test: repeated CI/CD calls), but explicitly out of scope for now. Since I use OpenWebUI, I witnessed they use Chroma for their persistence. I have to get to know it better, as well. 


### Why `sentence-transformers/all-MiniLM-L6-v2`

The project that I stumbled on -and influenced me- was a simple one. I noticed they used this. I've been trying to get a simple embedding on my other failed projects, but they ended up bloated. 

I begin to _hallucinate_! 

I'd do Azure, but I wanted to see for myself. Azure's cloud based embedding models are great. I actually wanted to download and play with it. 

A practical starter embedding model, not the best possible one: ~90MB download, fast and CPU-friendly, 384-dimensional vectors (modest memory), decent semantic search quality, widely used. Better options exist _if_ quality ever becomes the bottleneck (`BAAI/bge-small-en-v1.5`, `BAAI/bge-base-en-v1.5`, `sentence-transformers/all-mpnet-base-v2`)... Definitely worth benchmarking against MiniLM specifically on CLI-command docs if retrieval quality is ever suspect.

### Structured output, and why there's still a text fallback

This is the one dependency that isn't a library. It's an API *capability*, and it's the piece I'd worry about first if something ever goes strange.

The `ANS`/`GENERAL`/`CMD`/`UNSAFE` label is what decides whether anything is allowed to run. That makes getting the *label* right more important than getting the *prose* right -a beautifully worded answer with the wrong label is a worse outcome than an awkward answer with the right one. So `RagAssistant.__init__` doesn't trust the model to type the label correctly as free text. It passes `response_format=ToolStrategy(schema=ContractResponse)` to `create_agent`, which forces the final answer through a Pydantic schema the API itself validates.

That only works if the backend actually supports structured outputs, and support is uneven:

- **Azure OpenAI** supports it, but it's gated on the *API version*, not the model. Structured outputs arrived in `2024-08-01-preview`. That's the real reason `AZURE_OPENAI_API_VERSION` is pinned in `.env` instead of left to whatever default happens to be current -point it at something older and the reliable path quietly stops being available. Nothing errors. You just start getting worse labels.
- **Local llama.cpp** depends on the GGUF chat template baked into the model file, not on llama.cpp itself. Swap models and this can change under you. Measured 90% (18/20) on a sample batch, against 10/10 for Azure after a schema rewrite.

Which is why `parse_model_response()` is still in `response_contract.py`. It is not legacy and it is not dead code -it's the fallback for backends that don't reliably honor a forced structured response, and local isn't proven enough yet to drop it. Both paths land on the same `ModelResponse`, so `cli.py` never has to know which one ran.

The measured numbers behind all of this are in `TROUBLESHOOT.MD`.

### AI-usage telemetry: two instrumentation layers, one call type

`--usage`/`--usagelog` (`cli.py`) are opt-in observability, not an optimization. I wanted to sniff out what's being used. This was very hard to put in and Claude Code helped immensely in this area. I'm not a good monitoring person. Like Kubernetes, it's a weakness of mine. 

The telemetry measure calls, bytes, tokens, and retries without changing what the pipeline does. When `--usage` isn't passed, `cli.py::main()` never builds a `TelemetrySession`, `build_chat_model(telemetry=None)` never builds a custom `httpx.Client`, and `RagAssistant.__init__` never attaches a callback handler. Every code path is identical to before telemetry existed.

`src/qna_chatbot/telemetry.py` feeds one `TelemetrySession` from two independent instrumentation layers, because neither alone tells the whole story:

- **`TelemetryCallbackHandler`** (a `langchain_core.callbacks.BaseCallbackHandler`) hooks the *logical* call boundary: `on_chat_model_start`/`on_llm_end` bracket one `MODEL_CALL` event per round-trip through the agent's tool-calling loop, and `on_tool_start`/`on_tool_end` record one `RETRIEVAL` event per `retrieve_document_context` call. `RagAssistant.answer()` attaches it via `config={"callbacks": [...]}` on `agent.invoke()`. This layer sees provider-reported `usage_metadata` (actual input/output/total tokens) when the provider returns it.
- **`httpx_event_hooks(session)`** hooks the actual wire requests/responses, wired into `AzureChatOpenAI`/`ChatOpenAI` via `http_client=httpx.Client(event_hooks=...)` (`model_provider.py::_telemetry_http_client`, called from `build_azure_chat_model`/`build_local_chat_model`). This is the only layer that sees true wire-level bytes and silent retries: both chat-model builders already set `max_retries=2`, and LangChain's callback boundary fires exactly once per logical `.invoke()` no matter how many HTTP attempts the OpenAI SDK made underneath -- a retry is invisible to `TelemetryCallbackHandler` alone.

**Correlation mechanism.** `RagAssistant.answer()` is synchronous, so a model call's `on_chat_model_start`/`on_llm_end` pair always brackets its own httpx request(s) in the same call stack. `TelemetrySession` exploits this with a "currently open call" slot (`open_call`/`close_call`/`open_call_event`): `on_chat_model_start` opens it with a freshly-built `TelemetryEvent`, the httpx hooks read `open_call_event` to add wire bytes and bump `http_requests` onto that same event, and `on_llm_end` closes it after filling in duration and `usage_metadata`. No request ID matching is needed because there's only ever one call open at a time.

**One call type, not two.** It would be tempting to report separate "classification" and "final answer" call types, but that distinction doesn't exist at the network level in this codebase... the system prompt asks the model to classify intent *and* produce the final `ANS`/`GENERAL`/`CMD`/`UNSAFE`-shaped answer in whichever iteration of the tool-calling loop turns out to be its last, and every iteration before that is the same kind of chat-completion request, just with a tool result appended to the message history. So the taxonomy telemetry actually reports is one call type, `model_call`, distinguished per-invocation by an ordinal `sequence` and a `final` flag (`true` = this call produced the final answer, `false` = it requested a tool). One user question therefore produces exactly 1 model call if the model answers directly, or 2+ if it calls `retrieve_document_context` first. And, because each additional call resends the whole growing message history, a 2-call turn sends the system prompt bytes twice, not once.

**Local pipeline stages.** `measure(session, stage)` is a context manager used directly in `cli.py::main()` around the ingestion stage (scan+load+split) and the embedding stage (build_embeddings+build_vectors) -the two stages that are local and always free regardless of provider. It yields a mutable `_StageMetrics` the caller fills in (`payload_bytes`/`content_for_hash`/`preview_text`) during the `with` block, and no-ops cleanly when `session is None`, so call sites don't need a separate `if telemetry:` branch around the wrapped work.

**Redaction.** `sha256_short()` (first 12 hex chars of a sha256 digest) and `redact_preview()` (whitespace-collapsed, truncated to 80 chars) keep raw document/system-prompt content out of both the printed summary and the `--usagelog` JSON-lines file. Every event carries a hash and a short preview, never the underlying text.

That guarantee is enforced, not just intended: `preview` is built from the human turn alone. The full concatenated message text (system prompt + retrieved chunks) still feeds the token estimate and the content hash, but it can't reach `preview` -a call with no human turn, or an empty question, produces an empty preview rather than falling back to that text. It didn't always work that way. See `TROUBLESHOOT.MD`, "Telemetry preview can fall back to system-prompt text" (2026-08-05), for the version that could have leaked and why an empty preview is the better failure.

### Centralized strings (`string_table.py`)

Every user-facing and error string used by `cli.py`, `rag.py`, `model_provider.py`, `telemetry.py`, and `response_contract.py` is a named constant in `string_table.py`, grouped by the module that uses it (`# --- rag.py ---`, etc. to provide mapping), not an inline literal. This exists so strings can be revised, localized, or audited in one place instead of hunted across five files. When adding or changing a message, add or edit the constant there and import it, don't inline a new literal.

String tables are quite important and most don't use it. I did in my early career because of enterprise application development (mostly for localization). I'm trying my best to do more of it these days. String sprinkling is a bad practice. 

## Current scope / non-goals

Deliberately deferred, not oversights. Remember, I had to get it working first: 

- CI/CD pipeline wiring: a first GitHub Actions workflow exists (`.github/workflows/docker.yml`) but is unverified until the repo is pushed. Prod testing is still deferred.
- Vector-store persistence across invocations (Chroma looks promising)
- Pinning one "recommended" local LLM (I need to try a few models, including less quality ones)
- Command execution (`cli.py::run_command`) has no allowlist/deny-list/audit logging yet... a known, intentional gap, not something to silently patch.
- Better CLI parsing (I always use Click)
- Better printing (Rich is a great option)
- Instead of a single .env file, I may write an .INI or JSON config file for multiple profiles (local/cloud)

## Application workflow (current)

One CLI invocation: beginning -> exit. 

This is agentic RAG, not naive RAG: retrieval is no longer a fixed step (it was in the infancy of this project). It's a tool the agent calls zero or more times, on its own judgment, inside the loop `langchain.agents.create_agent` builds.

```mermaid
flowchart TD
    A["main() — cli.py"] --> B["parse_args() — cli.py"]
    B --> C["get_model_provider() — model_provider.py\n(printed; called again later before build_chat_model)"]
    C --> D["scan_document_paths(source_path) — rag.py"]
    D --> E["load_documents(paths) → load_document(path) per file — rag.py"]
    E --> F["split_documents(docs) — rag.py\n(chunk size/overlap from .env or defaults)"]
    F --> G["build_embeddings() — rag.py\n(HuggingFaceEmbeddings, all-MiniLM-L6-v2)"]
    G --> H["build_vectors(chunks, embeddings) — rag.py\n(InMemoryVectorStore, rebuilt every run)"]
    H --> I["build_chat_model() — model_provider.py"]
    I --> I1["build_azure_chat_model() or build_local_chat_model()\n(+ env_required() for missing .env values)\n(optional: httpx_event_hooks wired in when --usage)"]
    I1 --> J["RagAssistant(vector_store, model, retrieval_k) — rag.py\n__init__ builds build_retrieval_tool() + create_agent(...)\n(optional: TelemetryCallbackHandler attached when --usage)"]
    J --> K["assistant.answer(question)\nagent.invoke({messages: [question]}, config)\n(config carries callbacks=[...] only when --usage)"]
    K --> K1{"agent node: does the model\nwant to call a tool?"}
    K1 -- "tool_calls present" --> K2["retrieve_document_context(query) — rag.py\nvector_store.similarity_search() → context_from_document() per chunk"]
    K2 --> K3["ToolMessage appended → agent node runs again\n(may loop; model can refine the query)"]
    K3 --> K1
    K1 -- "no more tool_calls" --> L["final agent result\n(result[\"structured_response\"], result[\"messages\"])"]
    L --> M{"structured_response populated?\n(ContractResponse via ToolStrategy — rag.py __init__)"}
    M -- "yes" --> M2["contract_response_to_model_response() — response_contract.py"]
    M -- "no (None)" --> M1["parse_model_response(raw AIMessage) — response_contract.py\ntext_after_label() / parse_unsafe_body() fallback"]
    M2 --> M3
    M1 --> M3
    M3["deterministic Safety: unsafe override — RagAssistant.answer() (rag.py)\nCMD → UNSAFE if a retrieved ToolMessage contains \"(Safety: unsafe)\""]
    M3 --> N["print_model_response(response) — cli.py"]
    N --> O{--exe or CHATBOT_EXECUTE_COMMANDS=true?}
    O -- no --> P(["process exit 0"])
    O -- yes --> Q["apply_exe_request(response, yolo) — cli.py"]
    Q --> Q1{"response.kind\n(match/case statement)"}
    Q1 -- "ANS or GENERAL" --> Q2["print 'Nothing was run.' — never executes"]
    Q1 -- "CMD" --> Q3["run_command(command) — subprocess.run(shell=True)"]
    Q1 -- "UNSAFE, --yolo given" --> Q3
    Q1 -- "UNSAFE, no --yolo" --> Q4["print 'blocked' message — never executes"]
    Q2 --> P
    Q3 --> P
    Q4 --> P
```

Plain-text version of the same path, if Mermaid chart doesn't render:

1. `main()` parses args, then calls `load_dotenv()` before anything reads an env var — so `.env` values (`CHATBOT_MODEL_PROVIDER`, `CHATBOT_EXECUTE_COMMANDS`, the `CHATBOT_CHUNK_*` settings) are visible to everything downstream, not just to `build_chat_model()`, which calls it again harmlessly later. It then eagerly announces the chat provider (`get_model_provider()`) before the slow imports.
2. Lazy-imports `rag.py` (keeps `--help` fast), then runs the ingestion pipeline: `scan_document_paths` → `load_documents`/`load_document` → `split_documents` → `build_embeddings` → `build_vectors`. When `--usage` was passed, `main()` wraps the ingestion and embedding stages in `telemetry.measure()` (`telemetry.py`), an optional, no-op-when-off context manager that records local stage bytes/duration — see [AI-usage telemetry](#ai-usage-telemetry-two-instrumentation-layers-one-call-type) below.
3. Builds the chat model (`build_chat_model` → `build_azure_chat_model`/`build_local_chat_model`, reading `.env` via `env_required`), then constructs `RagAssistant` directly (plain constructor — no factory classmethods). `RagAssistant.__init__` builds a `retrieve_document_context` tool bound to that instance's vector store/`retrieval_k` (`build_retrieval_tool()`) and compiles a `create_agent(model, [tool], system_prompt=...)` graph. Both steps optionally take a `TelemetrySession` (`telemetry=` parameter) when `--usage` was passed — `build_chat_model` wires wire-level `httpx_event_hooks` into the model's `http_client`, and `RagAssistant.__init__` builds a `TelemetryCallbackHandler`; omitting `--usage` leaves both `None` and every code path unchanged from before telemetry existed.
4. `assistant.answer(question)` invokes the agent with just the plain question — no pre-fetched context — passing `config={"callbacks": [...]}` only when a `TelemetryCallbackHandler` was built. Internally, the agent node calls the model; if it responds with `tool_calls`, the graph calls `retrieve_document_context` (which runs `vector_store.similarity_search()` + `context_from_document()` per chunk, or returns a "no relevant context found" sentinel), appends the result as a `ToolMessage`, and calls the model again. This repeats until the model stops requesting tools.
5. `RagAssistant.answer()` checks `result.get("structured_response")` first — the agent was built with `response_format=ToolStrategy(schema=ContractResponse)` (`rag.py::__init__`), so a backend that honors the forced structured output returns a validated `ContractResponse` (`kind`/`content`/`command`, `response_contract.py`) directly. If populated, `contract_response_to_model_response()` converts it into a `ModelResponse`. If it's `None` (structured output wasn't produced this call), `answer()` falls back to the original text-parsing path: the final `AIMessage`'s content, still expected to carry an `ANS:`/`GENERAL:`/`CMD:`/`UNSAFE:` label, is passed to `parse_model_response()` (`text_after_label()`/`parse_unsafe_body()` internally). This fallback is deliberately kept, not scheduled for removal — see `TROUBLESHOOT.MD` for why.
6. Before returning, `answer()` applies one deterministic override: if the resolved `kind` is `CMD` and any message in `result["messages"]` (i.e. a `ToolMessage` from `retrieve_document_context`) contains the literal substring `"(Safety: unsafe)"`, `answer()` force-upgrades `kind` to `UNSAFE` — regardless of what the model itself concluded. This closes a specific, measured gap where model judgment alone wasn't reliable at that boundary; see `TROUBLESHOOT.MD` for the numbers.
7. `answer()` returns the resulting `ModelResponse` to `cli.py::main()`, which passes it straight to `print_model_response()` — `main()` no longer calls `parse_model_response()` itself. If `--exe`/`CHATBOT_EXECUTE_COMMANDS` was set, `apply_exe_request()` applies the execution rules with a `match` on `response.kind` (`ANS`/`GENERAL` never run anything; `CMD` runs with `--exe`; `UNSAFE` runs only with `--exe --yolo`) via `run_command()` → `subprocess.run(shell=True)`.
8. Process exits 0 after `main()` returns (unhandled exceptions — bad path, missing `.env` value, Azure/local API errors — propagate as a non-zero exit with a traceback; there's no top-level catch-all yet).

