"""扰动稳定性 + 不可行约束 + 存储容错 + 回测口径不变量。

对应 V3 第八节 E 类门禁（参数微扰不出现权重剧烈跳变）与 D 类
（极端情况下不输出无效权重）。
"""

import json

import pytest

from app.domain.backtest import run_backtest
from app.domain.guardrails import InfeasibleConstraintsError
from app.domain.pipeline import run_decision
from app.schemas.config import AllocationConfig
from app.services import store


def _bucket_l1(a: dict, b: dict) -> float:
    return sum(abs(a[k] - b[k]) for k in a)


@pytest.mark.parametrize("field,delta", [
    ("shrinkage", 0.02),
    ("tau", 0.002),
    ("max_view_tilt", 0.002),
    ("risk_aversion", 0.2),
])
def test_parameter_perturbation_bounded(field, delta):
    base_cfg = AllocationConfig()
    base = run_decision("perturb_base", "2026-07-09", base_cfg)
    perturbed_cfg = AllocationConfig(**{**base_cfg.model_dump(),
                                        field: getattr(base_cfg, field) + delta})
    perturbed = run_decision("perturb_test", "2026-07-09", perturbed_cfg)
    l1 = _bucket_l1(base.bucket_weights, perturbed.bucket_weights)
    assert l1 < 0.15, f"{field} 微扰 {delta} 引起桶权重 L1 变化 {l1:.3f}（>0.15，权重跳变）"
    assert abs(sum(perturbed.target_weights.values()) - 1.0) < 1e-6


def test_infeasible_constraints_fail_loud_not_invalid_weights():
    """债券底仓 50% 但单资产上限 2%（5 个债券资产最多 10%）→ 必须响亮报错，
    绝不输出和≠1 或越界的权重。"""
    cfg = AllocationConfig(bond_floor=0.5, single_asset_cap=0.02)
    with pytest.raises(InfeasibleConstraintsError):
        run_decision("infeasible", "2026-07-09", cfg)


def test_api_maps_infeasible_to_400():
    from fastapi.testclient import TestClient

    from app.main import app
    client = TestClient(app)
    cfg = AllocationConfig(bond_floor=0.5, single_asset_cap=0.02).model_dump()
    res = client.post("/api/decisions/run",
                      json={"scenario_id": "recovery_2026", "config": cfg})
    assert res.status_code == 400
    assert res.json()["detail"]["error_type"] == "InfeasibleConstraints"


def test_store_skips_corrupt_json(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RUNS", tmp_path)
    (tmp_path / "dec_corrupt.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "dec_missing_keys.json").write_text('{"decision_id": "x"}', encoding="utf-8")
    assert store.list_index() == []


def test_backtest_invariants():
    bt = run_backtest(AllocationConfig())
    n = len(bt["dates"])
    for name, nav in bt["nav"].items():
        assert len(nav) == n, f"{name} 净值长度与日期不符"
        assert all(v > 0 for v in nav), f"{name} 出现非正净值"
    assert len(bt["drawdown"]) == n
    assert all(v <= 1e-9 for v in bt["drawdown"]), "回撤序列出现正值"
    log = bt["rebalance_log"]
    assert log[0]["turnover"] == 0.0 and log[0]["cost_bps"] == 0.0, "首期建仓不应计成本"
    assert all(r["turnover"] >= 0 for r in log)
    # 委员会与基准同成本口径：非首期换手应普遍非零（漂移回调必然产生交易）
    assert sum(1 for r in log[1:] if r["turnover"] > 0) > len(log) * 0.8


def test_decision_record_json_roundtrip_with_new_fields():
    """degraded_inputs 等新字段的记录可完整序列化/反序列化（旧记录容错由默认值保证）。"""
    record = run_decision("roundtrip", "2026-07-09", AllocationConfig())
    from app.schemas.decision import DecisionRecord
    again = DecisionRecord.model_validate_json(record.model_dump_json())
    assert again.target_weights == record.target_weights
    assert again.degraded_inputs == record.degraded_inputs
    # 模拟旧版记录（无 degraded_inputs 字段）仍可加载
    payload = json.loads(record.model_dump_json())
    payload.pop("degraded_inputs")
    legacy = DecisionRecord.model_validate(payload)
    assert legacy.degraded_inputs == []
