"""LLM 可选基础设施。

本包顶层只导出纯 Python 契约；OpenAI SDK 仅在启用 provider 并构建 client 时
惰性导入，默认确定性路径不会加载任何可选依赖。
"""

from .config import LLMRuntimeConfig
from .providers import LLMProvider, ProviderSpec, get_provider_spec, provider_specs

__all__ = [
    "LLMProvider",
    "LLMRuntimeConfig",
    "ProviderSpec",
    "get_provider_spec",
    "provider_specs",
]
