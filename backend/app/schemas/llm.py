"""LLM 结构化输出契约（Phase 3 预埋，当前无任何 LLM 调用）。

铁律的结构性执法（V3 第七节防御 #1：结构化输出是最强防线）：
- 象限判断只能输出预定义枚举 + 置信度档位；LLM 永远不产 Ω/权重/收益率数字，
  置信度档位由确定性代码映射为数值再进 Ω 公式；
- citations 必须引用注入 prompt 的新闻编号，服务层校验拒绝幻觉引用；
- 解析失败/超时/非法值一律降级为 ABSTAIN（弃权），绝不回退自由文本
  （TradingAgents 回退自由文本的做法对本系统违规）。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

_NULLISH = {"", "none", "null", "n/a", "na", "-", "tbd", "unknown"}


class RegimeCall(str, Enum):
    """宏观象限枚举——与 signals.REGIME_TILTS 的键一一对应，外加弃权。"""

    RECOVERY = "recovery"
    OVERHEAT = "overheat"
    STAGFLATION = "stagflation"
    RECESSION = "recession"
    ABSTAIN = "abstain"


ConfidenceBand = Literal["low", "medium", "high"]

# 置信度档位 → 数值（由确定性代码消费，进现有 Ω=(1-c)/c·3τ·PΣPᵀ 公式；
# LLM 只能选档位，不能给数字）
CONFIDENCE_BAND_VALUE: dict[str, float] = {"low": 0.40, "medium": 0.60, "high": 0.80}


class QuadrantCall(BaseModel):
    """LLM 象限判断的唯一合法输出形状。字段描述即模型指令。"""

    model_config = {"extra": "forbid"}

    quadrant: RegimeCall = Field(
        description="四象限判断，只能是 recovery/overheat/stagflation/recession；"
                    "证据不足或相互矛盾时必须选 abstain")
    confidence_band: ConfidenceBand = Field(
        default="low",
        description="判断置信度档位，只能是 low/medium/high；不允许输出数字")
    citations: list[str] = Field(
        default_factory=list,
        description="支撑判断的新闻编号列表，必须来自提供的新闻块，禁止编造")
    rationale: str = Field(
        default="",
        description="两到三句中文说明，只做定性归纳，不得包含任何权重或收益率数字")

    @field_validator("citations", mode="before")
    @classmethod
    def _coerce_citations(cls, v):  # LLM 偶尔给 'None'/'-' 等哨值
        if v is None or (isinstance(v, str) and v.strip().lower() in _NULLISH):
            return []
        return v

    @field_validator("rationale", mode="before")
    @classmethod
    def _coerce_rationale(cls, v):
        if v is None or (isinstance(v, str) and v.strip().lower() in _NULLISH):
            return ""
        return str(v)


class ViewExplanation(BaseModel):
    """LLM 为某条观点生成的叙事解释（数字全部来自 DecisionRecord，LLM 只组织语言）。"""

    model_config = {"extra": "forbid"}

    view_id: str
    narrative: str = Field(description="三句以内中文解释，引用给定事实块，不得新增数字")
    cited_evidence: list[str] = Field(default_factory=list)


class LLMTrace(BaseModel):
    """单次 LLM 调用的审计痕迹（对应 V3 5.4 LLM observability 与
    DecisionRecord.llm_traces 字段）。"""

    trace_id: str
    persisted: bool = False
    schema_version: int = 0
    call_key: str = ""
    call_fingerprint: str = ""
    provider: str = "unknown"
    provider_spec_version: str = ""
    endpoint: str = ""
    model: str
    temperature: float = 0.0
    max_retries: int = 0
    timeout_seconds: float = 0.0
    prompt_sha256: str
    prompt: str = ""
    response_schema: str = ""
    response_schema_sha256: str = ""
    allowed_citations_sha256: str = ""
    structured_output: dict[str, Any] | None = None
    output_sha256: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    response_id: str = ""
    response_model: str = ""
    degraded: bool = False
    degraded_reason: str = ""
    error_type: str = ""
    created_at: str = ""


REGIME_ZH = {"recovery": "复苏", "overheat": "过热", "stagflation": "滞胀",
             "recession": "衰退", "abstain": "弃权"}


def render_quadrant_call(call: QuadrantCall) -> str:
    """渲染为溯源看板用的固定形状 Markdown（下游只消费这一形状）。"""
    lines = [f"**象限判断**：{REGIME_ZH[call.quadrant.value]}"
             f"（置信度档位：{call.confidence_band}）"]
    if call.citations:
        lines.append("**引用新闻**：" + "、".join(call.citations))
    if call.rationale:
        lines.append(f"**判断依据**：{call.rationale}")
    return "\n\n".join(lines)
