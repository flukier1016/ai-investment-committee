"""核心数据验收（任务书第十节 15 项，逐项对应）。"""

import pandas as pd

from app.domain import universe
from app.domain.market_data import load_slice
from app.domain.pipeline import run_decision

TOL = 1e-6


# 1. 27 个明细资产权重和为 100%
def test_asset_weights_sum_to_one(record):
    assert len(record.target_weights) == 27
    assert abs(sum(record.target_weights.values()) - 1.0) < TOL


# 2. 27 资产汇总到 7 桶后仍为 100%
def test_bucket_weights_sum_to_one(record):
    buckets = universe.aggregate_to_buckets(record.target_weights)
    assert len(buckets) == 7
    assert abs(sum(buckets.values()) - 1.0) < TOL
    for b, w in buckets.items():
        assert abs(w - record.bucket_weights[b]) < TOL


# 3. 7 桶汇总到 5 大类后仍为 100%
def test_class_weights_sum_to_one(record):
    classes = universe.aggregate_to_classes(record.bucket_weights)
    assert len(classes) == 5
    assert abs(sum(classes.values()) - 1.0) < TOL
    for c, w in classes.items():
        assert abs(w - record.class_weights[c]) < TOL


# 4. 顶部权重与底层明细完全一致
def test_top_weights_match_detail(record):
    for c in universe.class_ids():
        detail_sum = sum(
            w for a, w in record.target_weights.items()
            if universe.class_of_bucket()[universe.bucket_of()[a]] == c)
        assert abs(detail_sum - record.class_weights[c]) < TOL


# 5. P 的列数与参与 BL 的资产数量一致
def test_p_columns_match_asset_order(record):
    asset_order = record.bl_inputs["asset_order"]
    assert len(asset_order) == 27
    for view in record.bl_inputs["views"]:
        assert set(view["P"]).issubset(set(asset_order))


# 6. P、Q、Omega 行数一致
def test_p_q_omega_rows_consistent(record):
    views = record.bl_inputs["views"]
    assert len(views) > 0
    for view in views:
        assert "P" in view and view["P"]
        assert isinstance(view["Q"], float)
        assert isinstance(view["Omega"], float)
    assert record.checks["p_q_omega_rows"] == len(views)


# 7. Omega 对角元素为正
def test_omega_positive(record):
    for view in record.bl_inputs["views"]:
        assert view["Omega"] > 0
        assert view["view_variance"] > 0


# 8. 每个观点都有 view_id
def test_views_have_unique_ids(record):
    ids = [v["view_id"] for v in record.bl_inputs["views"]]
    assert all(ids)
    assert len(ids) == len(set(ids))


# 9. 每个观点都有 source_signal_ids
def test_views_have_source_signals(record):
    for view in record.bl_inputs["views"]:
        assert view["source_signal_ids"]
        for sid in view["source_signal_ids"]:
            assert sid in record.signals_by_id


# 10. 每个最终权重都能找到归因链路（桶 → 观点 → 信号 → 输入哈希）
def test_full_attribution_chain(record):
    view_ids = {v["view_id"] for v in record.bl_inputs["views"]}
    for bucket, parts in record.attribution.items():
        for key in parts:
            if key in ("prior", "guardrail"):
                continue
            assert key in view_ids, f"{bucket} 的归因段 {key} 无对应观点"
            view = next(v for v in record.bl_inputs["views"] if v["view_id"] == key)
            for sid in view["source_signal_ids"]:
                signal = record.signals_by_id[sid]
                assert signal.inputs, f"信号 {sid} 缺输入血缘"
                for inp in signal.inputs:
                    assert inp.hash and inp.asof


# 11. 风控裁剪后权重重新闭合（归因含风控段仍闭合）
def test_attribution_closure_after_guardrails(record):
    for bucket, parts in record.attribution.items():
        total = sum(parts.values())
        assert abs(total - record.bucket_weights[bucket]) < TOL, bucket
    assert record.checks["attribution_closure"] is True


# 12. 相同输入产生相同结果
def test_determinism(record, config):
    again = run_decision("recovery_2026", "2026-07-09", config)
    assert again.decision_id == record.decision_id
    assert again.target_weights == record.target_weights
    assert again.input_fingerprint == record.input_fingerprint
    assert [v["Q"] for v in again.bl_inputs["views"]] == \
           [v["Q"] for v in record.bl_inputs["views"]]


# 13. 场景切换会改变下游计算
def test_scenario_switch_changes_output(record, record_stagflation):
    assert record.input_fingerprint != record_stagflation.input_fingerprint
    assert record.target_weights != record_stagflation.target_weights
    r1 = record.signals_by_id[record.input_signals[2]].values.get("regime")
    r2 = record_stagflation.signals_by_id[record_stagflation.input_signals[2]].values.get("regime")
    assert r1 != r2


# 14. 回测/情景只使用当时可见数据（point-in-time）
def test_point_in_time_no_future_leak():
    asof = "2022-10-14"
    sl = load_slice(asof)
    assert sl.prices.index.max() <= pd.Timestamp(asof)
    assert (sl.macro["publish_date"] <= pd.Timestamp(asof)).all()
    assert sl.erp.index.max() <= pd.Timestamp(asof)
    # 2022-09 的 CPI 于 10-10 发布可见，2022-10 的于 11-10 发布不可见
    visible_months = set(sl.macro["month"])
    assert "2022-09" in visible_months
    assert "2022-10" not in visible_months


# 15. 页面展示值与 API 返回值一致（bundle == record）
def test_bundle_matches_record(record):
    from app.services.bundle import to_bundle
    bundle = to_bundle(record)
    assert bundle["target_weights"] == record.target_weights
    assert bundle["bucket_weights"] == record.bucket_weights
    assert bundle["class_weights"] == record.class_weights
    assert bundle["attribution"] == record.attribution
    assert bundle["posterior_ER"] == record.posterior_ER
    asset_targets = {a["id"]: a["target"] for a in bundle["assets"]}
    assert asset_targets == record.target_weights
