"""固定三类 LLM provider 注册表；不支持运行时扩展或任意 base URL。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class LLMProvider(str, Enum):
    OPENAI_COMPATIBLE = "openai_compatible"
    DEEPSEEK = "deepseek"
    OLLAMA = "ollama"


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    provider: LLMProvider
    base_url: str
    api_key_env: str | None
    placeholder_api_key: str | None = None
    spec_version: str = "1"

    @property
    def requires_api_key(self) -> bool:
        return self.api_key_env is not None


_PROVIDER_SPECS: Mapping[LLMProvider, ProviderSpec] = MappingProxyType({
    LLMProvider.OPENAI_COMPATIBLE: ProviderSpec(
        provider=LLMProvider.OPENAI_COMPATIBLE,
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
    ),
    LLMProvider.DEEPSEEK: ProviderSpec(
        provider=LLMProvider.DEEPSEEK,
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
    ),
    LLMProvider.OLLAMA: ProviderSpec(
        provider=LLMProvider.OLLAMA,
        base_url="http://127.0.0.1:11434/v1/",
        api_key_env=None,
        placeholder_api_key="ollama",
    ),
})


def provider_specs() -> Mapping[LLMProvider, ProviderSpec]:
    """返回不可变注册表；关闭状态用 None 表示，不是第四类 provider。"""
    return _PROVIDER_SPECS


def get_provider_spec(provider: LLMProvider | str) -> ProviderSpec:
    try:
        normalized = provider if isinstance(provider, LLMProvider) else LLMProvider(provider)
        return _PROVIDER_SPECS[normalized]
    except (ValueError, KeyError) as exc:
        raise ValueError(f"不支持的 LLM provider：{provider!r}") from exc
