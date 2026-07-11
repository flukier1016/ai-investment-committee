"""决策-结果闭环账本 + 委员会正反检验。

对应 V3 第 7.4 节 outcomes analysis 与运行时监控「信号命中率」维度。
"""

import pytest

from app.domain.pipeline import run_decision
from app.schemas.config import AllocationConfig
from app.services import outcomes
from app.services.committee import build_committee_review


@pytest.fixture(scope="module")
def isolated_outcomes(tmp_path_factory):
    path = tmp_path_factory.mktemp("outcomes") / "outcomes.json"
    original = outcomes.OUTCOMES_PATH
    outcomes.OUTCOMES_PATH = path
    yield path
    outcomes.OUTCOMES_PATH = original


@pytest.fixture(scope="module")
def config():
    return AllocationConfig()


def test_pending_then_resolve_lifecycle(isolated_outcomes, config):
    # 历史情景（其后有充足价格数据）→ 可解算
    record = run_decision("stagflation_2022", "2022-10-14", config)
    outcomes.store_pending(record)
    # 幂等：重复写不产生第二条
    outcomes.store_pending(record)
    assert outcomes.resolve_pending() == 1
    summary = outcomes.summarize()
    assert summary["resolved_count"] == 1
    entry = summary["entries"][0]
    assert entry["status"] == "resolved"
    # α 口径自洽：realized − bench_equal == alpha_vs_equal
    assert abs(entry["realized_return"] - entry["benchmark_returns"]["bm_equal"]
               - entry["alpha_vs_equal"]) < 1e-9
    # 观点命中只统计被采纳的观点
    view_ids_adopted = {v["view_id"] for v in record.bl_inputs["views"]
                        if v.get("lambda", 0.0) != 0.0}
    for h in entry["view_hits"]:
        assert h["view_id"] in view_ids_adopted
        assert h["method"] in {"tsmom", "clock", "erp"}


def test_panel_end_decision_stays_pending(isolated_outcomes, config):
    # as-of = 数据终点的决策没有未来价格 → 必须保持 pending，不得硬解算
    record = run_decision("recovery_2026", "2026-07-09", config)
    outcomes.store_pending(record)
    outcomes.resolve_pending()
    summary = outcomes.summarize()
    assert any(p["decision_id"] == record.decision_id for p in summary["pending"])


def test_backfill_idempotent(isolated_outcomes, config):
    added_first = outcomes.backfill_from_backtest(config)
    assert added_first > 40  # 55 期回测决策
    assert outcomes.backfill_from_backtest(config) == 0  # 幂等
    summary = outcomes.summarize()
    assert summary["resolved_count"] >= added_first - 2  # 最后一两期无未来数据
    for method, s in summary["method_hit_rates"].items():
        assert 0.0 <= s["hit_rate"] <= 1.0
        assert s["total"] > 0


def test_committee_review_refs_are_traceable(config):
    record = run_decision("stagflation_2022", "2022-10-14", config)
    review = build_committee_review(record)
    valid_view_ids = {v["view_id"] for v in record.bl_inputs["views"]}
    valid_rules = {a.rule for a in record.guardrail_actions}
    assert review["verdict"]["result"] in {"clean_pass", "pass_with_notes", "blocked"}
    assert review["verdict"]["score"]["closure_ok"] is True
    for c in review["challenges"]:
        assert c["response"]["text"], "每条质疑必须有回应"
        refs = c["refs"]
        if "view_id" in refs:
            assert refs["view_id"] in valid_view_ids
        if "view_ids" in refs:
            assert set(refs["view_ids"]).issubset(valid_view_ids)
        if "rule" in refs:
            assert refs["rule"] in valid_rules


def test_committee_counts_match_record(config):
    record = run_decision("recovery_2026", "2026-07-09", config)
    review = build_committee_review(record)
    score = review["verdict"]["score"]
    views = record.bl_inputs["views"]
    assert score["views_total"] == len(views)
    assert score["views_adopted"] == sum(1 for v in views if v.get("lambda", 0.0) != 0.0)
    assert score["guardrails_triggered"] == sum(1 for a in record.guardrail_actions if a.triggered)


def test_outcomes_concurrent_writes(isolated_outcomes, config):
    """并发写结果账本不互抢临时文件（CI 竞态回归）。"""
    import threading

    record = run_decision("stagflation_2022", "2022-10-14", config)
    errors: list[Exception] = []

    def worker():
        try:
            for _ in range(10):
                outcomes.store_pending(record)
                outcomes.resolve_pending()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not errors, f"并发写账本异常: {errors[:2]}"
