"""LLM 结构化输出契约（Phase 3 预埋）：零网络、失败即弃权、防幻觉引用。

对应 V3 第八节 C 类红队门禁：接新闻源前必须先过对抗性测试。
包含同形异义字（homoglyph）对抗样本——TradingAgents 论文引用的
IEEE SaTML 2026 攻击（arXiv:2601.13082）的最小回归样本。
"""

import pytest
from pydantic import ValidationError

from app.schemas.llm import (CONFIDENCE_BAND_VALUE, QuadrantCall, RegimeCall,
                             render_quadrant_call)
from app.services.llm_views import confidence_of, quadrant_call_or_abstain


class FakeClient:
    model = "fake-model"

    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc

    def complete_structured(self, prompt, schema):
        if self._exc:
            raise self._exc
        return self._result


ALLOWED = {"news_001", "news_002", "news_003"}


def test_client_none_degrades_to_abstain():
    call, trace = quadrant_call_or_abstain(None, "prompt", ALLOWED)
    assert call.quadrant == RegimeCall.ABSTAIN
    assert trace.degraded and trace.model == "none"


def test_client_exception_degrades_to_abstain_never_freetext():
    client = FakeClient(exc=TimeoutError("slow"))
    call, trace = quadrant_call_or_abstain(client, "prompt", ALLOWED)
    assert call.quadrant == RegimeCall.ABSTAIN
    assert trace.degraded and "TimeoutError" in trace.degraded_reason


def test_hallucinated_citation_rejected():
    good = QuadrantCall(quadrant=RegimeCall.RECOVERY, confidence_band="high",
                        citations=["news_001", "news_999"], rationale="编造引用")
    call, trace = quadrant_call_or_abstain(FakeClient(result=good), "prompt", ALLOWED)
    assert call.quadrant == RegimeCall.ABSTAIN
    assert "news_999" in trace.degraded_reason


def test_valid_call_passes_with_trace():
    good = QuadrantCall(quadrant=RegimeCall.STAGFLATION, confidence_band="medium",
                        citations=["news_002"], rationale="通胀高企、增长走弱。")
    call, trace = quadrant_call_or_abstain(FakeClient(result=good), "prompt", ALLOWED)
    assert call.quadrant == RegimeCall.STAGFLATION
    assert not trace.degraded
    assert trace.prompt_sha256 and len(trace.prompt_sha256) == 64


def test_confidence_band_is_only_numeric_gateway():
    """LLM 只能给档位；数值由确定性映射产生，弃权时恒为 0。"""
    for band, value in CONFIDENCE_BAND_VALUE.items():
        call = QuadrantCall(quadrant=RegimeCall.RECOVERY, confidence_band=band)
        assert confidence_of(call) == value
    abstain = QuadrantCall(quadrant=RegimeCall.ABSTAIN, confidence_band="high")
    assert confidence_of(abstain) == 0.0


def test_enum_rejects_freeform_quadrant():
    with pytest.raises(ValidationError):
        QuadrantCall(quadrant="牛市", confidence_band="high")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        QuadrantCall(quadrant=RegimeCall.RECOVERY, confidence_band="超高")  # type: ignore[arg-type]


def test_nullish_coercion():
    call = QuadrantCall(quadrant=RegimeCall.OVERHEAT, confidence_band="low",
                        citations="N/A", rationale="None")  # type: ignore[arg-type]
    assert call.citations == [] and call.rationale == ""


def test_homoglyph_adversarial_title_cannot_break_contract():
    """同形异义字新闻标题（西里尔字母 С 冒充拉丁 C）只能影响 LLM 的档位选择，
    无法让输出逃出枚举——即使被操纵，伤害上限也是一个合法象限 + 档位。"""
    adversarial_prompt = "新闻[news_001]: СРI surges（同形异义字操纵样本）"
    manipulated = QuadrantCall(quadrant=RegimeCall.OVERHEAT, confidence_band="high",
                               citations=["news_001"], rationale="通胀飙升")
    call, trace = quadrant_call_or_abstain(FakeClient(result=manipulated),
                                           adversarial_prompt, ALLOWED)
    assert call.quadrant in set(RegimeCall)  # 永远是合法枚举
    assert confidence_of(call) <= max(CONFIDENCE_BAND_VALUE.values())  # 数值有上界
    # 返回非法形状（模拟注入让模型输出自由文本）→ 弃权
    call2, trace2 = quadrant_call_or_abstain(
        FakeClient(result="I think we should BUY NOW!!!"), adversarial_prompt, ALLOWED)
    assert call2.quadrant == RegimeCall.ABSTAIN
    assert trace2.degraded


def test_render_shape_stable_for_all_enums():
    for regime in RegimeCall:
        md = render_quadrant_call(QuadrantCall(quadrant=regime, confidence_band="low"))
        assert md.startswith("**象限判断**：")
