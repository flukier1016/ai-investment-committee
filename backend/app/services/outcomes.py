"""决策-结果闭环账本（outcomes analysis）。

借鉴 TradingAgents 的 pending→resolved 决策日志生命周期，全部确定性代码：
1. 每次决策落库时写一条 pending 结果条目（幂等，decision_id 为键）；
2. 任意后续运行调用 resolve_pending()：对「as-of + 持有期」已有价格数据的
   条目，用 point-in-time 价格解算——组合实现收益、vs 等权/60·40 基准 α、
   逐观点方向命中、宏观象限命中；
3. JSON 原子写（tmp + os.replace），永不删除 pending；
4. backfill_from_backtest() 用 walk-forward 回测的逐期决策一次性回填全历史，
   立即得到有统计意义的命中率。

这满足 V3 第 7.4 节 outcomes analysis / 运行时监控「信号命中率」维度
（SR 2026-02 三项核心能力之一）。无任何 LLM 参与。
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from ..domain import universe
from ..domain.market_data import _prices, trading_dates
from ..schemas.decision import DecisionRecord

ROOT = Path(__file__).resolve().parents[3]
OUTCOMES_PATH = ROOT / "data" / "runs" / "outcomes.json"

HORIZON_DAYS = 21  # 结果解算持有期（约一个月）

# 象限 → 受益资产桶（与 signals.REGIME_TILTS 的正向腿一致）
REGIME_FAVORED = {
    "复苏": ["cn_equity", "commodity"],
    "过热": ["commodity"],
    "滞胀": ["commodity"],
    "衰退": ["cn_bond", "foreign_bond"],
}


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 唯一临时名：固定名会被并发写者互相 os.replace 掉（CI 竞态回归）
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _load() -> dict:
    if not OUTCOMES_PATH.exists():
        return {"entries": {}}
    try:
        return json.loads(OUTCOMES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"entries": {}}


def _bench_weights() -> dict[str, dict[str, float]]:
    eq = [a for a in universe.risky_asset_ids()
          if universe.class_of_bucket()[universe.bucket_of()[a]] == "equity"]
    bd = [a for a in universe.risky_asset_ids()
          if universe.class_of_bucket()[universe.bucket_of()[a]] == "bond"]
    risky = universe.risky_asset_ids()
    return {
        "bm_equal": {a: 1.0 / len(risky) for a in risky},
        "bm_6040": {**{a: 0.6 / len(eq) for a in eq}, **{a: 0.4 / len(bd) for a in bd}},
    }


def _period_return(weights: dict[str, float], start: pd.Timestamp, end: pd.Timestamp,
                   prices: pd.DataFrame) -> float:
    rel = prices.loc[end] / prices.loc[start]
    return float(sum(w * (float(rel[a]) - 1.0) for a, w in weights.items()))


def _view_tilt_sign(view: dict, pi: dict[str, float]) -> int:
    """观点方向 = sign(Q − P·π)，即信号倾斜的方向（Q 锚定 π 后的净判断）。"""
    anchor = sum(w * pi.get(a, 0.0) for a, w in view["P"].items())
    tilt = view["Q"] - anchor
    return 1 if tilt > 0 else (-1 if tilt < 0 else 0)


def make_pending(record: DecisionRecord) -> dict:
    """从 DecisionRecord 提取解算所需的最小快照（不依赖记录文件长期存在）。"""
    clock_sig = next((s for s in record.signals_by_id.values() if s.method == "clock"), None)
    regime = None
    if clock_sig is not None and clock_sig.view_type != "abstain":
        regime = clock_sig.values.get("regime")
    return {
        "decision_id": record.decision_id,
        "scenario_id": record.scenario_id,
        "mode": record.mode,
        "asof": record.asof[:10],
        "status": "pending",
        "target_weights": record.target_weights,
        "regime": regime,
        "views": [
            {"view_id": v["view_id"],
             "method": record.signals_by_id[v["source_signal_ids"][0]].method
             if v["source_signal_ids"] and v["source_signal_ids"][0] in record.signals_by_id
             else "unknown",
             "P": v["P"], "Q": v["Q"], "lambda": v.get("lambda", 0.0),
             "tilt_sign": _view_tilt_sign(v, record.prior.pi)}
            for v in record.bl_inputs["views"]
        ],
    }


def store_pending(record: DecisionRecord) -> None:
    """决策落库后追加 pending 条目（幂等：已存在即跳过，绝不覆盖已解算条目）。"""
    data = _load()
    if record.decision_id in data["entries"]:
        return
    data["entries"][record.decision_id] = make_pending(record)
    _atomic_write(OUTCOMES_PATH, data)


def _resolve_entry(entry: dict, prices: pd.DataFrame,
                   dates: pd.DatetimeIndex) -> dict | None:
    """条目到期则解算；数据不足返回 None（保持 pending）。"""
    asof = pd.Timestamp(entry["asof"])
    idx = dates.searchsorted(asof, side="right") - 1
    if idx < 0 or idx + HORIZON_DAYS >= len(dates):
        return None
    start, end = dates[idx], dates[idx + HORIZON_DAYS]

    port = _period_return(entry["target_weights"], start, end, prices)
    bench = {name: _period_return(w, start, end, prices)
             for name, w in _bench_weights().items()}

    # 逐观点方向命中：P 加权实现收益（绝对观点减等权基准）符号 vs 观点倾斜符号
    rel = prices.loc[end] / prices.loc[start] - 1.0
    view_hits = []
    for v in entry["views"]:
        if v["tilt_sign"] == 0 or v.get("lambda", 0.0) == 0.0:
            continue  # 未采纳/中性观点不计命中
        p_ret = float(sum(w * float(rel[a]) for a, w in v["P"].items()))
        p_sum = sum(v["P"].values())
        realized = p_ret - p_sum * bench["bm_equal"]  # 绝对观点做超额，相对观点 p_sum≈0 不变
        hit = (realized > 0) == (v["tilt_sign"] > 0)
        view_hits.append({"view_id": v["view_id"], "method": v["method"],
                          "tilt_sign": v["tilt_sign"],
                          "realized_excess": round(realized, 5), "hit": hit})

    regime_hit = None
    if entry.get("regime") in REGIME_FAVORED:
        favored = [a for b in REGIME_FAVORED[entry["regime"]]
                   for a in universe.assets_in_bucket(b)]
        favored_ret = float(np.mean([float(rel[a]) for a in favored]))
        regime_hit = favored_ret > bench["bm_equal"]

    return {
        **entry,
        "status": "resolved",
        "resolved_span": {"start": start.date().isoformat(), "end": end.date().isoformat()},
        "realized_return": round(port, 5),
        "benchmark_returns": {k: round(v, 5) for k, v in bench.items()},
        "alpha_vs_equal": round(port - bench["bm_equal"], 5),
        "alpha_vs_6040": round(port - bench["bm_6040"], 5),
        "view_hits": view_hits,
        "regime_hit": regime_hit,
    }


def resolve_pending() -> int:
    """解算所有到期 pending 条目，返回解算数量。幂等：已 resolved 不重算。"""
    data = _load()
    prices = _prices()
    dates = trading_dates()
    resolved = 0
    for did, entry in data["entries"].items():
        if entry.get("status") != "pending":
            continue
        result = _resolve_entry(entry, prices, dates)
        if result is not None:
            data["entries"][did] = result
            resolved += 1
    if resolved:
        _atomic_write(OUTCOMES_PATH, data)
    return resolved


def backfill_from_backtest(config) -> int:
    """用回测逐期决策回填结果账本（首版即得全历史命中率）。"""
    from ..domain.backtest import _rebalance_dates
    from ..domain.pipeline import run_decision_cached

    data = _load()
    added = 0
    for d in _rebalance_dates(config.rebalance):
        record = run_decision_cached("backtest", d.date().isoformat(), config, mode="backtest")
        if record.decision_id not in data["entries"]:
            data["entries"][record.decision_id] = make_pending(record)
            added += 1
    if added:
        _atomic_write(OUTCOMES_PATH, data)
    resolve_pending()
    return added


def summarize() -> dict:
    """聚合统计：整体与分方法命中率、平均 α、象限命中率。"""
    data = _load()
    entries = list(data["entries"].values())
    resolved = [e for e in entries if e.get("status") == "resolved"]
    pending = [e for e in entries if e.get("status") == "pending"]

    method_stats: dict[str, dict] = {}
    for e in resolved:
        for h in e.get("view_hits", []):
            s = method_stats.setdefault(h["method"], {"hits": 0, "total": 0})
            s["total"] += 1
            s["hits"] += 1 if h["hit"] else 0
    for s in method_stats.values():
        s["hit_rate"] = round(s["hits"] / s["total"], 4) if s["total"] else None

    regime_calls = [e for e in resolved if e.get("regime_hit") is not None]
    alphas_eq = [e["alpha_vs_equal"] for e in resolved]
    alphas_6040 = [e["alpha_vs_6040"] for e in resolved]
    return {
        "horizon_days": HORIZON_DAYS,
        "resolved_count": len(resolved),
        "pending_count": len(pending),
        "avg_alpha_vs_equal": round(float(np.mean(alphas_eq)), 5) if alphas_eq else None,
        "avg_alpha_vs_6040": round(float(np.mean(alphas_6040)), 5) if alphas_6040 else None,
        "alpha_win_rate_vs_equal": round(float(np.mean([a > 0 for a in alphas_eq])), 4)
        if alphas_eq else None,
        "method_hit_rates": method_stats,
        "regime_hit_rate": round(float(np.mean([e["regime_hit"] for e in regime_calls])), 4)
        if regime_calls else None,
        "regime_calls": len(regime_calls),
        "entries": sorted(resolved, key=lambda e: e["asof"], reverse=True)[:24],
        "pending": [{"decision_id": e["decision_id"], "asof": e["asof"],
                     "scenario_id": e["scenario_id"]} for e in pending],
        "note": f"持有期 {HORIZON_DAYS} 个交易日；观点命中 = P 加权超额收益方向 vs 观点倾斜方向；"
                "全部由确定性代码从 point-in-time 价格解算。",
    }
