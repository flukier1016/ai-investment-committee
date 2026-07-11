"""L1 信号层：四方法各自生成 TracedSignal。

- Risk Parity（strategic）：唯一战略底仓，输出风险预算权重；
- Time Series Momentum（tactical）：12-1 动量 / 波动率标准化 → 桶级方向；
- Merrill Lynch Investment Clock（tactical）：PMI×CPI 象限概率 → 桶级 tilt；
- Equity Risk Premium（tactical）：股债利差历史分位 → 仅中国股债相对观点，
  其余资产显式弃权（abstain）。

全部数字由确定性代码计算。数据缺失时弃权而非硬凑（V3 第七节 7.4）。
"""

from __future__ import annotations

import math

import numpy as np

from ..schemas.config import AllocationConfig
from ..schemas.decision import TracedSignal
from . import risk_parity, universe
from .covariance import TRADING_DAYS, log_returns
from .market_data import MarketSlice
from .versioning import code_version

AGENT_VERSION = "v1.0.0"

METHOD_NAMES = {
    "risk_parity": "Risk Parity",
    "tsmom": "Time Series Momentum",
    "clock": "Merrill Lynch Investment Clock",
    "erp": "Equity Risk Premium",
}

# 象限 → 桶级 tilt（经典投资时钟：衰退→债、复苏→股、过热→商品、滞胀→防御）。
# 现金不进入 BL 观点：零波动资产的收益观点在 BL 中退化为硬约束，
# 现金缓冲由战略底仓（cash_floor）与风控预算表达。
REGIME_TILTS = {
    "recovery": {"cn_equity": 1, "cn_bond": -1, "commodity": 1},
    "overheat": {"commodity": 1, "cn_bond": -1, "foreign_bond": -1},
    "stagflation": {"commodity": 1, "cn_equity": -1, "cn_bond": -1},
    "recession": {"cn_bond": 1, "foreign_bond": 1, "cn_equity": -1, "commodity": -1},
}
REGIME_ZH = {"recovery": "复苏", "overheat": "过热", "stagflation": "滞胀", "recession": "衰退"}


def _sig_id(slice_: MarketSlice, method: str) -> str:
    return f"sig_{slice_.asof.strftime('%Y%m%d')}_{method}_001"


def abstain_signal(slice_: MarketSlice, method: str, reason: str) -> TracedSignal:
    """可选输入缺失时的显式弃权信号（V3 容错纪律：缺数据弃权而非硬凑）。"""
    return TracedSignal(
        signal_id=_sig_id(slice_, {"tsmom": "tsmom", "clock": "clock", "erp": "erp"}[method]),
        method=method, method_name=METHOD_NAMES[method],  # type: ignore[arg-type]
        layer="tactical", view_type="abstain",
        asof=slice_.asof.isoformat(), values={}, strength={},
        confidence=0.0, horizon_days=0,
        rationale=f"输入数据不可用，按容错纪律整体弃权：{reason}",
        abstain=list(universe.bucket_ids()),
        agent_id=f"{method}_expert", agent_version=AGENT_VERSION,
        code_version=code_version(), params={},
        inputs=[], derivation=f"degraded: {reason}", source_refs=[],
    )


def risk_parity_signal(slice_: MarketSlice, config: AllocationConfig,
                       sigma=None, asset_order=None) -> tuple[TracedSignal, dict[str, float], dict]:
    """返回 (信号, 27资产战略权重, 推导细节)。"""
    weights, detail = risk_parity.strategic_weights(
        slice_.prices, config.cov_window_days, config.cash_floor,
        sigma_assets=sigma, asset_order=asset_order, config=config)
    bucket_w = universe.aggregate_to_buckets(weights)
    signal = TracedSignal(
        signal_id=_sig_id(slice_, "rp"),
        method="risk_parity", method_name=METHOD_NAMES["risk_parity"],
        layer="strategic", view_type="risk_budget",
        asof=slice_.asof.isoformat(),
        values={k: round(v, 4) for k, v in bucket_w.items()},
        strength={}, confidence=0.85, horizon_days=252,
        rationale="估计 26 个风险资产协方差，桶间等风险贡献、桶内逆波动率，汇总为 7 个展示桶的战略底仓。",
        abstain=[],
        agent_id="risk_parity_expert", agent_version=AGENT_VERSION,
        code_version=code_version(),
        params={"cov_window_days": config.cov_window_days,
                "shrinkage": config.shrinkage, "cash_floor": config.cash_floor,
                "structure": "bucket_erc_plus_inverse_vol"},
        inputs=[slice_.input_meta("px:all_27_assets")],
        derivation=f"桶间风险贡献占比 {detail['bucket_risk_contrib']}；现金战略底仓 {config.cash_floor:.0%}",
        source_refs=["px:all_27_assets"],
    )
    return signal, weights, detail


def tsmom_signal(slice_: MarketSlice, config: AllocationConfig) -> tuple[TracedSignal, dict]:
    """12-1 动量 / 60日波动率 → 资产分数 → 桶级方向。返回 (信号, {asset_scores, bucket_scores})。"""
    px = slice_.prices
    lookback, skip, vol_win = 252, 21, 60
    scores: dict[str, float] = {}
    for a in universe.risky_asset_ids():
        s = px[a]
        if len(s) < lookback + skip + 5:
            continue
        mom = float(s.iloc[-skip - 1] / s.iloc[-lookback - skip - 1] - 1)
        vol = float(np.log(s / s.shift(1)).iloc[-vol_win:].std(ddof=1) * math.sqrt(TRADING_DAYS))
        scores[a] = mom / max(vol, 1e-4)
    bucket_scores: dict[str, float] = {}
    for b in universe.bucket_ids():
        if b == "cash":
            continue
        members = [scores[a] for a in universe.assets_in_bucket(b) if a in scores]
        bucket_scores[b] = float(np.mean(members)) if members else 0.0
    threshold = 0.25
    directions = {b: (1 if s >= threshold else -1 if s <= -threshold else 0)
                  for b, s in bucket_scores.items()}
    strength = {b: round(min(abs(s), 3.0) / 3.0, 3) for b, s in bucket_scores.items()}
    active = [b for b, d in directions.items() if d != 0]
    conf = 0.45 + 0.15 * min(1.0, float(np.mean([strength[b] for b in active])) if active else 0.0)
    signal = TracedSignal(
        signal_id=_sig_id(slice_, "tsmom"),
        method="tsmom", method_name=METHOD_NAMES["tsmom"],
        layer="tactical", view_type="direction",
        asof=slice_.asof.isoformat(),
        values=directions, strength=strength,
        confidence=round(conf, 2), horizon_days=60,
        rationale="对 26 个风险资产计算 12-1 动量并除以 60 日波动率，按桶聚合方向；"
                  f"|标准化分数|≥{threshold} 才发言，现金无趋势弃权。",
        abstain=["cash"] + [b for b, d in directions.items() if d == 0],
        agent_id="tsmom_expert", agent_version=AGENT_VERSION,
        code_version=code_version(),
        params={"lookback_months": 12, "skip_months": 1, "vol_window_days": vol_win,
                "bucket_threshold": threshold},
        inputs=[slice_.input_meta("px:all_27_assets_total_return")],
        derivation="; ".join(f"{b}: score={s:+.2f}→{directions[b]:+d}"
                             for b, s in bucket_scores.items()),
        source_refs=["px:all_27_assets_total_return"],
    )
    return signal, {"asset_scores": scores, "bucket_scores": bucket_scores}


def clock_signal(slice_: MarketSlice, config: AllocationConfig) -> tuple[TracedSignal, dict]:
    """PMI（增长轴）× CPI（通胀轴）→ 四象限概率。数据不足时整体弃权。"""
    macro = slice_.macro
    if len(macro) < 6:
        signal = TracedSignal(
            signal_id=_sig_id(slice_, "clock"), method="clock",
            method_name=METHOD_NAMES["clock"], layer="tactical", view_type="abstain",
            asof=slice_.asof.isoformat(), values={}, confidence=0.0,
            rationale="可见宏观数据不足 6 个月，按容错纪律整体弃权。",
            abstain=list(universe.bucket_ids()),
            agent_id="clock_expert", agent_version=AGENT_VERSION,
            code_version=code_version(), params={}, inputs=[], derivation="insufficient macro data",
            source_refs=[],
        )
        return signal, {}
    pmi = macro["pmi_cn"].to_numpy()
    cpi = macro["cpi_yoy_cn"].to_numpy()
    growth_axis = float((pmi[-1] - 50.0) / 2.0 + (pmi[-1] - pmi[-4]) / 1.5)
    inflation_axis = float((cpi[-1] - 2.5) / 1.5 + (cpi[-1] - cpi[-4]) / 0.8)
    raw = {
        "recovery": growth_axis - inflation_axis,
        "overheat": growth_axis + inflation_axis,
        "stagflation": -growth_axis + inflation_axis,
        "recession": -growth_axis - inflation_axis,
    }
    exp = {k: math.exp(v) for k, v in raw.items()}
    total = sum(exp.values())
    probs = {k: round(v / total, 4) for k, v in exp.items()}
    regime = max(probs, key=probs.get)
    prob = probs[regime]
    tilts = REGIME_TILTS[regime]
    values: dict = {"regime": REGIME_ZH[regime], "probability": prob, **tilts}
    latest_month = macro.iloc[-1]["month"]
    signal = TracedSignal(
        signal_id=_sig_id(slice_, "clock"),
        method="clock", method_name=METHOD_NAMES["clock"],
        layer="tactical", view_type="regime",
        asof=slice_.asof.isoformat(),
        values=values,
        strength={k: round(prob, 3) for k in tilts},
        confidence=round(prob, 2), horizon_days=90,
        rationale=f"最新可见 PMI={pmi[-1]:.1f}、CPI同比={cpi[-1]:.2f}%（{latest_month}，按发布日过滤），"
                  f"增长轴 {growth_axis:+.2f}、通胀轴 {inflation_axis:+.2f} → {REGIME_ZH[regime]}象限概率 {prob:.0%}。",
        abstain=["fx"],
        agent_id="clock_expert", agent_version=AGENT_VERSION,
        code_version=code_version(),
        params={"growth_axis": "PMI-50 与 3 个月 PMI 变化", "inflation_axis": "CPI-2.5 与 3 个月 CPI 变化",
                "mapping": "softmax", "llm_used": False},
        inputs=[slice_.input_meta("macro:PMI_CN"), slice_.input_meta("macro:CPI_CN")],
        derivation=", ".join(f"P({REGIME_ZH[k]})={v:.2f}" for k, v in probs.items()),
        source_refs=["macro:PMI_CN", "macro:CPI_CN"],
    )
    return signal, {"probs": probs, "regime": regime, "growth_axis": growth_axis,
                    "inflation_axis": inflation_axis}


def erp_signal(slice_: MarketSlice, config: AllocationConfig) -> tuple[TracedSignal, dict]:
    """沪深300 E/P − 10Y 国债收益率的 3 年分位 → 仅中国股债相对观点。"""
    erp = slice_.erp
    window = 756
    if len(erp) < 60:
        signal = abstain_signal(slice_, "erp", f"ERP 输入仅 {len(erp)} 个交易日（<60）")
        return signal, {"degraded": True}
    gap = (erp["csi300_ep"] - erp["cgb10y_yield"]).iloc[-window:]
    current = float(gap.iloc[-1])
    pct = float((gap <= current).mean())
    upper, lower = 0.70, 0.30
    if pct >= upper:
        direction, stance = 1, "股相对债便宜，超配中国股票/低配中国债券"
    elif pct <= lower:
        direction, stance = -1, "股相对债偏贵，低配中国股票/超配中国债券"
    else:
        direction, stance = 0, f"分位 {pct:.0%} 处于中性区间 [{lower:.0%}, {upper:.0%}]，弃权"
    conf = round(0.4 + 0.4 * abs(pct - 0.5) * 2, 2) if direction else 0.0
    signal = TracedSignal(
        signal_id=_sig_id(slice_, "erp"),
        method="erp", method_name=METHOD_NAMES["erp"],
        layer="tactical", view_type="percentile" if direction else "abstain",
        asof=slice_.asof.isoformat(),
        values={"cn_equity_vs_cn_bond": direction, "percentile": round(pct, 2),
                "gap": round(current, 4)},
        strength={"cn_equity_vs_cn_bond": round(abs(pct - 0.5) * 2, 3)},
        confidence=conf, horizon_days=120,
        rationale=f"股债利差 {current:.2%}，处于近三年 {pct:.0%} 分位。{stance}。"
                  "仅对中国股债发言，商品/外汇/海外资产/现金显式弃权。",
        abstain=["foreign_equity", "foreign_bond", "commodity", "fx", "cash"],
        agent_id="erp_expert", agent_version=AGENT_VERSION,
        code_version=code_version(),
        params={"equity_yield": "CSI300_E/P", "bond_yield": "CGB10Y",
                "percentile_window_days": window, "upper": upper, "lower": lower},
        inputs=[slice_.input_meta("fundamental:CSI300_EP"), slice_.input_meta("yield:CGB10Y")],
        derivation=f"gap={current:.4f}; percentile_3y={pct:.2f}; direction={direction:+d}",
        source_refs=["fundamental:CSI300_EP", "yield:CGB10Y"],
    )
    return signal, {"percentile": pct, "gap": current, "direction": direction}
