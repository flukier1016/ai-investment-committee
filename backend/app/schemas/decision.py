"""决策链数据契约：TracedSignal / View / DecisionRecord / DecisionTraceBundle。

字段口径以《AI资产配置投委会_五方法三层_AgentSKILL_V3.md》第 3/5 节为准，
前端消费形状以《AI前端实现交接_三层溯源看板.md》第 6 节为准。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Method = Literal["risk_parity", "tsmom", "clock", "erp"]
Layer = Literal["strategic", "tactical"]
ViewType = Literal["risk_budget", "direction", "regime", "percentile", "abstain"]


class DataInput(BaseModel):
    data_id: str
    source: str
    asof: str
    hash: str


class TracedSignal(BaseModel):
    """信号 + 血缘（谁 / 何时 / 基于什么 / 怎么算）。"""

    signal_id: str
    method: Method
    method_name: str
    layer: Layer
    view_type: ViewType
    asof: str
    values: dict[str, Any]
    strength: dict[str, float] = Field(default_factory=dict)
    confidence: float
    horizon_days: int = 60
    rationale: str
    abstain: list[str] = Field(default_factory=list)
    agent_id: str
    agent_version: str
    code_version: str
    params: dict[str, Any] = Field(default_factory=dict)
    inputs: list[DataInput]
    derivation: str
    source_refs: list[str] = Field(default_factory=list)


class View(BaseModel):
    """Black-Litterman 观点行。Ω 由确定性代码从 confidence 映射，绝不由 LLM 生成。"""

    view_id: str
    label: str
    source_signal_ids: list[str]
    P: dict[str, float]
    P_derivation: str
    Q: float
    Q_derivation: str
    confidence: float
    view_variance: float
    Omega: float
    lam: float = Field(alias="lambda", description="应用的观点组合权重 λ（截断后）")
    lam_raw: float = Field(default=0.0, alias="lambda_raw",
                           description="He-Litterman 原始 λ（未截断）")
    derivation: str

    model_config = {"populate_by_name": True}


class GuardrailAction(BaseModel):
    rule: str
    label: str
    triggered: bool
    detail: str


class PriorBlock(BaseModel):
    w_strategic: dict[str, float]
    pi: dict[str, float]
    delta: float
    tau: float


class DecisionRecord(BaseModel):
    """一次完整决策的不可变记录（落库对象）。"""

    decision_id: str
    asof: str
    scenario_id: str
    mode: str = "demo"
    config: dict[str, Any]
    input_fingerprint: str
    input_signals: list[str]
    signals_by_id: dict[str, TracedSignal]
    prior: PriorBlock
    bl_inputs: dict[str, Any]  # {"asset_order": [...], "views": [View...]}
    posterior_ER: dict[str, float]
    target_weights: dict[str, float]  # 27 明细资产
    bucket_weights: dict[str, float]  # 7 桶
    class_weights: dict[str, float]  # 5 大类
    attribution: dict[str, dict[str, float]]  # bucket -> {prior, view_id..., guardrail?}
    guardrail_actions: list[GuardrailAction]
    conclusion: str
    checks: dict[str, Any]
    engine_runtime_ms: float
    code_version: str
    created_at: str
    llm_traces: list[str] = Field(default_factory=list)
    approver: str = "pending"
