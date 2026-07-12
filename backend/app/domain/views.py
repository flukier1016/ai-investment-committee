"""观点标准化：三种战术信号 → Black-Litterman 观点行 (P, Q, Ω)。

纪律（V3 第三节）：
- P 腿内权重来自确定性规则（TSMOM 用动量分数截面归一，
  Clock/ERP 用 Risk Parity 桶内战略权重），多头腿归一为 +1、空头腿为 -1；
- Q 由信号分数 × 校准尺度得到，每条观点写明数值代入（Q_derivation）；
- Ω 的确定性映射：view_variance = 3τ·PΣPᵀ，Ω = (1-c)/c · view_variance，
  绝不让 LLM 直接编 Ω 数字。
"""

from __future__ import annotations

import numpy as np

from ..schemas.config import AllocationConfig
from ..schemas.decision import TracedSignal, View
from . import universe
from .labels import BUCKET_ZH

# Q 校准尺度（年化观点收益 / 单位信号分数），Demo 校准值并写入推导
TSMOM_Q_SCALE = 0.005
CLOCK_Q_SCALE = {"cn_equity": 0.027, "foreign_equity": 0.020, "cn_bond": 0.0136,
                 "foreign_bond": 0.0136, "commodity": 0.0214, "cash": 0.005}
ERP_Q_SCALE = 0.0143
Q_CAP = 0.012

def _leg(entries: dict[str, float], sign: int = 1) -> dict[str, float]:
    total = sum(abs(v) for v in entries.values())
    if total <= 0:
        n = len(entries)
        return {k: sign / n for k in entries}
    return {k: sign * abs(v) / total for k, v in entries.items()}


def _omega(P: dict[str, float], sigma: np.ndarray, asset_index: dict[str, int],
           confidence: float, tau: float) -> tuple[float, float]:
    p = np.zeros(len(asset_index))
    for a, w in P.items():
        p[asset_index[a]] = w
    pvar = float(p @ sigma @ p)
    view_variance = max(3 * tau * pvar, 1e-8)
    c = min(max(confidence, 0.05), 0.95)
    omega = max((1 - c) / c * view_variance, 1e-8)
    return view_variance, omega


def _fmt_leg(leg: dict[str, float]) -> str:
    return "/".join(f"{abs(v) * 100:.0f}" for v in leg.values())


def build_views(signals: dict[str, TracedSignal], tsmom_detail: dict,
                clock_detail: dict, erp_detail: dict,
                rp_detail: dict, sigma: np.ndarray, asset_order: list[str],
                config: AllocationConfig,
                w_prior_map: dict[str, float] | None = None) -> list[View]:
    asset_index = {a: i for i, a in enumerate(asset_order)}
    intra = rp_detail["intra_bucket_inverse_vol"]
    views: list[View] = []

    # 先验隐含收益 π = δΣw_RP：绝对观点的 Q 必须锚定 π（Q = P·π + 信号倾斜），
    # 否则一个“看多但 Q 低于均衡收益”的观点在贝叶斯融合中实际是看空。
    if w_prior_map is not None:
        w_prior_vec = np.array([w_prior_map[a] for a in asset_order])
        pi_vec = config.risk_aversion * sigma @ w_prior_vec
    else:
        pi_vec = np.zeros(len(asset_order))

    def p_dot_pi(P: dict[str, float]) -> float:
        return float(sum(w * pi_vec[asset_index[a]] for a, w in P.items()))

    def add(view_id: str, label: str, sources: list[str], P: dict[str, float],
            p_deriv: str, tilt: float, tilt_deriv: str, conf: float, deriv: str) -> None:
        tilt = float(np.clip(tilt, -Q_CAP, Q_CAP))
        anchor = p_dot_pi(P)
        q = anchor + tilt
        vv, om = _omega(P, sigma, asset_index, conf, config.tau)
        views.append(View(
            view_id=view_id, label=label, source_signal_ids=sources,
            P={k: round(v, 4) for k, v in P.items()}, P_derivation=p_deriv,
            Q=round(q, 5),
            Q_derivation=f"先验隐含收益 P·π = {anchor:+.3%}，信号倾斜 {tilt:+.3%}（{tilt_deriv}），"
                         f"Q = {q:+.3%}。",
            confidence=round(conf, 2),
            view_variance=round(vv, 8), Omega=round(om, 8),
            **{"lambda": 0.0}, derivation=deriv,
        ))

    # ---- Time Series Momentum：每个非零方向的桶一条绝对观点 ----
    ts = signals.get("tsmom")
    if ts is not None:
        scores = tsmom_detail["asset_scores"]
        for b, direction in ts.values.items():
            if b == "cash" or not isinstance(direction, (int, float)) or direction == 0:
                continue
            members = {a: abs(scores.get(a, 0.0)) for a in universe.assets_in_bucket(b)}
            P = _leg(members, 1)
            mean_score = float(np.mean([scores.get(a, 0.0) for a in members]))
            q = float(np.clip(mean_score, -2.0, 2.0)) * TSMOM_Q_SCALE
            conf = min(0.75, 0.50 + 0.10 * abs(mean_score))
            zh = BUCKET_ZH[b]
            trend = "转强" if direction > 0 else "偏弱"
            add(
                f"view_tsmom_{b}", f"{zh}趋势{trend}", [ts.signal_id], P,
                f"{zh}桶内资产按 |12-1 动量/60日波动率| 截面归一为 {_fmt_leg(P)}。",
                q,
                f"桶内标准化动量均值 {mean_score:+.2f}（截断±2）× 收益尺度 {TSMOM_Q_SCALE:.2%}",
                conf,
                f"{zh} 12-1 动量{trend} → {'超配' if direction > 0 else '低配'}",
            )

    # ---- Merrill Lynch Investment Clock：每个非零 tilt 的桶一条绝对观点 ----
    # 观点强度锚定四象限均匀先验 0.25（而非二元阈值 0.5）：
    # strength = (prob − 0.25) / 0.75 ∈ [0,1]，方向永远与象限 tilt 一致；
    # 若用 (prob − 0.5)，四类 softmax 下胜出概率常低于 50%，观点会反向进入 BL。
    ck = signals.get("clock")
    if ck is not None and ck.view_type != "abstain":
        prob = float(ck.values.get("probability", 0.5))
        regime_zh = ck.values.get("regime", "")
        strength = max(prob - 0.25, 0.0) / 0.75
        for b, tilt in ck.values.items():
            if b in ("regime", "probability", "cash") or not isinstance(tilt, (int, float)) or tilt == 0:
                continue
            P = _leg({a: intra.get(b, {}).get(a, 1.0) for a in universe.assets_in_bucket(b)}, 1)
            scale = CLOCK_Q_SCALE.get(b, 0.015)
            q = tilt * strength * scale
            zh = BUCKET_ZH[b]
            action = "受益" if tilt > 0 else "承压"
            add(
                f"view_clock_{b}", f"{zh}{regime_zh}{action}", [ck.signal_id], P,
                f"{zh}桶按 Risk Parity 桶内战略权重映射为 {_fmt_leg(P)}，归一为观点腿；倾斜符号表达方向。",
                q,
                f"({regime_zh}概率 {prob:.0%} − 均匀先验 25%) ÷ 75% = 强度 {strength:.2f}，"
                f"× {scale:.2%} × 方向 {tilt:+d}",
                prob,
                f"{regime_zh}象限概率 {prob:.0%} → {zh}{'超配' if tilt > 0 else '低配'}",
            )

    # ---- Equity Risk Premium：仅中国股债相对观点（两腿） ----
    ep = signals.get("erp")
    if ep is not None and ep.view_type != "abstain":
        direction = int(ep.values["cn_equity_vs_cn_bond"])
        pct = float(ep.values["percentile"])
        long_b, short_b = ("cn_equity", "cn_bond") if direction > 0 else ("cn_bond", "cn_equity")
        P_long = _leg({a: intra.get(long_b, {}).get(a, 1.0)
                       for a in universe.assets_in_bucket(long_b)}, 1)
        P_short = _leg({a: intra.get(short_b, {}).get(a, 1.0)
                        for a in universe.assets_in_bucket(short_b)}, -1)
        P = {**P_long, **P_short}
        q = abs(pct - 0.5) * 2 * ERP_Q_SCALE
        zh_l, zh_s = BUCKET_ZH[long_b], BUCKET_ZH[short_b]
        add(
            "view_erp_cn_equity_bond", f"{zh_l}相对{zh_s}更具性价比", [ep.signal_id], P,
            f"相对观点两腿：{zh_l}多头按桶内战略权重 {_fmt_leg(P_long)}，"
            f"{zh_s}空头 {_fmt_leg(P_short)}；两腿分别归一。",
            q,
            f"(股债利差分位 {pct:.0%} − 中性 50%) × 2 × {ERP_Q_SCALE:.2%}",
            ep.confidence,
            f"股债利差处于 {pct:.0%} 分位 → {zh_l}相对{zh_s}超配",
        )

    return views
