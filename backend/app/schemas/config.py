"""账户与引擎配置契约。

投资性格问卷只允许透明映射到这里的风险参数与约束，
不得改变任何方法在 Black-Litterman 融合中的话语权。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AllocationConfig(BaseModel):
    principal: float = Field(default=50_000_000, gt=0, description="账户本金（元）")
    currency: str = Field(default="CNY", pattern="^(CNY|USD)$")
    target_vol: float = Field(default=0.08, gt=0, le=0.4, description="目标年化波动")
    max_drawdown_tolerance: float = Field(default=0.105, gt=0, le=0.8)
    single_asset_cap: float = Field(default=0.10, gt=0, le=1.0, description="单一明细资产上限")
    cn_equity_cap: float = Field(default=0.35, gt=0, le=1.0, description="中国股票桶上限")
    equity_class_cap: float = Field(default=0.60, gt=0, le=1.0, description="权益大类上限")
    bond_floor: float = Field(default=0.20, ge=0, le=0.8, description="债券大类底仓下限")
    cash_floor: float = Field(default=0.05, ge=0, le=0.5, description="现金战略底仓")
    rebalance: str = Field(default="monthly", pattern="^(weekly|monthly|quarterly)$")
    no_trade_band: float = Field(default=0.015, ge=0, le=0.10, description="免交易带（桶权重偏离阈值）")
    cost_bps_per_side: float = Field(default=10.0, ge=0, description="单边交易成本（基点）")
    # Black-Litterman 参数（确定性，由代码使用；LLM 不得触碰）
    risk_aversion: float = Field(default=4.8, gt=0, description="δ 风险厌恶系数")
    tau: float = Field(default=0.05, gt=0, le=1.0, description="τ 先验不确定性尺度")
    max_view_tilt: float = Field(default=0.05, gt=0, le=0.3,
                                 description="单一观点最大权重倾斜 |λ| 上限（Idzorek 2007 式）")
    cov_window_days: int = Field(default=504, ge=120, description="协方差滚动窗（交易日）")
    shrinkage: float = Field(default=0.20, ge=0, le=1.0, description="协方差向对角矩阵的线性收缩强度")
    # 明细资产风险敞口上限（万元），键为资产 id；缺省时使用 single_asset_cap
    risk_caps_wan: dict[str, float] = Field(default_factory=dict)

    def fingerprint_payload(self) -> dict:
        return self.model_dump()


class PersonalityProfile(BaseModel):
    """16 型投资性格 → 风险参数的透明映射结果（可选 Demo 功能）。"""

    type_code: str
    type_name: str
    target_vol: float
    max_drawdown: float
    single_asset_cap: float
    bond_floor: float
    rebalance: str

    def apply_to(self, config: AllocationConfig) -> AllocationConfig:
        return config.model_copy(update={
            "target_vol": self.target_vol,
            "max_drawdown_tolerance": self.max_drawdown,
            "single_asset_cap": min(self.single_asset_cap, 0.35),
            "bond_floor": self.bond_floor,
            "rebalance": self.rebalance,
        })
