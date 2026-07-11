"""LLM 象限判断调用器（Phase 3 留桩）：失败即弃权，绝不自由文本。

当前默认路径完全不加载任何 LLM SDK（llm_used 恒为 false）。真接入时只需
实现 LLMClient 协议并传入 quadrant_call_or_abstain。
"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from typing import Protocol

from ..schemas.llm import (CONFIDENCE_BAND_VALUE, LLMTrace, QuadrantCall,
                           RegimeCall)


class LLMClient(Protocol):
    """最小协议：给定 prompt 与目标 schema，返回已解析的 Pydantic 对象。"""

    model: str

    def complete_structured(self, prompt: str, schema: type) -> object: ...


def _abstain(reason: str) -> QuadrantCall:
    return QuadrantCall(quadrant=RegimeCall.ABSTAIN, confidence_band="low",
                        citations=[], rationale=f"LLM 降级弃权：{reason}")


def quadrant_call_or_abstain(
    client: LLMClient | None,
    prompt: str,
    allowed_citations: set[str],
) -> tuple[QuadrantCall, LLMTrace]:
    """调用 LLM 做象限判断；任何失败路径都降级为 ABSTAIN。

    降级触发条件：client 未配置 / 调用抛异常 / 返回类型不符 /
    citations 含幻觉引用（不在注入新闻块内）。
    """
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    trace = LLMTrace(trace_id=f"trace_{uuid.uuid4().hex[:12]}",
                     model=getattr(client, "model", "none"),
                     prompt_sha256=prompt_hash,
                     created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    if client is None:
        trace.degraded, trace.degraded_reason = True, "LLM 未启用"
        return _abstain("LLM 未启用"), trace

    t0 = time.perf_counter()
    try:
        result = client.complete_structured(prompt, QuadrantCall)
        trace.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        if not isinstance(result, QuadrantCall):
            result = QuadrantCall.model_validate(result)
    except Exception as exc:  # 解析失败/超时/网络——一律弃权，不回退自由文本
        trace.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        trace.degraded, trace.degraded_reason = True, f"{type(exc).__name__}: {exc}"
        return _abstain(f"结构化调用失败（{type(exc).__name__}）"), trace

    # 防幻觉引用：citations 必须是注入新闻块的编号子集
    bogus = [c for c in result.citations if c not in allowed_citations]
    if bogus:
        trace.degraded, trace.degraded_reason = True, f"幻觉引用: {bogus}"
        return _abstain(f"引用了不存在的新闻编号 {bogus}"), trace

    return result, trace


def confidence_of(call: QuadrantCall) -> float:
    """档位 → 数值，唯一入口；LLM 永不直接给数字（进 Ω 公式前的确定性映射）。"""
    if call.quadrant == RegimeCall.ABSTAIN:
        return 0.0
    return CONFIDENCE_BAND_VALUE[call.confidence_band]
