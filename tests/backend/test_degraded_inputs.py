"""核心/可选数据分级：可选输入缺失 → 显式弃权 + 决策照常闭合。

对应 V3 第八节 A 类门禁：任一专家方法在关键数据缺失时能弃权，
BL 聚合层正确处理缺失观点而非把 NaN 当 0。
"""

import pandas as pd
import pytest

from app.domain import market_data
from app.domain.pipeline import run_decision
from app.schemas.config import AllocationConfig

TOL = 1e-6


@pytest.fixture
def config():
    return AllocationConfig()


def test_missing_macro_degrades_clock_to_abstain(monkeypatch, config):
    empty_macro = pd.DataFrame(columns=["month", "pmi_cn", "cpi_yoy_cn",
                                        "publish_date", "source"])
    empty_macro["publish_date"] = pd.to_datetime(empty_macro["publish_date"])
    monkeypatch.setattr(market_data, "_macro", lambda: empty_macro)
    record = run_decision("test_no_macro", "2026-07-09", config)
    clock = next(s for s in record.signals_by_id.values() if s.method == "clock")
    assert clock.view_type == "abstain"
    assert any(d["input"] == "clock" for d in record.degraded_inputs)
    # BL 少观点仍闭合
    assert abs(sum(record.target_weights.values()) - 1.0) < TOL
    assert record.checks["attribution_closure"] is True
    assert all("view_clock" not in v["view_id"] for v in record.bl_inputs["views"])


def test_missing_erp_inputs_degrades_to_abstain(monkeypatch, config):
    empty_erp = pd.DataFrame(columns=["csi300_ep", "cgb10y_yield"],
                             index=pd.DatetimeIndex([], name="date"))
    monkeypatch.setattr(market_data, "_erp_inputs", lambda: empty_erp)
    record = run_decision("test_no_erp", "2026-07-09", config)
    erp = next(s for s in record.signals_by_id.values() if s.method == "erp")
    assert erp.view_type == "abstain"
    assert any(d["input"] == "erp" for d in record.degraded_inputs)
    assert abs(sum(record.target_weights.values()) - 1.0) < TOL
    assert record.checks["attribution_closure"] is True


def test_all_tactical_missing_falls_back_to_prior(monkeypatch, config):
    """三个战术信号全部缺席 → 目标权重 = 约束式 Risk Parity 底仓（无观点）。"""
    empty_macro = pd.DataFrame(columns=["month", "pmi_cn", "cpi_yoy_cn",
                                        "publish_date", "source"])
    empty_macro["publish_date"] = pd.to_datetime(empty_macro["publish_date"])
    empty_erp = pd.DataFrame(columns=["csi300_ep", "cgb10y_yield"],
                             index=pd.DatetimeIndex([], name="date"))
    monkeypatch.setattr(market_data, "_macro", lambda: empty_macro)
    monkeypatch.setattr(market_data, "_erp_inputs", lambda: empty_erp)
    # TSMOM 依赖价格（核心输入之外的分数），无法单独打掉；只验证 clock+erp 双缺
    record = run_decision("test_double_missing", "2026-07-09", config)
    assert len(record.degraded_inputs) >= 2
    assert abs(sum(record.target_weights.values()) - 1.0) < TOL
    # 归因中除 prior/guardrail/tsmom 外不应出现 clock/erp 段
    for parts in record.attribution.values():
        for key in parts:
            assert "clock" not in key and "erp" not in key
