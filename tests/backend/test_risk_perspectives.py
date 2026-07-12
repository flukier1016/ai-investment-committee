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

    # 两代理都从落库的 6 位明细权重派生并落回 6 位小数（与权重同精度），
    # 桶级 prior 取 prior.w_strategic 的桶聚合，而非全精度 attribution.prior。
    expected_asset_turnover = round(0.5 * sum(
        abs(record.target_weights[asset_id] - record.prior.w_strategic[asset_id])
        for asset_id in sorted(record.target_weights)
    ), 6)
    bucket_prior = universe.aggregate_to_buckets(record.prior.w_strategic)
    expected_bucket_shift = round(0.5 * sum(
        abs(round(record.bucket_weights[bucket_id], 6) - round(bucket_prior[bucket_id], 6))
        for bucket_id in sorted(record.bucket_weights)
    ), 6)
    assert neutral["metrics"]["asset_turnover_proxy"] == expected_asset_turnover
    assert neutral["metrics"]["bucket_shift"] == expected_bucket_shift
    assert "目标相对 Risk Parity 战略先验" in neutral["text"]


def test_neutral_derivation_is_stable_at_persisted_precision(record):
    """跨 runner 稳定性防线：换手代理/桶级偏离/可解释比例必须只由落库的 6 位
    小数权重派生，逐字节稳定。

    历史事故：中性视角把 attribution.prior（全精度桶级聚合再舍入）与桶级 target
    相除，1e-7 级求解器硬件差异经近似相等两量的比值放大成 1e-5 漂移（如
    0.997117 vs 0.997106），与只存 6 位的固定 fixture 精确 == 时在部分 GitHub
    Actions runner 上偶发失败（提交 dce9b57 的 CI 曾中招，重跑即绿）。
    """
    base = build_risk_perspectives(record)[2]
    m = base["metrics"]

    # 1) 报告的派生量本身就落在 6 位精度，且可解释比例/桶内残余可由报告的两代理
    #    精确复算——消费方无需接触任何 6 位以下中间量。
    for key in ("asset_turnover_proxy", "bucket_shift",
                "explainable_share", "intra_bucket_churn"):
        assert m[key] == round(m[key], 6)
    assert base["value"] == m["explainable_share"]
    assert m["explainable_share"] == round(
        m["bucket_shift"] / m["asset_turnover_proxy"], 6)
    assert m["intra_bucket_churn"] == round(
        max(m["asset_turnover_proxy"] - m["bucket_shift"], 0.0), 6)

    # 2) 桶级偏离只认 6 位 prior.w_strategic 的聚合，等于用 attribution.prior 会
    #    把全精度噪声带入。把每个桶的 attribution.prior 污染 1e-6（复刻噪声来源），
    #    派生视角必须逐字节不变。
    poisoned = record.model_copy(deep=True)
    for i, bucket_id in enumerate(sorted(poisoned.attribution)):
        if "prior" in poisoned.attribution[bucket_id]:
            poisoned.attribution[bucket_id]["prior"] = round(
                poisoned.attribution[bucket_id]["prior"]
                + (1e-6 if i % 2 == 0 else -1e-6), 9)
    assert build_risk_perspectives(poisoned)[2] == base

    # 3) bucket_weights 落库到 9 位，其 6 位以下尾数不得进入派生：注入 <5e-7 抖动
    #    （模拟求解器硬件差异残留在 6 位以下）后派生视角逐字节一致——派生把桶级
    #    target 先落回 6 位再比较。
    twin = record.model_copy(deep=True)
    twin.bucket_weights.update({
        b: v + (4e-7 if i % 2 == 0 else -4e-7)
        for i, (b, v) in enumerate(sorted(record.bucket_weights.items()))})
    assert build_risk_perspectives(twin)[2] == base


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
