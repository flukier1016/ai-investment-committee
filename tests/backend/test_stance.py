"""五档立场单一口径防线。

防止阈值边界漂移、立场脱离落库 prior、旧记录 schema 断裂，以及周报/前端/
结果账本各自重算出不同立场；同时锁定中性不计分、零超额不算命中的结果口径。
"""

from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from app.domain import universe
from app.domain import stance as stance_module
from app.domain.market_data import _prices, trading_dates
from app.domain.pipeline import run_decision, run_decision_cached
from app.domain.stance import (
    STANCE_5_TIER,
    STANCE_NEUTRAL,
    bucket_stances_from_weights,
    resolve_bucket_stances,
    stance_from_delta,
)
from app.schemas.decision import DecisionRecord
from app.services import outcomes, store
from app.services.bundle import to_bundle
from app.services.weekly import build_weekly


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (math.nextafter(0.02, math.inf), "显著超配"),
        (0.02, "显著超配"),
        (math.nextafter(0.02, 0.0), "超配"),
        (math.nextafter(0.004, math.inf), "超配"),
        (0.004, "超配"),
        (math.nextafter(0.004, 0.0), "中性"),
        (math.nextafter(-0.004, 0.0), "中性"),
        (-0.004, "低配"),
        (math.nextafter(-0.004, -math.inf), "低配"),
        (math.nextafter(-0.02, 0.0), "低配"),
        (-0.02, "显著低配"),
        (math.nextafter(-0.02, -math.inf), "显著低配"),
    ],
)
def test_four_stance_thresholds_and_both_sides(delta, expected):
    assert stance_from_delta(delta) == expected


@pytest.mark.parametrize("delta", [math.inf, -math.inf, math.nan])
def test_non_finite_delta_fails_loud(delta):
    with pytest.raises(ValueError, match="有限数"):
        stance_from_delta(delta)


@pytest.mark.parametrize(
    ("prior", "target", "expected"),
    [
        (0.1, 0.104, "超配"),
        (0.1, 0.12, "显著超配"),
        (0.1, 0.096, "低配"),
        (0.1, 0.08, "显著低配"),
    ],
)
def test_persisted_weight_subtraction_keeps_exact_boundaries(prior, target, expected):
    assert bucket_stances_from_weights(
        {"bucket": prior}, {"bucket": target}) == {"bucket": expected}


def test_complete_stored_stances_are_consumed_without_recalculation(monkeypatch):
    stored = {f"bucket_{i}": stance for i, stance in enumerate(STANCE_5_TIER)}

    def fail_recalculation(*_args, **_kwargs):
        raise AssertionError("完整落库立场不应重算")

    monkeypatch.setattr(
        stance_module, "bucket_stances_from_weights", fail_recalculation)
    assert resolve_bucket_stances(
        stored,
        {bucket: 0.1 for bucket in stored},
        {bucket: 0.9 for bucket in stored},
        stored,
    ) == stored


def test_record_has_seven_stances_from_persisted_prior(record):
    prior = universe.aggregate_to_buckets(record.prior.w_strategic)
    expected = bucket_stances_from_weights(
        prior, record.bucket_weights, universe.bucket_ids())

    assert list(record.bucket_stances) == universe.bucket_ids()
    assert len(record.bucket_stances) == 7
    assert record.bucket_stances == expected
    assert set(record.bucket_stances.values()).issubset(STANCE_5_TIER)
    assert "显著超配商品" in record.conclusion
    assert "显著低配外汇" in record.conclusion


def test_direct_and_cached_paths_share_canonical_decision_id(config):
    direct = run_decision("stance_determinism", "2026-07-09", config)
    cached = run_decision_cached("stance_determinism", "2026-07-09", config)

    assert direct.config == cached.config
    assert direct.decision_id == cached.decision_id
    assert direct.target_weights == cached.target_weights
    assert direct.bucket_stances == cached.bucket_stances


def test_old_decision_record_defaults_and_consumers_share_central_stances(record, config):
    payload = json.loads(record.model_dump_json())
    payload.pop("bucket_stances")
    legacy = DecisionRecord.model_validate(payload)
    assert legacy.bucket_stances == {}

    expected = record.bucket_stances
    assert to_bundle(record)["bucket_stances"] == expected
    assert to_bundle(legacy)["bucket_stances"] == expected

    weekly = build_weekly("recovery_2026", "2026-07-09", config)
    assert weekly["bucket_stances"] == expected
    for bucket, stance in expected.items():
        if stance != STANCE_NEUTRAL:
            assert f"{weekly['bucket_stances'][bucket]}（" in weekly["markdown"]


def test_bucket_outcome_skips_neutral_and_zero_excess_is_not_hit():
    rel = pd.Series(0.0, index=universe.asset_ids())
    entry = {
        "bucket_stances": {
            "cn_equity": "显著超配",
            "foreign_equity": STANCE_NEUTRAL,
            "cash": "显著低配",
        }
    }

    hits = outcomes._bucket_stance_hits(entry, rel, benchmark_return=0.0)

    assert {item["bucket"] for item in hits} == {"cn_equity", "cash"}
    assert all(item["realized_excess"] == 0.0 for item in hits)
    assert all(item["hit"] is False for item in hits)


def test_bucket_outcome_direction_and_equal_weight_excess_math():
    benchmark = 0.01
    rel = pd.Series(benchmark, index=universe.asset_ids())
    cases = {
        "cn_equity": ("超配", 0.03, True),
        "foreign_equity": ("显著超配", -0.01, False),
        "cn_bond": ("低配", -0.01, True),
        "foreign_bond": ("显著低配", 0.03, False),
    }
    for bucket, (_, bucket_return, _) in cases.items():
        members = universe.assets_in_bucket(bucket)
        # 同桶所有标的同收益，其等权平均必须等于 bucket_return。
        rel.loc[members] = bucket_return

    hits = outcomes._bucket_stance_hits(
        {"bucket_stances": {bucket: case[0] for bucket, case in cases.items()}},
        rel,
        benchmark_return=benchmark,
    )
    by_bucket = {item["bucket"]: item for item in hits}
    for bucket, (_, bucket_return, expected_hit) in cases.items():
        assert by_bucket[bucket]["realized_excess"] == pytest.approx(
            bucket_return - benchmark)
        assert by_bucket[bucket]["hit"] is expected_hit


def test_stance_summary_has_all_tiers_and_ignores_legacy_missing_fields(tmp_path, monkeypatch):
    path = tmp_path / "outcomes.json"
    monkeypatch.setattr(outcomes, "OUTCOMES_PATH", path)
    outcomes._atomic_write(path, {"entries": {
        "with_stances": {
            "decision_id": "with_stances", "scenario_id": "test", "asof": "2022-01-03",
            "status": "resolved", "alpha_vs_equal": 0.01, "alpha_vs_6040": 0.0,
            "view_hits": [], "regime_hit": None,
            "bucket_stance_hits": [
                {"stance": "显著超配", "hit": True},
                {"stance": "超配", "hit": False},
                {"stance": STANCE_NEUTRAL, "hit": True},
            ],
        },
        "legacy": {
            "decision_id": "legacy", "scenario_id": "test", "asof": "2022-01-04",
            "status": "resolved", "alpha_vs_equal": 0.0, "alpha_vs_6040": 0.0,
            "view_hits": [], "regime_hit": None,
        },
    }})

    summary = outcomes.summarize()

    assert tuple(summary["stance_hit_rates"]) == STANCE_5_TIER
    assert summary["stance_hit_rates"]["显著超配"] == {
        "hits": 1, "total": 1, "hit_rate": 1.0}
    assert summary["stance_hit_rates"]["超配"] == {
        "hits": 0, "total": 1, "hit_rate": 0.0}
    assert summary["stance_hit_rates"][STANCE_NEUTRAL] == {
        "hits": 0, "total": 0, "hit_rate": None}
    assert summary["bucket_stance_hit_rate"] == 0.5


def test_old_resolved_entry_is_enriched_without_rewriting_old_fields(
    tmp_path, monkeypatch, record_stagflation,
):
    path = tmp_path / "outcomes.json"
    monkeypatch.setattr(outcomes, "OUTCOMES_PATH", path)

    pending = outcomes.make_pending(record_stagflation)
    resolved = outcomes._resolve_entry(pending, _prices(), trading_dates())
    assert resolved is not None
    resolved["bucket_stances"] = {
        "cn_equity": record_stagflation.bucket_stances["cn_equity"]}
    resolved.pop("bucket_stance_hits")
    resolved["legacy_marker"] = {"must": "survive"}
    old_fields = json.loads(json.dumps(resolved, ensure_ascii=False))
    outcomes._atomic_write(path, {"entries": {record_stagflation.decision_id: resolved}})

    outcomes.store_pending(record_stagflation)
    assert outcomes.resolve_pending() == 0  # 已 resolved，只补字段，不重复计为新解算

    enriched = json.loads(path.read_text(encoding="utf-8"))["entries"][record_stagflation.decision_id]
    for key, value in old_fields.items():
        if key == "bucket_stances":
            continue
        assert enriched[key] == value
    assert enriched["bucket_stances"] == record_stagflation.bucket_stances
    assert enriched["bucket_stance_hits"]
    assert all(item["stance"] != STANCE_NEUTRAL for item in enriched["bucket_stance_hits"])


def test_api_reuses_immutable_legacy_record_consistently(tmp_path, monkeypatch, record):
    """同 decision_id 已有旧记录时，POST/GET 必须同源；立场仅在 bundle 中中央补算。"""
    from fastapi.testclient import TestClient

    from app.main import app

    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(store, "RUNS", runs)
    monkeypatch.setattr(outcomes, "OUTCOMES_PATH", tmp_path / "outcomes.json")

    legacy_payload = json.loads(record.model_dump_json())
    legacy_payload.pop("bucket_stances")
    legacy_payload["conclusion"] = "旧版不可变结论。"
    (runs / f"{record.decision_id}.json").write_text(
        json.dumps(legacy_payload, ensure_ascii=False), encoding="utf-8")

    client = TestClient(app)
    posted = client.post("/api/decisions/run", json={"scenario_id": "recovery_2026"}).json()
    fetched = client.get(f"/api/decisions/{record.decision_id}").json()
    raw = client.get(f"/api/decisions/{record.decision_id}/record").json()

    assert posted["conclusion"] == fetched["conclusion"] == "旧版不可变结论。"
    assert posted["bucket_stances"] == fetched["bucket_stances"] == record.bucket_stances
    assert raw["bucket_stances"] == {}  # 原记录不改写，默认值保证可加载
