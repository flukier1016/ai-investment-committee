"""回测：月度调仓 walk-forward，每个调仓日只用当时可见数据（防前视）。

委员会组合调用与生产完全相同的决策管线；基准（60/40、等权、
纯 Risk Parity、现金）同窗同成本口径。结果按输入指纹缓存。
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from ..schemas.config import AllocationConfig
from . import universe
from .market_data import _prices, trading_dates
from .pipeline import run_decision_cached as run_decision

COST = 1e-4  # 每边 1bp 的额外滑点常数由 config.cost_bps_per_side 控制，这里只留占位
MIN_HISTORY_DAYS = 530  # 协方差窗 504 + TSMOM 回看的最低数据量


def _rebalance_dates(freq: str = "monthly") -> list[pd.Timestamp]:
    dates = trading_dates()
    start = dates[0] + pd.Timedelta(days=int(MIN_HISTORY_DAYS * 7 / 5))
    eligible = dates[dates >= start]
    if freq == "weekly":
        marks = eligible.to_series().groupby(eligible.to_period("W")).last()
    elif freq == "quarterly":
        marks = eligible.to_series().groupby(eligible.to_period("Q")).last()
    else:
        marks = eligible.to_series().groupby(eligible.to_period("M")).last()
    return [pd.Timestamp(d) for d in marks]


def _hold_returns(prices: pd.DataFrame, weights: dict[str, float],
                  start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """持有期组合日收益（期初权重买入持有，期内随价格漂移）。"""
    px = prices.loc[start:end]
    if len(px) < 2:
        return pd.Series(dtype=float)
    rel = px / px.iloc[0]
    port_value = (rel * pd.Series(weights)).sum(axis=1)
    return port_value.pct_change().dropna()


def _drifted_weights(prices: pd.DataFrame, weights: dict[str, float],
                     start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float]:
    """期初权重持有到期末后的漂移权重（换手与成本按真实交易量计）。"""
    rel = prices.loc[end] / prices.loc[start]
    drifted = {a: w * float(rel[a]) for a, w in weights.items()}
    total = sum(drifted.values())
    return {a: w / total for a, w in drifted.items()} if total > 0 else dict(weights)


def _turnover(new_w: dict[str, float], held_w: dict[str, float] | None) -> float:
    """调仓换手：目标权重 vs 漂移后持仓（首期建仓按同一口径计半程）。"""
    if held_w is None:
        return sum(abs(v) for v in new_w.values())
    return sum(abs(new_w[a] - held_w.get(a, 0.0)) for a in new_w)


def _benchmark_weights() -> dict[str, dict[str, float]]:
    eq = [a for a in universe.risky_asset_ids()
          if universe.class_of_bucket()[universe.bucket_of()[a]] == "equity"]
    bd = [a for a in universe.risky_asset_ids()
          if universe.class_of_bucket()[universe.bucket_of()[a]] == "bond"]
    risky = universe.risky_asset_ids()
    return {
        "bm_6040": {**{a: 0.6 / len(eq) for a in eq}, **{a: 0.4 / len(bd) for a in bd}},
        "bm_equal": {a: 1.0 / len(risky) for a in risky},
        "cash": {"cash": 1.0},
    }


def _metrics(nav: pd.Series, cash_nav: pd.Series) -> dict:
    rets = nav.pct_change().dropna()
    if len(rets) < 20:
        return {}
    years = len(rets) / 252
    ann_return = float(nav.iloc[-1] ** (1 / years) - 1)
    ann_vol = float(rets.std(ddof=1) * np.sqrt(252))
    rf = float(cash_nav.iloc[-1] ** (1 / years) - 1)
    peak = nav.cummax()
    dd = (nav / peak - 1)
    max_dd = float(dd.min())
    sharpe = (ann_return - rf) / ann_vol if ann_vol > 0 else 0.0
    return {
        "ann_return": round(ann_return, 4), "ann_vol": round(ann_vol, 4),
        "sharpe": round(sharpe, 2), "max_drawdown": round(max_dd, 4),
        "calmar": round(ann_return / abs(max_dd), 2) if max_dd < 0 else None,
    }


def run_backtest(config: AllocationConfig) -> dict:
    from ..services.store import cache_json
    key = "backtest_" + hashlib.sha256(
        json.dumps(config.fingerprint_payload(), sort_keys=True).encode()).hexdigest()[:12]
    cached = cache_json(key)
    if cached is not None:
        return cached

    prices = _prices()
    rebal_dates = _rebalance_dates(config.rebalance)
    cost_rate = config.cost_bps_per_side / 10_000

    committee_rets: list[pd.Series] = []
    rp_rets: list[pd.Series] = []
    weights_history: list[dict] = []
    turnovers: list[float] = []
    held_w: dict[str, float] | None = None      # 漂移后的实际持仓
    held_w_rp: dict[str, float] | None = None
    rebalance_log: list[dict] = []

    for i, d in enumerate(rebal_dates):
        end = rebal_dates[i + 1] if i + 1 < len(rebal_dates) else prices.index[-1]
        record = run_decision("backtest", d.date().isoformat(), config, mode="backtest")
        w = record.target_weights
        w_rp = record.prior.w_strategic
        # 换手 = 新目标 vs 漂移后持仓（真实交易量口径，首期建仓不计）
        turnover = _turnover(w, held_w) if held_w is not None else 0.0
        cost = turnover * cost_rate
        r = _hold_returns(prices, w, d, end)
        if len(r):
            r.iloc[0] -= cost
        committee_rets.append(r)
        r_rp = _hold_returns(prices, w_rp, d, end)
        if held_w_rp is not None and len(r_rp):
            r_rp.iloc[0] -= _turnover(w_rp, held_w_rp) * cost_rate
        rp_rets.append(r_rp)
        turnovers.append(turnover)
        weights_history.append({"date": d.date().isoformat(),
                                "bucket_weights": record.bucket_weights,
                                "decision_id": record.decision_id})
        rebalance_log.append({
            "date": d.date().isoformat(), "decision_id": record.decision_id,
            "turnover": round(turnover, 4), "cost_bps": round(cost * 10_000, 1),
            "views": len(record.bl_inputs["views"]),
            "regime": record.signals_by_id[record.input_signals[2]].values.get("regime"),
            "triggered": [a.rule for a in record.guardrail_actions if a.triggered],
        })
        held_w = _drifted_weights(prices, w, d, end)
        held_w_rp = _drifted_weights(prices, w_rp, d, end)

    committee = pd.concat(committee_rets).sort_index()
    rp_only = pd.concat(rp_rets).sort_index()
    navs = {"committee": (1 + committee).cumprod(),
            "risk_parity_only": (1 + rp_only).cumprod()}

    span = (rebal_dates[0], prices.index[-1])
    for name, bw in _benchmark_weights().items():
        segs = []
        held: dict[str, float] | None = None
        for i, d in enumerate(rebal_dates):
            end = rebal_dates[i + 1] if i + 1 < len(rebal_dates) else prices.index[-1]
            r = _hold_returns(prices, bw, d, end)
            # 静态权重基准每月同样要从漂移持仓调回目标，成本口径与委员会一致
            if held is not None and len(r):
                r.iloc[0] -= _turnover(bw, held) * cost_rate
            segs.append(r)
            held = _drifted_weights(prices, bw, d, end)
        navs[name] = (1 + pd.concat(segs).sort_index()).cumprod()

    cash_nav = navs["cash"]
    metrics = {name: {"strategy": name, **_metrics(nav, cash_nav)}
               for name, nav in navs.items()}

    # walk-forward：按自然年分折，委员会 vs 等权（样本外逐折）
    folds = []
    for year, grp in committee.groupby(committee.index.year):
        eq = navs["bm_equal"].pct_change().dropna()
        eq_y = eq[eq.index.year == year]
        c_ann = float((1 + grp).prod() ** (252 / len(grp)) - 1) if len(grp) > 20 else None
        e_ann = float((1 + eq_y).prod() ** (252 / len(eq_y)) - 1) if len(eq_y) > 20 else None
        if c_ann is not None and e_ann is not None:
            folds.append({"year": int(year), "committee_ann": round(c_ann, 4),
                          "bm_equal_ann": round(e_ann, 4),
                          "beats": c_ann > e_ann})

    drawdown = (navs["committee"] / navs["committee"].cummax() - 1)
    weight_stability = float(np.mean(turnovers[1:])) if len(turnovers) > 1 else 0.0
    result = {
        "span": {"start": span[0].date().isoformat(), "end": span[1].date().isoformat()},
        "rebalance_freq": config.rebalance,
        "dates": [d.date().isoformat() for d in navs["committee"].index],
        "nav": {name: [round(float(v), 5) for v in nav.reindex(navs["committee"].index).ffill()]
                for name, nav in navs.items()},
        "drawdown": [round(float(v), 5) for v in drawdown],
        "metrics": list(metrics.values()),
        "ann_turnover": round(float(np.sum(turnovers)) / max(len(committee) / 252, 1e-9), 3),
        "avg_rebalance_turnover": round(weight_stability, 4),
        "cost_bps_per_side": config.cost_bps_per_side,
        "walk_forward": {"folds": folds,
                         "oos_note": "每个调仓日只使用该日之前可见数据；分折为自然年样本外对比"},
        "weights_history": weights_history,
        "rebalance_log": rebalance_log,
        "note": "Demo 合成数据回测，委员会组合与基准同窗同成本口径",
    }
    return cache_json(key, result)
