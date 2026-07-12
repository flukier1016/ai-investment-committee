"""Typer CLI 防线。

防止命令行绕回 HTTP、跳过 canonical 落库/结果账本、漏掉零归因观点，
或在 trace/report 中重跑引擎、截断输入哈希、混入方法缩写与 Rich 额外渲染。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app import cli
from app.domain import universe
from app.domain.labels import BUCKET_ZH
from app.domain.market_data import NoDataError
from app.schemas.config import AllocationConfig
from app.services.report import write_decision_report


RUNNER = CliRunner()
BACKEND = Path(__file__).resolve().parents[2] / "backend"
FORBIDDEN_METHOD_ABBREVIATION = re.compile(
    r"(?<![A-Za-z0-9_])(?:CTA|TSMOM|ERP|BL)(?![A-Za-z0-9_])"
)


def _invoke(*args: str):
    return RUNNER.invoke(cli.app, list(args), color=False)


def test_entrypoint_and_help_register_exact_four_commands():
    pyproject = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["scripts"]["invest"] == "app.cli:app"

    result = _invoke("--help")

    assert result.exit_code == 0
    for command in ("run", "backtest", "trace", "report"):
        assert command in result.stdout


def test_run_uses_defaults_pipeline_canonical_store_and_outcomes(monkeypatch, record):
    canonical = record.model_copy(update={
        "decision_id": "dec_cli_canonical",
        "conclusion": "[bold]只展示 canonical 落库记录[/bold]",
        "degraded_inputs": [{"input": "clock", "reason": "fixture", "action": "abstain"}],
    })
    calls: list[tuple] = []

    def fake_run(scenario_id, asof, config):
        calls.append(("pipeline", scenario_id, asof, config))
        return record

    def fake_save(generated):
        calls.append(("save", generated))
        return canonical

    monkeypatch.setattr(cli, "run_decision_cached", fake_run)
    monkeypatch.setattr(cli.store, "save", fake_save)
    monkeypatch.setattr(cli.outcomes, "store_pending",
                        lambda saved: calls.append(("pending", saved)))
    monkeypatch.setattr(cli.outcomes, "resolve_pending",
                        lambda: calls.append(("resolve",)) or 0)

    first = _invoke("run")
    second = _invoke("run")

    assert first.exit_code == second.exit_code == 0
    assert first.stdout == second.stdout
    pipeline_calls = [call for call in calls if call[0] == "pipeline"]
    assert len(pipeline_calls) == 2
    assert all(call[1:3] == ("recovery_2026", "2026-07-09") for call in pipeline_calls)
    assert all(isinstance(call[3], AllocationConfig) for call in pipeline_calls)
    assert [call[0] for call in calls[:4]] == ["pipeline", "save", "pending", "resolve"]
    assert calls[1][1] is record
    assert calls[2][1] is canonical
    assert canonical.decision_id in first.stdout
    assert record.decision_id not in first.stdout
    assert canonical.conclusion in first.stdout
    assert "降级输入" in first.stdout and "1" in first.stdout
    assert "\x1b[" not in first.stdout


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("run", "--scenario", "unknown"), "未知情景"),
        (("run", "--asof", "2026/07/09"), "YYYY-MM-DD"),
        (("run", "--asof", "2027-01-01"), "超出数据范围"),
    ],
)
def test_run_rejects_invalid_inputs_before_pipeline(monkeypatch, args, message):
    monkeypatch.setattr(
        cli, "run_decision_cached",
        lambda *_args, **_kwargs: pytest.fail("非法输入不得进入 pipeline"),
    )

    result = _invoke(*args)

    assert result.exit_code == 2
    assert message in result.output
    assert "Traceback" not in result.output


def test_run_core_data_failure_is_loud_and_never_persists(monkeypatch):
    def fail_pipeline(*_args, **_kwargs):
        raise NoDataError("核心价格缺失")

    monkeypatch.setattr(cli, "run_decision_cached", fail_pipeline)
    monkeypatch.setattr(
        cli.store, "save", lambda *_args: pytest.fail("核心失败后不得落库"))

    result = _invoke("run")

    assert result.exit_code == 1
    assert "NoDataError" in result.output
    assert "核心价格缺失" in result.output
    assert "Traceback" not in result.output


def test_backtest_direct_call_renders_summary_not_raw_nav(monkeypatch):
    captured = []
    payload = {
        "span": {"start": "2022-01-31", "end": "2026-07-09"},
        "rebalance_freq": "monthly",
        "cost_bps_per_side": 10.0,
        "ann_turnover": 0.972,
        "avg_rebalance_turnover": 0.0827,
        "walk_forward": {"folds": [{"beats": True}, {"beats": False}]},
        "metrics": [{
            "strategy": "risk_parity_only",
            "ann_return": 0.0123,
            "ann_vol": 0.0456,
            "sharpe": 0.27,
            "max_drawdown": -0.0789,
            "calmar": 0.16,
        }],
        "nav": {"committee": [1.0, 987654.321]},
    }

    def fake_backtest(config):
        captured.append(config)
        return payload

    monkeypatch.setattr(cli, "run_backtest", fake_backtest)

    result = _invoke("backtest")

    assert result.exit_code == 0
    assert len(captured) == 1 and isinstance(captured[0], AllocationConfig)
    assert "2022-01-31" in result.stdout and "2026-07-09" in result.stdout
    assert "Risk Parity" in result.stdout
    assert "risk_parity_only" not in result.stdout
    assert "987654.321" not in result.stdout


def test_trace_reads_record_and_keeps_all_views_signals_hashes_and_full_method_names(
    monkeypatch, record
):
    monkeypatch.setattr(cli.store, "get", lambda _decision_id: record)
    monkeypatch.setattr(
        cli, "run_decision_cached",
        lambda *_args, **_kwargs: pytest.fail("trace 不得重跑 pipeline"),
    )

    result = _invoke("trace", record.decision_id)

    assert result.exit_code == 0
    for view in record.bl_inputs["views"]:
        assert view["view_id"] in result.stdout
    for signal_id, signal in record.signals_by_id.items():
        assert signal_id in result.stdout
        for data_input in signal.inputs:
            assert data_input.hash in result.stdout
    assert record.input_fingerprint in result.stdout
    assert "Risk Parity 战略先验" in result.stdout
    assert all(name in result.stdout for name in cli.METHOD_NAMES.values())
    assert "Black-Litterman Model" in result.stdout
    assert FORBIDDEN_METHOD_ABBREVIATION.search(result.stdout) is None


def test_trace_view_filter_keeps_zero_attribution_view_and_risk_parity(monkeypatch, record):
    zero_view = next(view for view in record.bl_inputs["views"] if view["lambda"] == 0.0)
    attribution = {
        bucket_id: {key: value for key, value in parts.items()
                    if key != zero_view["view_id"]}
        for bucket_id, parts in record.attribution.items()
    }
    sparse = record.model_copy(update={"attribution": attribution})
    monkeypatch.setattr(cli.store, "get", lambda _decision_id: sparse)

    result = _invoke("trace", sparse.decision_id, "--view", zero_view["view_id"])

    assert result.exit_code == 0
    assert zero_view["view_id"] in result.stdout
    other_view_id = next(
        view["view_id"] for view in record.bl_inputs["views"]
        if view["view_id"] != zero_view["view_id"])
    assert other_view_id not in result.stdout
    assert result.stdout.count("+0.0000%") >= len(universe.bucket_ids())
    assert all(BUCKET_ZH[bucket_id] in result.stdout for bucket_id in universe.bucket_ids())
    risk_parity_signal = next(
        signal for signal in record.signals_by_id.values()
        if signal.method == "risk_parity")
    assert risk_parity_signal.signal_id in result.stdout
    assert all(data_input.hash in result.stdout for data_input in risk_parity_signal.inputs)


def test_trace_surfaces_orphans_abstain_branch_and_controlled_errors(monkeypatch, record):
    erp_signal = next(
        signal for signal in record.signals_by_id.values() if signal.method == "erp")
    removed_view_ids = {
        view["view_id"] for view in record.bl_inputs["views"]
        if erp_signal.signal_id in view["source_signal_ids"]
    }
    remaining_views = [
        view for view in record.bl_inputs["views"]
        if view["view_id"] not in removed_view_ids
    ]
    attribution = {
        bucket_id: {key: value for key, value in parts.items()
                    if key not in removed_view_ids}
        for bucket_id, parts in record.attribution.items()
    }
    attribution[universe.bucket_ids()[0]]["view_orphan_fixture"] = 0.001
    signals = dict(record.signals_by_id)
    signals[erp_signal.signal_id] = erp_signal.model_copy(update={
        "view_type": "abstain",
        "abstain": ["commodity", "fx"],
    })
    anomalous = record.model_copy(update={
        "bl_inputs": {**record.bl_inputs, "views": remaining_views},
        "attribution": attribution,
        "signals_by_id": signals,
    })
    monkeypatch.setattr(cli.store, "get", lambda _decision_id: anomalous)

    traced = _invoke("trace", anomalous.decision_id)
    unknown_view = _invoke("trace", anomalous.decision_id, "--view", "view_missing")

    assert traced.exit_code == 0
    assert "view_orphan_fixture" in traced.stdout
    assert "归因含未注册观点键" in traced.stdout
    assert erp_signal.signal_id in traced.stdout
    assert "未形成观点" in traced.stdout
    assert "abstain" in traced.stdout
    assert '["commodity","fx"]' in traced.stdout
    assert unknown_view.exit_code == 2
    assert "观点不存在" in unknown_view.output
    assert "Traceback" not in unknown_view.output

    monkeypatch.setattr(
        cli.store, "get", lambda _decision_id: pytest.fail("非法 ID 不得访问存储"))
    invalid = _invoke("trace", "../../etc/passwd")
    assert invalid.exit_code == 2
    assert "decision_id 格式非法" in invalid.output

    monkeypatch.setattr(cli.store, "get", lambda _decision_id: None)
    missing = _invoke("trace", "dec_missing")
    assert missing.exit_code == 2
    assert "决策记录不存在" in missing.output


def test_report_is_exact_stdout_and_never_reruns_pipeline(monkeypatch, record):
    expected = write_decision_report(record)
    monkeypatch.setattr(cli.store, "get", lambda _decision_id: record)
    monkeypatch.setattr(
        cli, "run_decision_cached",
        lambda *_args, **_kwargs: pytest.fail("report 不得重跑 pipeline"),
    )

    result = _invoke("report", record.decision_id)

    assert result.exit_code == 0
    assert result.stdout == expected
    assert result.stdout.encode("utf-8") == expected.encode("utf-8")
    assert "\x1b[" not in result.stdout
