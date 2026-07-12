"""风控三视角防线。

防止人格卡自行造数、前端重算或反向影响权重：三个纯函数只解释落库事实；
上限复用风控 cap；“换手”始终标明是目标相对战略底仓的理论代理。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain import universe
from app.domain.pipeline import run_decision
from app.schemas.config import AllocationConfig
from app.services.bundle import to_bundle
from app.services.committee import (
    aggressive_risk_perspective,
    build_committee_review,
    build_risk_perspectives,
    conservative_risk_perspective,
    neutral_risk_perspective,
)


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def record():
    return run_decision("recovery_2026", "2026-07-09", AllocationConfig())


def test_aggressive_pure_function_uses_only_the_hard_budget_boundary():
    remaining = aggressive_risk_perspective(0.04, 0.08)
    at_budget = aggressive_risk_perspective(0.08, 0.08)
    over = aggressive_risk_perspective(0.081, 0.08)

    assert remaining["assessment"] == "capacity_remaining"
    assert remaining["value"] == 0.5
    assert remaining["metrics"] == {
        "portfolio_vol": 0.04,
        "target_vol": 0.08,
        "utilization": 0.5,
        "remaining_vol": 0.04,
        "remaining_budget_share": 0.5,
    }
    assert at_budget["assessment"] == "at_budget"
    assert over["assessment"] == "over_budget"
    with pytest.raises(ValueError, match="portfolio_vol"):
        aggressive_risk_perspective(0.01, 0.0)


def test_conservative_pure_function_preserves_headroom_binding_and_breach():
    refs = {"current": "target_weights.asset", "limit": "config.single_asset_cap"}
    room = conservative_risk_perspective(
        subject="测试资产上限", current=0.08, limit=0.10, refs=refs)
    binding = conservative_risk_perspective(
        subject="测试资产上限", current=0.10, limit=0.10, refs=refs)
    breach = conservative_risk_perspective(
        subject="测试资产上限", current=0.11, limit=0.10, refs=refs)

    assert room["assessment"] == "headroom" and room["value"] == 0.02
    assert binding["assessment"] == "binding" and binding["value"] == 0.0
    assert breach["assessment"] == "breach" and breach["value"] == -0.01
    assert breach["refs"] == refs


def test_neutral_pure_function_exposes_proxy_not_realized_turnover():
    no_turnover = neutral_risk_perspective(0.0, 0.0)
    cross_bucket = neutral_risk_perspective(0.10, 0.10)
    mixed = neutral_risk_perspective(0.10, 0.06)
    inside_bucket = neutral_risk_perspective(0.10, 0.0)
    inconsistent = neutral_risk_perspective(0.10, 0.100002)

    assert no_turnover["assessment"] == "no_turnover"
    assert cross_bucket["assessment"] == "fully_explained"
    assert mixed["assessment"] == "partly_explained"
    assert mixed["metrics"]["explainable_share"] == 0.6
    assert mixed["metrics"]["intra_bucket_churn"] == 0.04
    assert inside_bucket["assessment"] == "intra_bucket_only"
    assert inconsistent["assessment"] == "inconsistent"
    assert inconsistent["value"] > 1.0, "不一致记录不得静默截到 100%"
    for item in (no_turnover, cross_bucket, mixed, inside_bucket, inconsistent):
        assert "不是实际成交换手" in item["text"]
        assert item["refs"]["strategic_prior"] == "prior.w_strategic"


def test_record_derivation_is_deterministic_exact_and_non_mutating(record):
    before = record.model_dump_json()
    first = build_risk_perspectives(record)
    second = build_risk_perspectives(record)

    assert first == second
    assert record.model_dump_json() == before
    assert [item["role"] for item in first] == [
        "aggressive", "conservative", "neutral"]
    assert [item["metric"] for item in first] == [
        "vol_budget_utilization", "cap_headroom", "turnover_proportionality"]

    aggressive, conservative, neutral = first
    assert aggressive["value"] == pytest.approx(
        record.checks["portfolio_vol"] / record.config["target_vol"], abs=1e-6)
    assert conservative["metrics"]["current"] + conservative["metrics"]["headroom"] \
        == pytest.approx(conservative["metrics"]["limit"], abs=1e-6)

    expected_asset_turnover = 0.5 * sum(
        abs(record.target_weights[asset_id] - record.prior.w_strategic[asset_id])
        for asset_id in sorted(record.target_weights)
    )
    expected_bucket_shift = 0.5 * sum(
        abs(record.bucket_weights[bucket_id]
            - record.attribution[bucket_id]["prior"])
        for bucket_id in sorted(record.bucket_weights)
    )
    assert neutral["metrics"]["asset_turnover_proxy"] == pytest.approx(
        expected_asset_turnover, abs=1e-6)
    assert neutral["metrics"]["bucket_shift"] == pytest.approx(
        expected_bucket_shift, abs=1e-6)
    assert "目标相对 Risk Parity 战略先验" in neutral["text"]


def test_tightest_limit_reuses_configured_asset_risk_cap(record):
    asset_id = "csi300"
    current = record.target_weights[asset_id]
    configured_cap = current - 0.001
    config = {**record.config, "risk_caps_wan": {
        asset_id: configured_cap * record.config["principal"] / 10_000,
    }}
    constrained = record.model_copy(update={"config": config})

    perspective = build_risk_perspectives(constrained)[1]
    assert perspective["metrics"]["subject"].startswith("沪深300")
    assert perspective["metrics"]["current"] == current
    assert perspective["metrics"]["limit"] == pytest.approx(configured_cap, abs=1e-6)
    assert perspective["value"] == pytest.approx(-0.001, abs=1e-6)
    assert perspective["assessment"] == "breach"
    assert perspective["refs"]["limit"] == f"config.risk_caps_wan.{asset_id}"

    cash_cap = record.target_weights["cash"] - 0.001
    cash_config = {**record.config, "risk_caps_wan": {
        "cash": cash_cap * record.config["principal"] / 10_000,
    }}
    cash_perspective = build_risk_perspectives(
        record.model_copy(update={"config": cash_config}))[1]
    assert cash_perspective["metrics"]["subject"].startswith("现金")
    assert cash_perspective["metrics"]["limit"] == pytest.approx(cash_cap, abs=1e-6)
    assert cash_perspective["refs"]["limit"] == "config.risk_caps_wan.cash"


def test_committee_and_bundle_add_views_without_changing_record_or_verdict(record):
    before = json.loads(record.model_dump_json())
    review = build_committee_review(record)
    bundle = to_bundle(record)

    assert bundle["committee_review"] == review
    assert len(review["risk_perspectives"]) == 3
    assert review["verdict"]["score"]["views_total"] == len(record.bl_inputs["views"])
    assert review["verdict"]["score"]["closure_ok"] is True
    assert json.loads(record.model_dump_json()) == before
    assert set(record.target_weights) == set(record.prior.w_strategic) \
        == set(universe.asset_ids())
    assert "risk_perspectives" not in before, "派生点评不得污染 DecisionRecord"
    sample = json.loads(
        (ROOT / "docs/api_samples/decision_bundle.json").read_text(encoding="utf-8"))
    assert sample["committee_review"]["risk_perspectives"] == review["risk_perspectives"]
    assert sample["committee_review"]["note"] == review["note"]

    corrupted = record.model_copy(deep=True)
    corrupted.attribution["cash"].pop("prior")
    with pytest.raises(ValueError, match="缺少桶级 prior"):
        build_risk_perspectives(corrupted)
