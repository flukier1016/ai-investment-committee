"""日更驾驶舱：模拟最近 N 个交易日的每日运行。

每日：重算理想权重（同生产管线）→ 与当前持仓比较桶级偏离 →
超过免交易带才调仓，否则持仓随价格漂移。结果按输入指纹缓存。
"""

from __future__ import annotations

import hashlib
import json

import pandas as pd

from ..schemas.config import AllocationConfig
from . import universe
from .market_data import _prices, trading_dates
from .pipeline import run_decision_cached as run_decision

SIM_DAYS = 60


def _drift_weights(prices: pd.DataFrame, weights: dict[str, float],
                   d0: pd.Timestamp, d1: pd.Timestamp) -> dict[str, float]:
    """持仓从 d0 漂移到 d1（价格变化，不交易）。"""
    rel = prices.loc[d1] / prices.loc[d0]
    drifted = {a: w * float(rel[a]) for a, w in weights.items()}
    total = sum(drifted.values())
    return {a: w / total for a, w in drifted.items()}


def run_daily(scenario_asof: str, config: AllocationConfig) -> dict:
    from ..services.store import cache_json
    key = "daily_" + hashlib.sha256(
        (scenario_asof + json.dumps(config.fingerprint_payload(), sort_keys=True)).encode()
    ).hexdigest()[:12]
    cached = cache_json(key)
    if cached is not None:
        return cached

    prices = _prices()
    dates = trading_dates()
    dates = dates[dates <= pd.Timestamp(scenario_asof)][-SIM_DAYS:]
    band = config.no_trade_band

    held: dict[str, float] | None = None
    last_rebalance: str | None = None
    history: list[dict] = []
    latest_ideal: dict[str, float] = {}
    latest_decision_id = ""

    for i, d in enumerate(dates):
        record = run_decision("daily", d.date().isoformat(), config, mode="daily")
        ideal = record.target_weights
        latest_ideal = ideal
        latest_decision_id = record.decision_id
        if held is None:
            held = dict(ideal)
            last_rebalance = d.date().isoformat()
            rebalanced = True
            max_drift = 0.0
        else:
            held = _drift_weights(prices, held, dates[i - 1], d)
            ideal_b = universe.aggregate_to_buckets(ideal)
            held_b = universe.aggregate_to_buckets(held)
            max_drift = max(abs(ideal_b[b] - held_b[b]) for b in ideal_b)
            rebalanced = max_drift > band
            if rebalanced:
                held = dict(ideal)
                last_rebalance = d.date().isoformat()
        drift_total = sum(abs(universe.aggregate_to_buckets(ideal)[b]
                              - universe.aggregate_to_buckets(held)[b])
                          for b in universe.bucket_ids()) / 2
        history.append({
            "date": d.date().isoformat(),
            "max_drift": round(max_drift, 5),
            "drift": round(drift_total, 5),
            "rebalanced": rebalanced,
            "decision_id": record.decision_id,
        })

    held_b = universe.aggregate_to_buckets(held or {})
    ideal_b = universe.aggregate_to_buckets(latest_ideal)
    result = {
        "asof": dates[-1].date().isoformat(),
        "no_trade_band": band,
        "rebalance_freq": config.rebalance,
        "ideal_weights": {a: round(w, 6) for a, w in latest_ideal.items()},
        "held_weights": {a: round(w, 6) for a, w in (held or {}).items()},
        "ideal_buckets": ideal_b,
        "held_buckets": held_b,
        "max_drift": history[-1]["max_drift"],
        "rebalanced_today": history[-1]["rebalanced"],
        "last_rebalance": last_rebalance,
        "rebalance_count": sum(1 for h in history if h["rebalanced"]),
        "latest_decision_id": latest_decision_id,
        "history": history,
        "note": f"最近 {len(history)} 个交易日 Demo 模拟：每日重算理想权重，桶级偏离超过免交易带 {band:.1%} 才调仓",
    }
    return cache_json(key, result)
