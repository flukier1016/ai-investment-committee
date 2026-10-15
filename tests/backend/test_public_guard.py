"""公网演示防护：计算类 POST 限流、决策记录存储上限。"""

import os

from fastapi.testclient import TestClient

import app.main as main_module
from app.api import guard
from app.services import store


def test_rate_gate_limits_per_client_and_in_total():
    g = guard.RateGate(per_client=2, client_window=600, total=3, total_window=3600)
    assert g.take("a") is None and g.take("a") is None
    assert "同一来源" in g.take("a")
    assert g.take("b") is None
    assert "全站" in g.take("c")


def test_compute_posts_get_429_after_limit_but_reads_still_work(monkeypatch):
    monkeypatch.setattr(main_module, "compute_gate", guard.RateGate(2, 600, 100, 3600))
    client = TestClient(main_module.app)
    first = [client.post("/api/__probe__", json={}).status_code for _ in range(2)]
    assert 429 not in first
    blocked = client.post("/api/__probe__", json={})
    assert blocked.status_code == 429 and blocked.headers["Retry-After"] == "60"
    assert client.post("/api/__probe__", json={}, headers={"X-Forwarded-For": "203.0.113.9"}).status_code != 429
    assert client.get("/api/health").status_code == 200


def test_store_evicts_oldest_records_beyond_cap(tmp_path, monkeypatch, record):
    monkeypatch.setattr(store, "RUNS", tmp_path)
    monkeypatch.setattr(store, "MAX_RECORDS", 3)
    ids = [f"dec_cap_{i}" for i in range(5)]
    for i, decision_id in enumerate(ids):
        store.save(record.model_copy(update={"decision_id": decision_id}))
        os.utime(tmp_path / f"{decision_id}.json", (1_000_000 + i, 1_000_000 + i))
    assert sorted(p.stem for p in tmp_path.glob("dec_*.json")) == ids[-3:]
