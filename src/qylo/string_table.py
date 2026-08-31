# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2025.12.15
# String table
#
# Purpose:
# Centralized stringtable for user-facing and error strings.
#
# Sections follow the module that uses each string, in request-flow order.
#

# from future means allow forward references in type hints
from __future__ import annotations

# --- settings.py ---

# positive_int_from_env()
MSG_INVALID_INT_ENV = "{name} must be a positive whole number, got: {value}"

# --- documents.py ---

# scan_document_paths()
MSG_DOCUMENT_PATH_NOT_FOUND = "Document path not found: {path}"
MSG_NO_SUPPORTED_DOCUMENTS = "No supported documents found in {path} ({extensions})"

# load_document()
MSG_UNSUPPORTED_DOCUMENT_TYPE = "Unsupported document type: {path}"

# split_documents()
ENV_CHUNK_SIZE = "CHATBOT_CHUNK_SIZE"
ENV_CHUNK_OVERLAP = "CHATBOT_CHUNK_OVERLAP"
MSG_CHUNK_OVERLAP_TOO_LARGE = (
    "{overlap_name} ({overlap}) must be smaller than {size_name} ({size}). "
    "Overlap is how much text adjacent chunks share, so it cannot be as large "
    "as a chunk itself."
)

# --- retrieval.py ---

# build_retrieval_tool() -> retrieve_document_context()
MSG_NO_RELEVANT_CONTEXT = "No relevant context found in the knowledge base."

# format_retrieval_results() - model-facing text, pinned by tests/test_model_facing_text.py
MSG_RETRIEVAL_RESULT_HEADER = "[{index}] Source: {citation}"
MSG_RETRIEVAL_SAFETY_SUFFIX = " (Safety: {safety})"
MSG_RETRIEVAL_RESULT_BODY = "\n{content}"

# --- model_provider.py ---

# get_model_provider()
ENV_MODEL_PROVIDER = "CHATBOT_MODEL_PROVIDER"
MSG_UNSUPPORTED_PROVIDER_ENV = (
    "Unsupported {env_name} value: {raw_provider}. Use one of: {valid_values}."
)

# build_chat_model() (dead-code fallback path - ModelProvider is exhaustive)
MSG_UNSUPPORTED_PROVIDER = "Unsupported model provider: {provider}"

# build_azure_chat_model()
ENV_AZURE_ENDPOINT = "AZURE_OPENAI_ENDPOINT"
ENV_AZURE_API_KEY = "AZURE_OPENAI_API_KEY"
ENV_AZURE_CHAT_DEPLOYMENT = "AZURE_OPENAI_CHAT_DEPLOYMENT"
ENV_AZURE_API_VERSION = "AZURE_OPENAI_API_VERSION"
MSG_AZURE_ENDPOINT_FORMAT = (
    "AZURE_OPENAI_ENDPOINT should be the Azure OpenAI resource root, "
    "for example https://my-resource.openai.azure.com/. Remove '/openai/v1' "
    "from the endpoint when using AzureChatOpenAI."
)

# build_local_chat_model()
ENV_LOCAL_BASE_URL = "LOCAL_OPENAI_BASE_URL"
ENV_LOCAL_MODEL_NAME = "LOCAL_MODEL_NAME"
ENV_LOCAL_API_KEY = "LOCAL_OPENAI_API_KEY"
LOCAL_API_KEY_DEFAULT = "local-not-used"

# env_required()
MSG_MISSING_ENV_VAR = "Missing required environment variable: {name}"

# --- assistant.py ---

# RagAssistant.answer() — GraphRecursionError guard
MSG_AGENT_STEP_LIMIT_EXCEEDED = (
    "The agent didn't converge on an answer within {limit} steps (it kept searching the "
    "knowledge base without producing a final answer) and was stopped before running away "
    "further. Try rephrasing the question, or narrowing --documents/--doc to a smaller set."
)

# --- response_contract.py ---

# ContractResponse._validate_command_matches_kind()
MSG_CONTRACT_COMMAND_REQUIRED = (
    "kind={kind!r} requires a non-empty command field with the actual "
    "command text. If this wasn't really a command request, reclassify as "
    "ANS or GENERAL instead."
)
MSG_CONTRACT_COMMAND_FORBIDDEN = (
    "kind={kind!r} must not set command. If this is actually a command "
    "request, reclassify as CMD or UNSAFE instead."
)

# --- console.py ---

# print_stage() tags
TAG_INGESTION = "[ingestion]"
TAG_EMBEDDING = "[embedding]"
TAG_MODEL_CALL = "[call model]"
TAG_LOCAL = "[local]"
TAG_CLOUD = "[cloud]"

# print_model_response()
MSG_NOT_GROUNDED = "(not grounded in the knowledge base)"
LABEL_COMMAND = "Command:"
LABEL_UNSAFE_REQUEST = "Unsafe command request:"
MSG_UNSAFE_DEFAULT_REASON = "The model marked this command as unsafe."
LABEL_PROPOSED_COMMAND = "Proposed command:"

# --- execution.py ---

# run_command()
MSG_EXECUTING_COMMAND = "Executing command: {command}"
MSG_COMMAND_EXIT_CODE = "Command exited with code {code}."

# apply_exe_request()
MSG_NO_COMMAND_PROVIDED = "No executable command was provided. Nothing was run."
MSG_GENERAL_NOT_RUN = "General-knowledge answer (not grounded). Nothing was run."
MSG_CMD_NO_TEXT = "The model returned CMD but no command text. Nothing was run."
MSG_UNSAFE_NO_COMMAND = "The model marked this unsafe but did not provide a command. Nothing was run."
MSG_UNSAFE_BLOCKED = "Unsafe command blocked. Re-run with --exe --yolo to execute it."

# --- cli.py ---

# main()
ENV_EXECUTE_COMMANDS = "CHATBOT_EXECUTE_COMMANDS"
MSG_CONNECTING = "Connecting to {provider} chat model..."
MSG_THINKING = "Thinking (the agent may search the knowledge base)..."

# build_assistant()
MSG_SCANNING = "Scanning {path}..."
MSG_FOUND_DOCUMENTS = "Found {count} supported document(s)."
MSG_LOADING_DOCUMENTS = "Loading documents..."
MSG_LOADED_DOCUMENTS = "Loaded {count} document part(s)."
MSG_SPLITTING_DOCUMENTS = "Splitting documents into chunks..."
MSG_SPLIT_DOCUMENTS = "Split documents into {count} chunk(s)."
MSG_LOADING_EMBEDDING_MODEL = "Loading embedding model..."
MSG_BUILDING_VECTOR_STORE = "Building the in-memory vector store..."
MSG_VECTOR_STORE_READY = "Vector store ready with {count} searchable chunk(s)."

# parse_args()
CLI_DESCRIPTION = "Ask a question against local documentation using grounded RAG."
HELP_QUESTION = "Question to answer from the knowledge base."
HELP_DOCUMENTS = "Document file or folder to scan. Defaults to {default_path}."
HELP_DOC = "Load one documentation file instead of scanning the documents folder."
HELP_RETRIEVAL_K = "Number of retrieved chunks to provide to the model. Defaults to 4."
HELP_EXE = (
    "Execute a CMD response. UNSAFE responses also require --yolo. "
    "Setting CHATBOT_EXECUTE_COMMANDS=true in .env does the same thing for every "
    "run, without the flag."
)
HELP_YOLO = "Allow execution of an UNSAFE command when used with --exe."
HELP_SYSTEM_PROMPT = "Custom system prompt file to use instead of the bundled default."
