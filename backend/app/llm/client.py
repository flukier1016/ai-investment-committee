"""一套 OpenAI-compatible transport，服务固定三类 provider。"""

from __future__ import annotations

import hashlib
import importlib
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from .config import LLMRuntimeConfig
from .providers import ProviderSpec, get_provider_spec


class LLMClientError(RuntimeError):
    """客户端基础设施错误；上层必须统一降级为 abstain。"""


class LLMDependencyError(LLMClientError):
    pass


class LLMProviderConfigurationError(LLMClientError):
    pass


class LLMResponseError(LLMClientError):
    pass


@dataclass(frozen=True, slots=True)
class StructuredCompletion:
    parsed: BaseModel
    raw_output_sha256: str
    tokens_in: int = 0
    tokens_out: int = 0
    response_id: str = ""
    response_model: str = ""
    finish_reason: str = ""


class OpenAICompatibleClient:
    """不追加隐藏 prompt；JSON mode 后只走本地 Pydantic schema 校验。"""

    def __init__(self, sdk_client: Any, runtime_config: LLMRuntimeConfig,
                 provider_spec: ProviderSpec):
        self._sdk_client = sdk_client
        self.runtime_config = runtime_config
        self.provider_spec = provider_spec
        self.provider = provider_spec.provider.value
        self.model = runtime_config.model
        self.temperature = runtime_config.temperature
        self.max_retries = runtime_config.max_retries

    def complete_structured(
        self,
        prompt: str,
        schema: type[BaseModel],
    ) -> StructuredCompletion:
        try:
            response = self._sdk_client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            raise LLMClientError(f"sdk_call_failed:{type(exc).__name__}") from exc

        choices = getattr(response, "choices", None)
        if not isinstance(choices, list) or len(choices) != 1:
            raise LLMResponseError("invalid_choice_count")
        choice = choices[0]
        finish_reason = str(getattr(choice, "finish_reason", "") or "")
        if finish_reason != "stop":
            raise LLMResponseError(f"incomplete:{finish_reason or 'missing'}")
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("empty_content")
        try:
            parsed = schema.model_validate_json(content)
        except (ValidationError, ValueError, TypeError) as exc:
            raise LLMResponseError("schema_validation_failed") from exc

        usage = getattr(response, "usage", None)
        return StructuredCompletion(
            parsed=parsed,
            raw_output_sha256=hashlib.sha256(content.encode()).hexdigest(),
            tokens_in=int(getattr(usage, "prompt_tokens", 0) or 0),
            tokens_out=int(getattr(usage, "completion_tokens", 0) or 0),
            response_id=str(getattr(response, "id", "") or ""),
            response_model=str(getattr(response, "model", "") or ""),
            finish_reason=finish_reason,
        )


def _load_openai_factory() -> Callable[..., Any]:
    try:
        module = importlib.import_module("openai")
        return module.OpenAI
    except (ImportError, AttributeError) as exc:
        raise LLMDependencyError(
            "LLM 可选依赖未安装；请运行 `uv sync --extra llm`"
        ) from exc


def build_client(
    runtime_config: LLMRuntimeConfig,
    *,
    environ: Mapping[str, str] | None = None,
    sdk_factory: Callable[..., Any] | None = None,
) -> OpenAICompatibleClient | None:
    """构建 client；max_retries 原样交给 SDK，不实现外层重试循环。"""
    if not runtime_config.enabled:
        return None
    assert runtime_config.provider is not None
    spec = get_provider_spec(runtime_config.provider)
    env = os.environ if environ is None else environ
    if spec.requires_api_key:
        api_key = (env.get(spec.api_key_env or "") or "").strip()
        if not api_key:
            raise LLMProviderConfigurationError(
                f"缺少 {spec.api_key_env}，无法启用 {spec.provider.value}"
            )
    else:
        api_key = spec.placeholder_api_key or "local"

    factory = sdk_factory or _load_openai_factory()
    try:
        sdk_client = factory(
            api_key=api_key,
            base_url=spec.base_url,
            timeout=runtime_config.timeout_seconds,
            max_retries=runtime_config.max_retries,
        )
    except Exception as exc:
        raise LLMClientError(f"sdk_init_failed:{type(exc).__name__}") from exc
    return OpenAICompatibleClient(sdk_client, runtime_config, spec)


__all__ = [
    "LLMClientError",
    "LLMDependencyError",
    "LLMProviderConfigurationError",
    "LLMResponseError",
    "OpenAICompatibleClient",
    "StructuredCompletion",
    "build_client",
]
