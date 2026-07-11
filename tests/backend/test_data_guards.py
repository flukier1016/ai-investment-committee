"""数据护栏：类型化错误 + 防前视断言 + API 边界。

防线来源：TradingAgents #992/#1007 前视泄漏与 data-access contract 的教训。
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.domain.market_data import (InsufficientHistoryError, NoDataError,
                                    load_slice, trading_dates)
from app.main import app

client = TestClient(app)


def test_asof_before_data_start_raises_typed_error():
    with pytest.raises(NoDataError):
        load_slice("2019-01-01")


def test_short_history_raises_typed_error():
    start = trading_dates()[0]
    with pytest.raises(InsufficientHistoryError):
        load_slice((start + pd.Timedelta(days=30)).date().isoformat())


def test_slice_never_contains_future_data():
    for asof in ["2022-10-14", "2024-06-28", "2026-07-09"]:
        sl = load_slice(asof)
        ts = pd.Timestamp(asof)
        assert sl.prices.index.max() <= ts
        assert sl.erp.index.max() <= ts
        assert (sl.macro["publish_date"] <= ts).all()


def test_api_returns_400_with_error_type_for_bad_asof():
    res = client.post("/api/decisions/run",
                      json={"scenario_id": "recovery_2026", "asof": "2020-03-02"})
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["error_type"] == "InsufficientHistoryError"
    assert "300" in detail["message"]


def test_api_rejects_out_of_range_asof():
    res = client.post("/api/decisions/run",
                      json={"scenario_id": "recovery_2026", "asof": "2030-01-01"})
    assert res.status_code == 400
