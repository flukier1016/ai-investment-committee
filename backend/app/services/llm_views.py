"""LLM 象限判断调用器（Phase 3 留桩）：失败即弃权，绝不自由文本。

当前默认路径完全不加载任何 LLM SDK（llm_used 恒为 false），pipeline 也不调用
本模块；第 8 项只用本地 mock 验证客户端、降级与 trace 重放边界。
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from ..llm.client import StructuredCompletion, build_client
from ..llm.config import LLMRuntimeConfig
from ..llm.providers import get_provider_spec
from ..llm.traces import (
    TraceCorruptError,
    TraceStoreError,
    build_trace_identity,
    make_trace,
    replay_or_record,
    trace_identity_from_parts,
)
from ..schemas.llm import (CONFIDENCE_BAND_VALUE, LLMTrace, QuadrantCall,
                           RegimeCall)


class LLMClient(Protocol):
    """最小协议：给定 prompt 与目标 schema，返回已解析的 Pydantic 对象。"""

    model: str

    def complete_structured(self, prompt: str, schema: type[BaseModel]) -> object: ...


def _abstain(reason: str) -> QuadrantCall:
    return QuadrantCall(quadrant=RegimeCall.ABSTAIN, confidence_band="low",
                        citations=[], rationale=f"LLM 降级弃权：{reason}")


def _trace_identity(client: LLMClient | None, prompt: str,
                    allowed_citations: set[str]):
    runtime = getattr(client, "runtime_config", None)
    if isinstance(runtime, LLMRuntimeConfig) and runtime.enabled:
        return build_trace_identity(
            runtime,
            call_key="quadrant_call",
            prompt=prompt,
            response_schema=QuadrantCall,
            allowed_citations=allowed_citations,
        )
    return trace_identity_from_parts(
        call_key="quadrant_call",
        provider=str(getattr(client, "provider", "disabled" if client is None else "test")),
        provider_spec_version=str(getattr(client, "provider_spec_version", "test")),
        endpoint=str(getattr(getattr(client, "provider_spec", None), "base_url", "")),
        model=str(getattr(client, "model", "none")),
        temperature=float(getattr(client, "temperature", 0.0)),
        max_retries=int(getattr(client, "max_retries", 0)),
        timeout_seconds=float(getattr(client, "timeout_seconds", 0.0)),
        prompt=prompt,
        response_schema=QuadrantCall,
        allowed_citations=allowed_citations,
    )


def _audit_trace(identity, prompt: str, call: QuadrantCall, *, latency_ms: float = 0.0,
                 completion: StructuredCompletion | None = None,
                 degraded: bool = False, degraded_reason: str = "",
                 error_type: str = "", secrets: tuple[str, ...] = ()) -> LLMTrace:
    return make_trace(
        identity,
        prompt=prompt,
        structured_output=call,
        tokens_in=completion.tokens_in if completion else 0,
        tokens_out=completion.tokens_out if completion else 0,
        latency_ms=latency_ms,
        response_id=completion.response_id if completion else "",
        response_model=completion.response_model if completion else "",
        degraded=degraded,
        degraded_reason=degraded_reason,
        error_type=error_type,
        secrets=secrets,
    )


def _quadrant_call_with_identity(
    client: LLMClient | None,
    identity,
    prompt: str,
    allowed_citations: set[str],
    *,
    secrets: tuple[str, ...] = (),
) -> tuple[QuadrantCall, LLMTrace]:
    if client is None:
        call = _abstain("LLM 未启用")
        return call, _audit_trace(
            identity, prompt, call, degraded=True,
            degraded_reason="llm_disabled", error_type="ProviderDisabled",
            secrets=secrets,
        )

    t0 = time.perf_counter()
    completion: StructuredCompletion | None = None
    try:
        raw_result = client.complete_structured(prompt, QuadrantCall)
        if isinstance(raw_result, StructuredCompletion):
            completion = raw_result
            result = raw_result.parsed
        else:
            result = raw_result
        if not isinstance(result, QuadrantCall):
            result = QuadrantCall.model_validate(result)
    except Exception as exc:  # 解析失败/超时/网络——一律弃权，不回退自由文本
        latency_ms = (time.perf_counter() - t0) * 1000
        error_type = type(exc).__name__
        call = _abstain(f"结构化调用失败（{error_type}）")
        return call, _audit_trace(
            identity, prompt, call, latency_ms=latency_ms,
            degraded=True, degraded_reason=f"client_error:{error_type}",
            error_type=error_type, secrets=secrets,
        )

    latency_ms = (time.perf_counter() - t0) * 1000

    # 防幻觉引用：citations 必须是注入新闻块的编号子集
    bogus = [c for c in result.citations if c not in allowed_citations]
    if bogus:
        call = _abstain(f"引用了不存在的新闻编号 {bogus}")
        return call, _audit_trace(
            identity, prompt, call, latency_ms=latency_ms, completion=completion,
            degraded=True,
            degraded_reason="hallucinated_citation:" + ",".join(bogus),
            error_type="CitationValidationError", secrets=secrets,
        )

    return result, _audit_trace(
        identity, prompt, result, latency_ms=latency_ms, completion=completion,
        secrets=secrets)


def quadrant_call_or_abstain(
    client: LLMClient | None,
    prompt: str,
    allowed_citations: set[str],
) -> tuple[QuadrantCall, LLMTrace]:
    """本地/mock 调用边界；返回内存 trace，不承诺已经落盘。"""
    identity = _trace_identity(client, prompt, allowed_citations)
    return _quadrant_call_with_identity(
        client, identity, prompt, allowed_citations)


def _runtime_secrets(
    runtime: LLMRuntimeConfig,
    environ: Mapping[str, str] | None,
) -> tuple[str, ...]:
    assert runtime.provider is not None
    spec = get_provider_spec(runtime.provider)
    env = os.environ if environ is None else environ
    if not spec.requires_api_key or not spec.api_key_env:
        return ()
    secret = (env.get(spec.api_key_env) or "").strip()
    return (secret,) if len(secret) >= 4 else ()


def quadrant_call_from_runtime(
    runtime: LLMRuntimeConfig,
    prompt: str,
    allowed_citations: set[str],
    *,
    environ: Mapping[str, str] | None = None,
    sdk_factory: Callable[..., Any] | None = None,
) -> tuple[QuadrantCall, LLMTrace]:
    """可重放运行入口；当前不接决策链，测试只注入本地 mock SDK。"""
    if not runtime.enabled:
        return quadrant_call_or_abstain(None, prompt, allowed_citations)
    identity = build_trace_identity(
        runtime,
        call_key="quadrant_call",
        prompt=prompt,
        response_schema=QuadrantCall,
        allowed_citations=allowed_citations,
    )

    def produce() -> LLMTrace:
        secrets = _runtime_secrets(runtime, environ)
        try:
            client = build_client(
                runtime, environ=environ, sdk_factory=sdk_factory)
        except Exception as exc:
            error_type = type(exc).__name__
            call = _abstain(f"客户端初始化失败（{error_type}）")
            return _audit_trace(
                identity,
                prompt,
                call,
                degraded=True,
                degraded_reason=f"client_init_error:{error_type}",
                error_type=error_type,
                secrets=secrets,
            )
        _, trace = _quadrant_call_with_identity(
            client,
            identity,
            prompt,
            allowed_citations,
            secrets=secrets,
        )
        return trace

    try:
        trace, _ = replay_or_record(identity, produce)
        call = QuadrantCall.model_validate(trace.structured_output)
        if any(citation not in allowed_citations for citation in call.citations):
            raise TraceCorruptError("缓存引用超出本次允许集合")
        return call, trace
    except (TraceStoreError, OSError, ValidationError, ValueError) as exc:
        # 审计写入/重放失败时不返回可引用的 trace_id，避免“记录不存在”的悬空引用。
        error_type = type(exc).__name__
        call = _abstain(f"审计轨迹不可用（{error_type}）")
        trace = _audit_trace(
            identity,
            prompt,
            call,
            degraded=True,
            degraded_reason=f"trace_store_error:{error_type}",
            error_type=error_type,
            secrets=_runtime_secrets(runtime, environ),
        ).model_copy(update={"trace_id": "", "persisted": False})
        return call, trace


def confidence_of(call: QuadrantCall) -> float:
    """档位 → 数值，唯一入口；LLM 永不直接给数字（进 Ω 公式前的确定性映射）。"""
    if call.quadrant == RegimeCall.ABSTAIN:
        return 0.0
    return CONFIDENCE_BAND_VALUE[call.confidence_band]
