"""服务端可信 LLM 运行配置与有效配置指纹。

该配置不属于公开 API 的 AllocationConfig，避免匿名请求借服务器密钥触发计费，
也不允许调用方覆盖固定 endpoint。只有非秘密运行身份进入决策配置指纹。
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Mapping

from pydantic import BaseModel, Field, field_validator, model_validator

from .providers import LLMProvider, get_provider_spec


DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT_SECONDS = 30.0


class LLMRuntimeConfig(BaseModel):
    model_config = {"extra": "forbid", "frozen": True, "validate_default": True}

    provider: LLMProvider | None = None
    model: str = Field(default="", max_length=200)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_retries: int = Field(default=DEFAULT_MAX_RETRIES, ge=0, le=10)
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, gt=0, le=120)

    @field_validator("model", mode="before")
    @classmethod
    def _normalize_model(cls, value: object) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("LLM model 必须是字符串")
        return value.strip()

    @model_validator(mode="after")
    def _enabled_fields_are_atomic(self) -> "LLMRuntimeConfig":
        if self.provider is None:
            if (
                self.model
                or self.temperature != 0.0
                or self.max_retries != DEFAULT_MAX_RETRIES
                or self.timeout_seconds != DEFAULT_TIMEOUT_SECONDS
            ):
                raise ValueError("LLM 关闭时 model/temperature/retry/timeout 必须保持默认")
        elif not self.model:
            raise ValueError("启用 LLM provider 时必须显式指定 model")
        return self

    @property
    def enabled(self) -> bool:
        return self.provider is not None

    def identity_payload(self) -> dict[str, object] | None:
        if self.provider is None:
            return None
        spec = get_provider_spec(self.provider)
        return {
            "provider": self.provider.value,
            "provider_spec_version": spec.spec_version,
            "endpoint": spec.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
        }


def effective_config_payload(
    allocation_payload: Mapping[str, object],
    llm_runtime: LLMRuntimeConfig | None = None,
) -> dict[str, object]:
    """合并安全的 LLM 身份；关闭时逐字节保持旧 AllocationConfig 形状。"""
    payload = deepcopy(dict(allocation_payload))
    runtime = llm_runtime or LLMRuntimeConfig()
    llm_payload = runtime.identity_payload()
    if llm_payload is not None:
        payload["llm"] = llm_payload
    return payload


def effective_config_json(
    allocation_payload: Mapping[str, object],
    llm_runtime: LLMRuntimeConfig | None = None,
) -> str:
    # 保持历史 serializer 口径；默认路径的 hash 必须继续是 e9e97d…。
    return json.dumps(
        effective_config_payload(allocation_payload, llm_runtime),
        sort_keys=True,
    )


def effective_config_digest(
    allocation_payload: Mapping[str, object],
    llm_runtime: LLMRuntimeConfig | None = None,
) -> str:
    return hashlib.sha256(
        effective_config_json(allocation_payload, llm_runtime).encode()
    ).hexdigest()
