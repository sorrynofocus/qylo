# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2026.07.30
# Model provider enables configuration to use a local or cloud AI model.
#
# Purpose:
# Stage 4 of the request flow, and the one abstraction boundary between
# assistant.py and whichever chat backend is configured. cli.py asks for a model
# and assistant.py gets back a BaseChatModel it can .invoke() - neither learns
# whether that model lives in Azure or in a llama.cpp server on localhost. A new
# backend means a new build_*_chat_model() here, not a change to the RAG code.
#
# Which backend is chosen comes from CHATBOT_MODEL_PROVIDER in .env rather than
# a command-line switch, so a run stays reproducible from configuration alone.
# Everything a backend needs is read here from the environment, so credentials
# never travel through function arguments or the cli.
#
# Usage examples (see README for granular details):
#
# .env for Azure:
# CHATBOT_MODEL_PROVIDER=azure
# AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/   <- root only, no /openai/v1
# AZURE_OPENAI_API_KEY=<key>
# AZURE_OPENAI_CHAT_DEPLOYMENT=<deployment-name>
# AZURE_OPENAI_API_VERSION=2024-12-01-preview
#
# .env for a local llama.cpp server:
# CHATBOT_MODEL_PROVIDER=local
# LOCAL_OPENAI_BASE_URL=http://localhost:8080/v1
# LOCAL_MODEL_NAME=qwen3.5-9b
#
# From code:
# model = build_chat_model()
#

from __future__ import annotations

import os
from enum import Enum

from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from pydantic import SecretStr

from qylo import string_table


class ModelProvider(Enum):
    """
    Configured source for the chat model.

    Values:
        AZURE: Use an Azure OpenAI deployment such as gpt-5-nano.
        LOCAL: Use a local OpenAI-compatible server such as llama.cpp.

    The provider is selected from CHATBOT_MODEL_PROVIDER in .env. Keeping this
    in configuration avoids adding one-off command-line switches and makes the
    runtime choice easy to reproduce.
    """

    AZURE = "azure"
    LOCAL = "local"
    OPENAI = "openai" # not tested!
    CUSTOM = "custom" # not tested!



def build_chat_model() -> BaseChatModel:
    """
    Build the configured chat model.

    Returns:
        A LangChain chat model. RagAssistant can call .invoke(messages) on this
        object without knowing whether the model is hosted in Azure or running
        locally through llama.cpp.
    """

    load_dotenv()
    provider = get_model_provider()

    if provider is ModelProvider.AZURE:
        return build_azure_chat_model()

    if provider is ModelProvider.LOCAL:
        return build_local_chat_model()

    # if provider is ModelProvider.OPENAI:
    #     return build_openai_chat_model()
    #
    # if provider is ModelProvider.CUSTOM:
    #     return build_custom_chat_model()

    raise ValueError(string_table.MSG_UNSUPPORTED_PROVIDER.format(provider=provider))


def get_model_provider() -> ModelProvider:
    """
    Read CHATBOT_MODEL_PROVIDER and convert it to a ModelProvider enum.
    """

    raw_provider = os.getenv(string_table.ENV_MODEL_PROVIDER, ModelProvider.AZURE.value)
    friendly_name_provider = raw_provider.strip().lower()

    for provider in ModelProvider:
        if friendly_name_provider == provider.value:
            return provider

    valid_values = ", ".join(provider.value for provider in ModelProvider)

    raise RuntimeError(
        string_table.MSG_UNSUPPORTED_PROVIDER_ENV.format(
            env_name=string_table.ENV_MODEL_PROVIDER,
            raw_provider=raw_provider,
            valid_values=valid_values,
        )
    )


def build_azure_chat_model() -> AzureChatOpenAI:
    """
    Build an Azure OpenAI chat model from .env settings.

    Required .env values:
        AZURE_OPENAI_ENDPOINT
        AZURE_OPENAI_API_KEY
        AZURE_OPENAI_CHAT_DEPLOYMENT
        AZURE_OPENAI_API_VERSION
    """

    endpoint = env_required(string_table.ENV_AZURE_ENDPOINT)
    env_required(string_table.ENV_AZURE_API_KEY)
    deployment = env_required(string_table.ENV_AZURE_CHAT_DEPLOYMENT)
    api_version = env_required(string_table.ENV_AZURE_API_VERSION)

    if "/openai/" in endpoint.rstrip("/"):
        raise RuntimeError(string_table.MSG_AZURE_ENDPOINT_FORMAT)

    return AzureChatOpenAI(
        azure_deployment=deployment,
        api_version=api_version,
        max_retries=2,
    )


def build_local_chat_model() -> ChatOpenAI:
    """
    Build a local OpenAI-compatible chat model.

    This is intended for llama.cpp server mode. Example server:
        llama-server -m D:\\Models\\model.gguf -c 4096 -ngl 99

    Required .env values:
        LOCAL_OPENAI_BASE_URL
        LOCAL_MODEL_NAME

    Optional .env value:
        LOCAL_OPENAI_API_KEY

    llama.cpp usually ignores the API key, but the OpenAI client expects a
    value, so the default is "local-not-used".
    """

    base_url = env_required(string_table.ENV_LOCAL_BASE_URL)
    model_name = env_required(string_table.ENV_LOCAL_MODEL_NAME)
    api_key = os.getenv(string_table.ENV_LOCAL_API_KEY, string_table.LOCAL_API_KEY_DEFAULT)

    return ChatOpenAI(
        base_url=base_url,
        # SecretStr rather than the plain str env_required/os.getenv hands back.
        # The field is declared SecretStr | None | Callable[[], str] |
        # Callable[[], Awaitable[str]]; Pydantic coerces a str to SecretStr
        # during validation, so both spellings are byte-identical by the time
        # the OpenAI client sees the key. Wrapping it here just states the
        # declared type instead of leaning on that coercion.
        api_key=SecretStr(api_key),
        model=model_name,
        max_retries=2,
    )


def env_required(name: str) -> str:
    """
    Read a required environment variable or fail with a clear message.
    """

    value = os.getenv(name)

    if not value:
        raise RuntimeError(string_table.MSG_MISSING_ENV_VAR.format(name=name))

    return value
