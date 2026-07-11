"""API 层测试：11 个端点的契约与一致性。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_meta():
    data = client.get("/api/meta").json()
    assert len(data["universe"]["assets"]) == 27
    assert len(data["universe"]["display_buckets"]) == 7
    assert len(data["universe"]["asset_classes"]) == 5
    assert len(data["scenarios"]["scenarios"]) >= 2
    names = {m["name"] for m in data["methods"]}
    assert names == {"Risk Parity", "Time Series Momentum",
                     "Merrill Lynch Investment Clock", "Equity Risk Premium",
                     "Black-Litterman Model"}


def test_config_defaults():
    data = client.get("/api/config/defaults").json()
    assert data["config"]["single_asset_cap"] == 0.10
    assert "personality" in data


def test_run_decision_and_fetch():
    bundle = client.post("/api/decisions/run",
                         json={"scenario_id": "recovery_2026"}).json()
    assert abs(sum(bundle["target_weights"].values()) - 1) < 1e-6
    assert bundle["checks"]["attribution_closure"] is True
    decision_id = bundle["decision_id"]

    again = client.get(f"/api/decisions/{decision_id}").json()
    assert again["target_weights"] == bundle["target_weights"]

    record = client.get(f"/api/decisions/{decision_id}/record").json()
    assert record["decision_id"] == decision_id

    index = client.get("/api/decisions").json()
    assert any(d["decision_id"] == decision_id for d in index)


def test_run_with_custom_config_changes_result():
    base = client.post("/api/decisions/run",
                       json={"scenario_id": "recovery_2026"}).json()
    custom = dict(base["config"])
    custom["cash_floor"] = 0.15
    custom["single_asset_cap"] = 0.08
    changed = client.post("/api/decisions/run",
                          json={"scenario_id": "recovery_2026", "config": custom}).json()
    assert changed["decision_id"] != base["decision_id"]
    assert changed["target_weights"] != base["target_weights"]
    assert abs(sum(changed["target_weights"].values()) - 1) < 1e-6
    assert max(changed["target_weights"].values()) <= 0.08 + 1e-6 or \
        changed["target_weights"]["cash"] > 0.08  # 现金不受单资产上限约束


def test_overview():
    data = client.get("/api/overview?scenario_id=recovery_2026").json()
    assert abs(sum(data["class_weights"].values()) - 1) < 1e-6
    assert data["risk"]["vol_budget_use"] > 0


def test_scenario_compare():
    data = client.get("/api/scenarios/compare?base=recovery_2026&other=stagflation_2022").json()
    assert data["base"]["input_fingerprint"] != data["other"]["input_fingerprint"]
    assert any(abs(v) > 1e-4 for v in data["bucket_diff"].values())


def test_daily():
    data = client.get("/api/daily?scenario_id=recovery_2026").json()
    assert len(data["history"]) > 0
    assert abs(sum(data["ideal_weights"].values()) - 1) < 1e-6
    assert data["no_trade_band"] == 0.015


def test_weekly():
    data = client.get("/api/weekly-report?scenario_id=recovery_2026").json()
    assert data["markdown"].startswith("# 周度投资纪要")
    assert len(data["signals"]) == 4
    assert "Risk Parity" in data["markdown"]
    assert "CTA" not in data["markdown"]


def test_spread_desk_isolated():
    data = client.get("/api/spread-desk?scenario_id=recovery_2026").json()
    assert len(data["strategies"]) == 5
    assert "独立叠加账本" in data["constraints"]["isolation"]
    assert all("z" in s for s in data["strategies"])


def test_backtest():
    data = client.post("/api/backtest/run", json={}).json()
    assert "committee" in data["nav"]
    assert len(data["dates"]) == len(data["nav"]["committee"])
    strategies = {m["strategy"] for m in data["metrics"]}
    assert {"committee", "bm_6040", "bm_equal", "cash"}.issubset(strategies)


def test_unknown_scenario_404():
    res = client.post("/api/decisions/run", json={"scenario_id": "nope"})
    assert res.status_code == 404


@pytest.mark.parametrize("path", ["/api/decisions/dec_not_exist"])
def test_missing_decision_404(path):
    assert client.get(path).status_code == 404
