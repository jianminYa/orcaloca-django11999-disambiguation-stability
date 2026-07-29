import os
import time

import config
from llama_index.core.base.llms.types import LLMMetadata, MessageRole
from google.oauth2 import service_account
from llama_index.core.llms.llm import LLM
from llama_index.llms.anthropic import Anthropic
from llama_index.llms.openai import OpenAI
from llama_index.llms.openai.utils import (
    is_chat_model,
    is_function_calling_model,
    openai_modelname_to_contextsize,
)
from llama_index.llms.vertex import Vertex

from .utils import VertexAnthropicWithCredentials


OPENAI_BASE_URL_KEYS = (
    "OPENAI_BASE_URL",
    "BASE_URL",
    "API_BASE_URL",
    "OPENAI_API_BASE",
)


class OpenAICompatible(OpenAI):
    def _with_retry(self, call_name: str, call_func):
        max_retry = int(os.environ.get("ORCAR_LLM_MAX_RETRY", "8"))
        retry_delay = float(os.environ.get("ORCAR_LLM_RETRY_DELAY", "2"))
        retry_delay_max = float(os.environ.get("ORCAR_LLM_RETRY_DELAY_MAX", "60"))
        fatal_markers = (
            "model_not_found",
            "invalid_api_key",
            "unauthorized",
            "permission_denied",
        )
        for attempt in range(1, max_retry + 1):
            try:
                return call_func()
            except Exception as exc:
                message = str(exc)
                if any(marker in message for marker in fatal_markers):
                    raise
                if attempt == max_retry:
                    raise
                delay = min(retry_delay_max, retry_delay * (2 ** (attempt - 1)))
                print(
                    f"OpenAI-compatible {call_name} retry "
                    f"{attempt}/{max_retry} after {type(exc).__name__}; "
                    f"sleeping {delay:.1f}s"
                )
                time.sleep(delay)

    def chat(self, *args, **kwargs):
        parent_chat = super().chat
        return self._with_retry("chat", lambda: parent_chat(*args, **kwargs))

    def complete(self, *args, **kwargs):
        parent_complete = super().complete
        return self._with_retry(
            "complete", lambda: parent_complete(*args, **kwargs)
        )

    @property
    def metadata(self) -> LLMMetadata:
        try:
            context_window = openai_modelname_to_contextsize(self._get_model_name())
            is_known_chat_model = is_chat_model(model=self._get_model_name())
            is_known_function_calling_model = is_function_calling_model(
                model=self._get_model_name()
            )
        except ValueError:
            context_window = 128000
            is_known_chat_model = self._get_model_name().startswith("gpt")
            is_known_function_calling_model = False
        return LLMMetadata(
            context_window=context_window,
            num_output=self.max_tokens or -1,
            is_chat_model=is_known_chat_model,
            is_function_calling_model=is_known_function_calling_model,
            model_name=self.model,
            system_role=MessageRole.SYSTEM,
        )


def _get_openai_api_base(orcar_config: "Config") -> str:
    for key in OPENAI_BASE_URL_KEYS:
        try:
            value = orcar_config[key]
        except KeyError:
            value = ""
        if value:
            return value
    return ""


def _load_key_value_config(file_path: str) -> dict:
    values = {}
    with open(file_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


class Config:
    def __init__(self, file_path=None, provider=None):
        self.file_path = file_path
        if self.file_path and os.path.isfile(self.file_path):
            try:
                self.file_config = config.Config(self.file_path)
            except config.ConfigFormatError:
                self.file_config = _load_key_value_config(self.file_path)
        else:
            self.file_config = dict()
        self.fallback_config = dict()
        self.fallback_config["OPENAI_API_BASE_URL"] = ""
        self.provider = provider

    def __getitem__(self, index):
        # Values in key.cfg has priority over env variables
        if self.file_config.get(index):
            return self.file_config.get(index)
        if index in os.environ:
            return os.environ[index]
        if index in self.fallback_config:
            return self.fallback_config[index]
        raise KeyError(
            f"Cannot find {index} in either cfg file '{self.file_path}' or env variables"
        )


def get_llm(**kwargs) -> LLM:
    # key.cfg is in the parent directory of this file
    orcar_config: Config = kwargs.get("orcar_config", None)
    model = kwargs.get("model", None)
    if model.startswith("claude"):
        # first check if the provider has been set
        if orcar_config.provider == "vertexanthropic":
            print(f"Using AnthropicVertex model: {model}")
            service_account_path = os.path.expanduser(
                orcar_config["VERTEX_SERVICE_ACCOUNT_PATH"]
            )
            if not os.path.exists(service_account_path):
                raise FileNotFoundError(
                    f"Google Cloud Service Account file not found: {service_account_path}"
                )
            try:
                credentials = service_account.Credentials.from_service_account_file(
                    service_account_path,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
                kwargs["credentials"] = credentials
                kwargs["project_id"] = credentials.project_id
                kwargs["region"] = orcar_config["VERTEX_REGION"]
                LLM_func = VertexAnthropicWithCredentials
            except Exception as e:
                raise Exception(f"gen_config: Failed to get vertexanthropic LLM") from e
        else:
            kwargs["api_key"] = orcar_config["ANTHROPIC_API_KEY"]
            LLM_func = Anthropic
    elif model.startswith("gpt"):
        kwargs["api_key"] = orcar_config["OPENAI_API_KEY"]
        api_base = _get_openai_api_base(orcar_config)
        if api_base:
            kwargs["api_base"] = api_base
        LLM_func = OpenAICompatible
    elif model.startswith("gemini"):
        # Load Google Cloud credentials
        service_account_path = orcar_config["VERTEX_SERVICE_ACCOUNT_PATH"]

        if not os.path.exists(service_account_path):
            raise FileNotFoundError(
                f"Google Cloud Service Account file not found: {service_account_path}"
            )

        credentials = service_account.Credentials.from_service_account_file(
            service_account_path
        )

        kwargs["project"] = credentials.project_id
        kwargs["credentials"] = credentials
        LLM_func = Vertex

    # delete orcar_config from kwargs
    if "orcar_config" in kwargs:
        del kwargs["orcar_config"]

    try:
        llm: LLM = LLM_func(**kwargs)
        _ = llm.complete("Say 'Hi'")
        return llm
    except Exception as e:
        raise Exception(f"Failed to initialize LLM: {e}")
