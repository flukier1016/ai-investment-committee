"""端到端决策工作流（一次决策的时序，V3 第四节）。

市场/宏观 Demo 输入 → point-in-time 切片与输入指纹
→ Risk Parity 战略底仓 → TSMOM/Clock/ERP 战术信号
→ 观点标准化 (P,Q,Ω) → Black-Litterman 后验
→ 风控投影 → 27 明细资产权重 → 7 桶 → 5 大类
→ He-Litterman 观点归因（含风控段，严格闭合）
→ 不可变 DecisionRecord。

所有数字由确定性代码计算；相同输入（数据指纹 + 配置指纹）产生相同结果。
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np

from ..schemas.config import AllocationConfig
from ..schemas.decision import DecisionRecord, PriorBlock, TracedSignal, View
from . import signals as sig_mod
from . import universe
from .black_litterman import run_bl
from .covariance import shrunk_covariance
from .guardrails import apply_guardrails
from .labels import BUCKET_ZH
from .market_data import DataError, MarketSlice, load_slice
from .stance import bucket_stances_from_weights, stance_direction
from .versioning import code_version


def _decision_id(slice_: MarketSlice, scenario_id: str, config: AllocationConfig) -> str:
    cfg_fp = hashlib.sha256(
        json.dumps(config.fingerprint_payload(), sort_keys=True).encode()).hexdigest()[:6]
    return f"dec_{slice_.asof.strftime('%Y%m%d')}_{scenario_id}_{slice_.fingerprint[:6]}{cfg_fp}"


def _bucket_agg(vec: np.ndarray, asset_order: list[str]) -> dict[str, float]:
    return universe.aggregate_to_buckets(
        {a: float(v) for a, v in zip(asset_order, vec)})


def _conclusion(prior_b: dict[str, float], target_b: dict[str, float],
                regime: str | None, bucket_stances: dict[str, str]) -> str:
    deltas = {b: target_b[b] - prior_b[b] for b in target_b}
    over = sorted((b for b in deltas if stance_direction(bucket_stances[b]) > 0),
                  key=lambda b: -deltas[b])
    under = sorted((b for b in deltas if stance_direction(bucket_stances[b]) < 0),
                   key=lambda b: deltas[b])
    parts = []
    if regime:
        parts.append(f"宏观象限判定为{regime}")
    if over:
        parts.append("、".join(
            f"{bucket_stances[b]}{BUCKET_ZH[b]}（{deltas[b]:+.1%}）" for b in over[:3]))
    if under:
        parts.append("、".join(
            f"{bucket_stances[b]}{BUCKET_ZH[b]}（{deltas[b]:+.1%}）" for b in under[:3]))
    if not over and not under:
        parts.append("战术观点接近中性，目标权重贴近 Risk Parity 战略底仓")
    parts.append(f"现金保留 {target_b['cash']:.1%} 作为流动性缓冲")
    return "；".join(parts) + "。"


def run_decision(scenario_id: str, asof: str, config: AllocationConfig,
                 mode: str = "demo") -> DecisionRecord:
    t0 = time.perf_counter()
    slice_ = load_slice(asof)
    asset_order = universe.asset_ids()

    # 协方差（先于信号层：约束式 Risk Parity 需要资产级协方差）
    sigma = shrunk_covariance(slice_.prices, asset_order,
                              config.cov_window_days, config.shrinkage)

    # L1 信号层。核心/可选分级：价格与协方差（Risk Parity 依赖）是核心输入，
    # 失败向上抛整次中止；三个战术信号是可选输入，失败降级为显式弃权，
    # BL 少观点仍闭合，决策照常产出，降级事实记入 DecisionRecord.degraded_inputs。
    degraded_inputs: list[dict] = []
    rp_signal, w_strategic_map, rp_detail = sig_mod.risk_parity_signal(
        slice_, config, sigma=sigma, asset_order=asset_order)

    def _tactical(method: str, gen):
        try:
            signal, detail = gen()
        except DataError as exc:
            signal, detail = sig_mod.abstain_signal(slice_, method, str(exc)), {}
            degraded_inputs.append({"input": method, "reason": str(exc), "action": "abstain"})
            return signal, detail
        if signal.view_type == "abstain":
            degraded_inputs.append({"input": method, "reason": signal.rationale, "action": "abstain"})
        return signal, detail

    ts_signal, ts_detail = _tactical("tsmom", lambda: sig_mod.tsmom_signal(slice_, config))
    ck_signal, ck_detail = _tactical("clock", lambda: sig_mod.clock_signal(slice_, config))
    ep_signal, ep_detail = _tactical("erp", lambda: sig_mod.erp_signal(slice_, config))
    signals: dict[str, TracedSignal] = {
        "risk_parity": rp_signal, "tsmom": ts_signal, "clock": ck_signal, "erp": ep_signal}

    # 观点装配（Q 锚定先验隐含收益 π）
    from .views import build_views
    views = build_views(signals, ts_detail, ck_detail, ep_detail,
                        rp_detail, sigma, asset_order, config,
                        w_prior_map=w_strategic_map)

    # L2 Black-Litterman 融合
    w_prior = np.array([w_strategic_map[a] for a in asset_order])
    # 立场口径与落库先验一致：先将明细先验舍入到 6 位，再聚合到桶。
    prior_map = {a: round(float(w), 6) for a, w in zip(asset_order, w_prior)}
    bl = run_bl(w_prior, sigma, views, asset_order, config.risk_aversion,
                config.tau, config.max_view_tilt)
    annotated = []
    for v, l, lr in zip(views, bl.lambdas, bl.lambdas_raw):
        deriv = v.derivation
        if l == 0.0 and lr != 0.0:
            deriv += f"；联合融合中被同资产更强观点支配（原始 λ={lr:+.4f}），按方向纪律未采纳"
        elif abs(l) < abs(lr):
            deriv += f"；原始 λ={lr:+.4f} 超出单观点倾斜上限 ±{config.max_view_tilt:.0%}，截断为 {l:+.4f}"
        annotated.append(v.model_copy(update={"lam": round(l, 6), "lam_raw": round(lr, 6),
                                              "derivation": deriv}))
    views = annotated

    # L3 风控投影
    w_final, actions = apply_guardrails(bl.w_uncon, sigma, asset_order, config)

    # 落库权重取 6 位小数；用最大余数法归还舍入残差，保证 27 资产严格加总为 1，
    # 桶与大类一律从舍入后的明细聚合，三层闭合一致。
    target_map = {a: round(float(w), 6) for a, w in zip(asset_order, w_final)}
    resid = round(1.0 - sum(target_map.values()), 9)
    if abs(resid) > 0:
        largest = max(target_map, key=lambda k: target_map[k])
        target_map[largest] = round(target_map[largest] + resid, 9)

    # 归因：prior + Σ 观点段 + 风控段 = target（按桶严格闭合）
    prior_b = _bucket_agg(w_prior, asset_order)
    target_b = universe.aggregate_to_buckets(target_map)
    persisted_prior_b = universe.aggregate_to_buckets(prior_map)
    bucket_stances = bucket_stances_from_weights(
        persisted_prior_b, target_b, universe.bucket_ids())
    uncon_b = _bucket_agg(bl.w_uncon, asset_order)
    attribution: dict[str, dict[str, float]] = {}
    for bi, b in enumerate(universe.bucket_ids()):
        entry: dict[str, float] = {"prior": round(prior_b[b], 6)}
        for v, contrib in zip(views, bl.view_contribs):
            cb = _bucket_agg(contrib, asset_order)[b]
            if abs(cb) > 5e-7:
                entry[v.view_id] = round(cb, 6)
        g = target_b[b] - uncon_b[b]
        if abs(g) > 5e-7:
            entry["guardrail"] = round(g, 6)
        # 数值残差归入最大段，保证展示层闭合
        resid = target_b[b] - sum(entry.values())
        if abs(resid) > 1e-9:
            largest = max(entry, key=lambda k: abs(entry[k]))
            entry[largest] = round(entry[largest] + resid, 9)
        attribution[b] = entry

    # 桶级后验收益（桶内按先验权重加权）
    posterior_b: dict[str, float] = {}
    pi_b: dict[str, float] = {}
    for b in universe.bucket_ids():
        members = [i for i, a in enumerate(asset_order) if universe.bucket_of()[a] == b]
        wsum = sum(w_prior[i] for i in members)
        posterior_b[b] = round(float(sum(bl.mu_bl[i] * w_prior[i] for i in members) / wsum), 5) \
            if wsum > 0 else 0.0
        pi_b[b] = round(float(sum(bl.pi[i] * w_prior[i] for i in members) / wsum), 5) \
            if wsum > 0 else 0.0

    class_w = universe.aggregate_to_classes(target_b)
    regime = ck_signal.values.get("regime") if ck_signal.view_type != "abstain" else None

    checks = {
        "portfolio_vol": round(float(np.sqrt(max(w_final @ sigma @ w_final, 0.0))), 5),
        "weight_sum_assets": round(sum(target_map.values()), 8),
        "weight_sum_buckets": round(sum(target_b.values()), 8),
        "weight_sum_classes": round(sum(class_w.values()), 8),
        "attribution_closure": all(
            abs(sum(attribution[b].values()) - target_b[b]) < 1e-6
            for b in target_b),
        "views_have_sources": all(bool(v.source_signal_ids) for v in views),
        "omega_positive": all(v.Omega > 0 for v in views),
        "p_q_omega_rows": len(views),
        "macro_staleness_days": int((slice_.asof - slice_.macro["publish_date"].max()).days)
        if len(slice_.macro) else None,
        "cov_observations": int(min(len(slice_.prices) - 1, config.cov_window_days)),
        "cov_window_full": bool(len(slice_.prices) - 1 >= config.cov_window_days),
    }

    runtime_ms = (time.perf_counter() - t0) * 1000
    record = DecisionRecord(
        decision_id=_decision_id(slice_, scenario_id, config),
        asof=slice_.asof.strftime("%Y-%m-%dT09:30:00+08:00"),
        scenario_id=scenario_id, mode=mode,
        config=config.model_dump(),
        input_fingerprint=slice_.fingerprint,
        input_signals=[s.signal_id for s in signals.values()],
        signals_by_id={s.signal_id: s for s in signals.values()},
        prior=PriorBlock(
            w_strategic=prior_map,
            pi={a: round(float(p), 6) for a, p in zip(asset_order, bl.pi)},
            delta=config.risk_aversion, tau=config.tau),
        bl_inputs={"asset_order": asset_order,
                   "views": [v.model_dump(by_alias=True) for v in views]},
        posterior_ER=posterior_b,
        target_weights=target_map,
        bucket_weights={b: round(v, 9) for b, v in target_b.items()},
        bucket_stances=bucket_stances,
        class_weights={c: round(v, 9) for c, v in class_w.items()},
        attribution=attribution,
        guardrail_actions=actions,
        conclusion=_conclusion(persisted_prior_b, target_b, regime, bucket_stances),
        checks=checks,
        degraded_inputs=degraded_inputs,
        engine_runtime_ms=round(runtime_ms, 1),
        code_version=code_version(),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    return record


def prior_bucket_weights(record: DecisionRecord) -> dict[str, float]:
    return universe.aggregate_to_buckets(record.prior.w_strategic)


@lru_cache(maxsize=512)
def _run_cached(scenario_id: str, asof: str, config_json: str, mode: str) -> DecisionRecord:
    return run_decision(scenario_id, asof,
                        AllocationConfig.model_validate_json(config_json), mode)


def run_decision_cached(scenario_id: str, asof: str, config: AllocationConfig,
                        mode: str = "demo") -> DecisionRecord:
    """进程内缓存版：相同输入直接复用（结果本就确定性）。"""
    return _run_cached(scenario_id, asof, config.model_dump_json(), mode)
