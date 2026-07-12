"""API 层：前端所有页面消费同一套决策结果。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from ..domain import universe
from ..domain.backtest import run_backtest
from ..domain.daily import run_daily
from ..domain.guardrails import InfeasibleConstraintsError
from ..domain.market_data import DataError, _prices, load_slice, trading_dates
from ..domain.pipeline import run_decision_cached
from ..domain.spread_desk import desk_report
from ..schemas.config import AllocationConfig
from ..services import store
from ..services.bundle import to_bundle
from ..services import outcomes
from ..services.report import write_decision_report
from ..services.weekly import build_weekly

router = APIRouter(prefix="/api")

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "data" / "demo"
LEGACY = DEMO / "legacy"


@lru_cache(maxsize=1)
def _scenarios() -> dict:
    return json.loads((DEMO / "scenarios.json").read_text(encoding="utf-8"))


def _scenario(scenario_id: str) -> dict:
    for s in _scenarios()["scenarios"]:
        if s["id"] == scenario_id:
            return s
    raise HTTPException(404, f"未知情景: {scenario_id}")


def _legacy(name: str) -> dict:
    path = LEGACY / f"{name}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


class RunRequest(BaseModel):
    scenario_id: str = "recovery_2026"
    config: AllocationConfig | None = None
    asof: str | None = None


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": "demo"}


@router.get("/meta")
def meta() -> dict:
    uni = universe.load_universe()
    return {
        "universe": uni,
        "scenarios": _scenarios(),
        "methods": [
            {"id": "risk_parity", "name": "Risk Parity", "layer": "strategic", "color": "#16806b"},
            {"id": "tsmom", "name": "Time Series Momentum", "layer": "tactical", "color": "#247da8"},
            {"id": "clock", "name": "Merrill Lynch Investment Clock", "layer": "tactical", "color": "#9f6500"},
            {"id": "erp", "name": "Equity Risk Premium", "layer": "tactical", "color": "#aa4168"},
            {"id": "black_litterman", "name": "Black-Litterman Model", "layer": "integration", "color": "#59666f"},
        ],
        "data_span": {"start": trading_dates()[0].date().isoformat(),
                      "end": trading_dates()[-1].date().isoformat()},
    }


@router.get("/config/defaults")
def config_defaults() -> dict:
    return {
        "config": AllocationConfig().model_dump(),
        "personality": _legacy("personality_quiz"),
        "note": "投资性格问卷只透明映射到风险参数与约束，不改变方法话语权",
    }


@router.post("/decisions/run")
def run(req: RunRequest) -> dict:
    scenario = _scenario(req.scenario_id)
    config = req.config or AllocationConfig()
    asof = req.asof or scenario["asof"]
    if pd.Timestamp(asof) > trading_dates()[-1]:
        raise HTTPException(400, "as-of 超出数据范围")
    try:
        record = run_decision_cached(req.scenario_id, asof, config)
    except DataError as exc:  # 核心输入缺失/历史不足：客户端可修正的输入问题
        raise HTTPException(400, detail={"error_type": type(exc).__name__, "message": str(exc)}) from exc
    except InfeasibleConstraintsError as exc:  # 约束集不自洽：配置问题
        raise HTTPException(400, detail={"error_type": "InfeasibleConstraints", "message": str(exc)}) from exc
    # 不可变记录已存在时，以落库版本为准；避免 schema 演进后
    # 同一 decision_id 的 POST 新内存结果与随后 GET 旧记录不一致。
    record = store.save(record)
    outcomes.store_pending(record)
    outcomes.resolve_pending()
    return to_bundle(record)


@router.get("/decisions")
def decisions() -> list[dict]:
    return store.list_index()


@router.get("/decisions/{decision_id}")
def decision(decision_id: str) -> dict:
    record = store.get(decision_id)
    if record is None:
        raise HTTPException(404, "决策记录不存在")
    return to_bundle(record)


@router.get("/decisions/{decision_id}/record")
def decision_record(decision_id: str) -> dict:
    record = store.get(decision_id)
    if record is None:
        raise HTTPException(404, "决策记录不存在")
    return json.loads(record.model_dump_json())


@router.get("/decisions/{decision_id}/report")
def decision_report(decision_id: str) -> Response:
    record = store.get(decision_id)
    if record is None:
        raise HTTPException(404, "决策记录不存在")
    return Response(
        content=write_decision_report(record),
        media_type="text/markdown",
    )


@router.get("/overview")
def overview(scenario_id: str = "recovery_2026") -> dict:
    scenario = _scenario(scenario_id)
    config = AllocationConfig()
    record = run_decision_cached(scenario_id, scenario["asof"], config)
    record = store.save(record)
    bundle = to_bundle(record)
    daily = run_daily(scenario["asof"], config)
    return {
        "scenario": scenario,
        "decision_id": record.decision_id,
        "asof": record.asof,
        "class_weights": record.class_weights,
        "bucket_weights": record.bucket_weights,
        "prior_bucket_weights": bundle["prior"]["bucket_weights"],
        "conclusion": record.conclusion,
        "checks": record.checks,
        "guardrail_actions": bundle["guardrail_actions"],
        "risk": {
            "portfolio_vol": record.checks.get("portfolio_vol"),
            "target_vol": config.target_vol,
            "vol_budget_use": round(record.checks.get("portfolio_vol", 0) / config.target_vol, 3),
        },
        "rebalance": {
            "last": daily["last_rebalance"],
            "rebalanced_today": daily["rebalanced_today"],
            "max_drift": daily["max_drift"],
            "no_trade_band": daily["no_trade_band"],
        },
        "engine_runtime_ms": record.engine_runtime_ms,
        "views_count": len(record.bl_inputs["views"]),
        "history_count": len(store.list_index()),
    }


@router.get("/cockpit")
def cockpit(scenario_id: str = "recovery_2026") -> dict:
    scenario = _scenario(scenario_id)
    config = AllocationConfig()
    asof = pd.Timestamp(scenario["asof"])
    record = run_decision_cached(scenario_id, scenario["asof"], config)
    slice_ = load_slice(scenario["asof"])
    prices = _prices()
    window = prices.loc[:asof]

    snapshot = []
    uni = universe.load_universe()
    for a in uni["assets"]:
        aid = a["id"]
        s = window[aid]
        ytd_start = s[s.index.year == asof.year]
        snapshot.append({
            "id": aid, "name": a["name"], "short_name": a["short_name"],
            "bucket": a["bucket"], "px": round(float(s.iloc[-1]), 2),
            "chg_1w": round(float(s.iloc[-1] / s.iloc[-6] - 1), 4) if len(s) > 6 else None,
            "ytd": round(float(s.iloc[-1] / ytd_start.iloc[0] - 1), 4) if len(ytd_start) else None,
            "vol_3m": round(float((s.pct_change().iloc[-63:]).std() * (252 ** 0.5)), 4),
        })

    bt = run_backtest(config)
    daily = run_daily(scenario["asof"], config)
    committee_nav = bt["nav"]["committee"]
    dd_now = bt["drawdown"][-1] if bt["drawdown"] else 0.0

    events = _legacy("risk_officer_report").get("events", [])
    return {
        "scenario": scenario,
        "asof": scenario["asof"],
        "decision_id": record.decision_id,
        "market_snapshot": snapshot,
        "nav": {"dates": bt["dates"][-252:],
                "committee": committee_nav[-252:],
                "bm_6040": bt["nav"]["bm_6040"][-252:]},
        "current_drawdown": dd_now,
        "risk_budget_use": round(record.checks.get("portfolio_vol", 0) / config.target_vol, 3),
        "portfolio_vol": record.checks.get("portfolio_vol"),
        "target_vol": config.target_vol,
        "drift": {"max_drift": daily["max_drift"], "band": daily["no_trade_band"],
                  "history": daily["history"][-30:]},
        "data_freshness": {
            "prices_asof": slice_.prices.index[-1].date().isoformat(),
            "macro_latest_publish": slice_.macro["publish_date"].max().date().isoformat()
            if len(slice_.macro) else None,
            "macro_staleness_days": record.checks.get("macro_staleness_days"),
        },
        "engine_runtime_ms": record.engine_runtime_ms,
        "closure": {
            "weights": record.checks["weight_sum_assets"],
            "attribution": record.checks["attribution_closure"],
        },
        "events": events,
        "events_note": "事件带来自旧静态页迁移 fixture，仅演示",
        "system_health": {"engine": "ok", "store": "ok",
                          "decisions_stored": len(store.list_index())},
    }


@router.post("/backtest/run")
def backtest(req: RunRequest) -> dict:
    config = req.config or AllocationConfig()
    return run_backtest(config)


@router.get("/daily")
def daily(scenario_id: str = "recovery_2026") -> dict:
    scenario = _scenario(scenario_id)
    return run_daily(scenario["asof"], AllocationConfig())


@router.get("/weekly-report")
def weekly(scenario_id: str = "recovery_2026") -> dict:
    scenario = _scenario(scenario_id)
    return build_weekly(scenario_id, scenario["asof"], AllocationConfig())


@router.get("/spread-desk")
def spread(scenario_id: str = "recovery_2026") -> dict:
    scenario = _scenario(scenario_id)
    report = desk_report(scenario["asof"])
    config = AllocationConfig()
    record = run_decision_cached(scenario_id, scenario["asof"], config)
    report["core_guardrails"] = [a.model_dump() for a in record.guardrail_actions]
    report["core_class_weights"] = record.class_weights
    legacy_risk = _legacy("risk_officer_report")
    report["events"] = legacy_risk.get("events", [])
    report["legacy_note"] = "宏观事件日历来自旧静态页迁移 fixture；策略数字由当前引擎从价格面板现算"
    return report


@router.get("/outcomes")
def outcomes_view(backfill: bool = False) -> dict:
    """决策-结果闭环账本：命中率与 α 统计。backfill=true 时用回测逐期决策回填全历史。"""
    if backfill:
        outcomes.backfill_from_backtest(AllocationConfig())
    outcomes.resolve_pending()
    return outcomes.summarize()


@router.get("/scenarios/compare")
def compare(base: str = "recovery_2026", other: str = "stagflation_2022") -> dict:
    config = AllocationConfig()
    res = {}
    for key, sid in [("base", base), ("other", other)]:
        sc = _scenario(sid)
        record = run_decision_cached(sid, sc["asof"], config)
        record = store.save(record)
        res[key] = to_bundle(record)
    diff = {b: round(res["base"]["bucket_weights"][b] - res["other"]["bucket_weights"][b], 6)
            for b in res["base"]["bucket_weights"]}
    return {**res, "bucket_diff": diff}
