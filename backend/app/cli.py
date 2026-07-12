"""直接调用确定性引擎的 Typer 命令行入口。

run/backtest 只调用 domain 与 services；trace/report 只读取不可变
DecisionRecord。这里不依赖 FastAPI，也不通过 HTTP 回调本项目。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from .domain import universe
from .domain.backtest import run_backtest
from .domain.guardrails import InfeasibleConstraintsError
from .domain.labels import BUCKET_ZH, CLASS_ZH
from .domain.market_data import DataError, trading_dates
from .domain.pipeline import run_decision_cached
from .domain.stance import resolve_bucket_stances
from .schemas.config import AllocationConfig
from .schemas.decision import DecisionRecord, TracedSignal, View
from .services import outcomes, store
from .services.report import write_decision_report


app = typer.Typer(
    name="invest",
    help="智策 AI 投委会确定性命令行",
    no_args_is_help=True,
    add_completion=False,
)

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_PATH = ROOT / "data" / "demo" / "scenarios.json"
DECISION_ID_PATTERN = re.compile(r"^dec_[A-Za-z0-9_-]+$")

METHOD_NAMES = {
    "risk_parity": "Risk Parity",
    "tsmom": "Time Series Momentum",
    "clock": "Merrill Lynch Investment Clock",
    "erp": "Equity Risk Premium",
}

STRATEGY_NAMES = {
    "committee": "智策 AI 投委会",
    "risk_parity_only": "Risk Parity",
    "bm_6040": "60/40 基准",
    "bm_equal": "等权基准",
    "cash": "现金基准",
}


def _console() -> Console:
    """命令内创建 Console，确保测试/管道能捕获 stdout；关闭动态高亮。"""
    # 固定审计输出宽度，窄终端可自行折行，但 Rich 不得用省略号截断 ID/hash。
    return Console(width=160, highlight=False, markup=False)


def _fail(message: str, *, code: int = 2) -> NoReturn:
    typer.echo(f"错误：{message}", err=True)
    raise typer.Exit(code=code)


def _scenario_catalog() -> dict:
    try:
        return json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        _fail(f"无法读取 Demo 情景目录（{type(exc).__name__}）", code=1)


def _resolve_run_inputs(scenario: str | None, asof: str | None) -> tuple[str, str]:
    catalog = _scenario_catalog()
    scenario_id = scenario or catalog.get("default_scenario")
    definitions = {
        item.get("id"): item
        for item in catalog.get("scenarios", [])
        if isinstance(item, dict) and item.get("id")
    }
    if scenario_id not in definitions:
        available = "、".join(definitions) or "无"
        _fail(f"未知情景 {scenario_id!r}；可选：{available}")
    selected_asof = asof or definitions[scenario_id].get("asof")
    if not isinstance(selected_asof, str):
        _fail(f"情景 {scenario_id!r} 缺少有效 as-of", code=1)
    return str(scenario_id), _validate_asof(selected_asof)


def _validate_asof(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        _fail("as-of 必须是 YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail("as-of 不是有效日历日期")
    last_date = trading_dates()[-1].date()
    if parsed > last_date:
        _fail(f"as-of 超出数据范围（最后交易日 {last_date.isoformat()}）")
    return parsed.isoformat()


def _validate_decision_id(decision_id: str) -> str:
    if not DECISION_ID_PATTERN.fullmatch(decision_id):
        _fail("decision_id 格式非法")
    return decision_id


def _load_record(decision_id: str) -> DecisionRecord:
    decision_id = _validate_decision_id(decision_id)
    try:
        record = store.get(decision_id)
    except (OSError, UnicodeError, ValidationError) as exc:
        _fail(f"决策记录损坏或不可读（{type(exc).__name__}）", code=1)
    if record is None:
        _fail(f"决策记录不存在：{decision_id}")
    return record


def _percent(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "—"
    return f"{float(value):{'+' if signed else ''}.4%}"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _method_name(signal: TracedSignal | None) -> str:
    if signal is None:
        return "来源信号缺失"
    return METHOD_NAMES[signal.method]


def _record_views(record: DecisionRecord) -> list[View]:
    return [
        view if isinstance(view, View) else View.model_validate(view)
        for view in record.bl_inputs.get("views", [])
    ]


def _view_methods(record: DecisionRecord, view: View | None) -> str:
    if view is None:
        return "完整性异常：未找到观点"
    names: list[str] = []
    for signal_id in view.source_signal_ids:
        name = _method_name(record.signals_by_id.get(signal_id))
        if name not in names:
            names.append(name)
    return " / ".join(names) if names else "来源信号缺失"


def _ordered_signal_ids(record: DecisionRecord) -> list[str]:
    ordered = list(dict.fromkeys(record.input_signals))
    ordered.extend(sorted(signal_id for signal_id in record.signals_by_id
                          if signal_id not in ordered))
    return ordered


def _print_run_summary(record: DecisionRecord) -> None:
    console = _console()
    metadata = Table(title="决策摘要")
    metadata.add_column("字段")
    metadata.add_column("值", overflow="fold")
    metadata.add_row("decision_id", record.decision_id)
    metadata.add_row("scenario", record.scenario_id)
    metadata.add_row("as-of", record.asof)
    metadata.add_row("mode", record.mode)
    metadata.add_row("风控触发", str(sum(action.triggered for action in record.guardrail_actions)))
    metadata.add_row("降级输入", str(len(record.degraded_inputs)))
    metadata.add_row("三层闭合", "通过" if all(
        abs(float(record.checks.get(key, 0.0)) - 1.0) <= 1e-6
        for key in ("weight_sum_assets", "weight_sum_buckets", "weight_sum_classes")
    ) else "异常")
    console.print(metadata)

    class_table = Table(title="五大类目标权重")
    class_table.add_column("大类")
    class_table.add_column("目标权重", justify="right")
    for class_id in universe.class_ids():
        class_table.add_row(CLASS_ZH.get(class_id, class_id),
                            _percent(record.class_weights.get(class_id)))
    console.print(class_table)

    prior = universe.aggregate_to_buckets(record.prior.w_strategic)
    stances = resolve_bucket_stances(
        record.bucket_stances,
        prior,
        record.bucket_weights,
        universe.bucket_ids(),
    )
    bucket_table = Table(title="七个资产桶 · Risk Parity 先验 → 目标")
    bucket_table.add_column("资产桶")
    bucket_table.add_column("Risk Parity 先验", justify="right")
    bucket_table.add_column("目标权重", justify="right")
    bucket_table.add_column("偏离", justify="right")
    bucket_table.add_column("五档立场")
    for bucket_id in universe.bucket_ids():
        target = record.bucket_weights.get(bucket_id)
        bucket_table.add_row(
            BUCKET_ZH.get(bucket_id, bucket_id),
            _percent(prior.get(bucket_id)),
            _percent(target),
            _percent(None if target is None else target - prior.get(bucket_id, 0.0),
                     signed=True),
            stances.get(bucket_id, "—"),
        )
    console.print(bucket_table)
    console.print(record.conclusion)
    console.print("仅用于研究推演，不构成任何投资建议或交易指令。")


def _print_backtest(result: dict) -> None:
    console = _console()
    span = result.get("span") or {}
    summary = Table(title="回测摘要")
    summary.add_column("字段")
    summary.add_column("值", justify="right")
    summary.add_row("区间", f"{span.get('start', '—')} → {span.get('end', '—')}")
    summary.add_row("调仓频率", str(result.get("rebalance_freq", "—")))
    summary.add_row("单边成本", f"{result.get('cost_bps_per_side', '—')} bp")
    summary.add_row("年化换手", _percent(result.get("ann_turnover")))
    summary.add_row("平均单次换手", _percent(result.get("avg_rebalance_turnover")))
    folds = (result.get("walk_forward") or {}).get("folds") or []
    summary.add_row("样本外年度胜出", f"{sum(bool(fold.get('beats')) for fold in folds)}/{len(folds)}")
    console.print(summary)

    metrics = Table(title="策略指标")
    metrics.add_column("策略")
    metrics.add_column("年化收益", justify="right")
    metrics.add_column("年化波动", justify="right")
    metrics.add_column("Sharpe", justify="right")
    metrics.add_column("最大回撤", justify="right")
    metrics.add_column("Calmar", justify="right")
    for row in result.get("metrics") or []:
        strategy = str(row.get("strategy", "unknown"))
        metrics.add_row(
            STRATEGY_NAMES.get(strategy, f"其他策略（{strategy}）"),
            _percent(row.get("ann_return")),
            _percent(row.get("ann_vol")),
            "—" if row.get("sharpe") is None else str(row["sharpe"]),
            _percent(row.get("max_drawdown")),
            "—" if row.get("calmar") is None else str(row["calmar"]),
        )
    console.print(metrics)


def _orphan_attribution_ids(record: DecisionRecord, view_ids: set[str]) -> list[str]:
    extras = {
        key
        for bucket_id in universe.bucket_ids()
        for key in record.attribution.get(bucket_id, {})
        if key not in {"prior", "guardrail"} and key not in view_ids
    }
    return sorted(extras)


def _print_attribution(
    console: Console,
    record: DecisionRecord,
    views: list[View],
    segment_ids: list[str],
    warnings: list[str],
) -> None:
    by_id = {view.view_id: view for view in views}
    table = Table(title="七桶归因 → Black-Litterman Model 观点")
    table.add_column("资产桶")
    table.add_column("归因段", overflow="fold")
    table.add_column("段类型", overflow="fold")
    table.add_column("贡献", justify="right")
    table.add_column("桶目标", justify="right")
    table.add_column("闭合")
    for bucket_id in universe.bucket_ids():
        parts = record.attribution.get(bucket_id, {})
        target = record.bucket_weights.get(bucket_id)
        closure = target is not None and abs(sum(parts.values()) - target) <= 1e-6
        if not closure:
            warnings.append(f"{bucket_id} 的归因未与桶目标闭合")
        for segment_id in ["prior", *segment_ids, "guardrail"]:
            if segment_id == "prior":
                segment_type = "Risk Parity 战略先验"
            elif segment_id == "guardrail":
                segment_type = "确定性风控闸门"
            else:
                segment_type = _view_methods(record, by_id.get(segment_id))
            table.add_row(
                BUCKET_ZH.get(bucket_id, bucket_id),
                segment_id,
                segment_type,
                _percent(parts.get(segment_id, 0.0), signed=True),
                _percent(target),
                "通过" if closure else "异常",
            )
    console.print(table)


def _ordered_p(view: View, asset_order: list[str]) -> str:
    ordered = list(dict.fromkeys(asset_order))
    ordered.extend(sorted(asset_id for asset_id in view.P if asset_id not in ordered))
    values = [
        f"{asset_id}:{view.P.get(asset_id, 0.0):+g}"
        for asset_id in ordered
        if abs(view.P.get(asset_id, 0.0)) > 1e-12
    ]
    return "；".join(values) if values else "全零"


def _print_views(console: Console, record: DecisionRecord, views: list[View]) -> None:
    table = Table(title="Black-Litterman Model 观点参数")
    table.add_column("观点技术标识", overflow="fold")
    table.add_column("字段")
    table.add_column("值", overflow="fold")
    asset_order = list(record.bl_inputs.get("asset_order") or [])
    for view in views:
        rows = (
            ("来源方法", _view_methods(record, view)),
            ("P 非零项", _ordered_p(view, asset_order)),
            ("Q", f"{repr(float(view.Q))}（{_percent(view.Q, signed=True)}）"),
            ("confidence", f"{repr(float(view.confidence))}（{_percent(view.confidence)}）"),
            ("view_variance", repr(float(view.view_variance))),
            ("Omega", repr(float(view.Omega))),
            ("lambda_raw", f"{repr(float(view.lam_raw))}（{_percent(view.lam_raw, signed=True)}）"),
            ("lambda", f"{repr(float(view.lam))}（{_percent(view.lam, signed=True)}）"),
            ("source_signal_ids", "、".join(view.source_signal_ids) or "—"),
            ("P 推导", view.P_derivation),
            ("Q 推导", view.Q_derivation),
            ("融合推导", view.derivation),
        )
        for index, (field, value) in enumerate(rows):
            table.add_row(view.view_id if index == 0 else "", field, value)
    if not views:
        table.add_row("—", "状态", "无战术观点")
    console.print(table)


def _signal_relationships(
    record: DecisionRecord,
    selected_views: list[View],
    *,
    filtered: bool,
) -> tuple[list[str], dict[str, list[str]]]:
    relations: dict[str, list[str]] = defaultdict(list)
    for view in selected_views:
        for signal_id in view.source_signal_ids:
            if view.view_id not in relations[signal_id]:
                relations[signal_id].append(view.view_id)

    all_signal_ids = _ordered_signal_ids(record)
    risk_parity_ids = [
        signal_id for signal_id in all_signal_ids
        if (signal := record.signals_by_id.get(signal_id)) is not None
        and signal.method == "risk_parity"
    ]
    for signal_id in risk_parity_ids:
        relations[signal_id].insert(0, "Risk Parity 战略先验")

    if filtered:
        ordered = list(dict.fromkeys([
            *risk_parity_ids,
            *(signal_id for view in selected_views for signal_id in view.source_signal_ids),
        ]))
    else:
        ordered = list(all_signal_ids)
        ordered.extend(
            signal_id
            for view in selected_views
            for signal_id in view.source_signal_ids
            if signal_id not in ordered
        )
        for signal_id in ordered:
            if not relations[signal_id]:
                relations[signal_id].append("未形成观点")
    return ordered, relations


def _print_signals(
    console: Console,
    record: DecisionRecord,
    signal_ids: list[str],
    relations: dict[str, list[str]],
    warnings: list[str],
) -> None:
    details = Table(title="观点 → 信号")
    details.add_column("关系", overflow="fold")
    details.add_column("信号技术标识", overflow="fold")
    details.add_column("字段")
    details.add_column("值", overflow="fold")

    inputs = Table(title="信号 → 输入哈希")
    inputs.add_column("信号技术标识", overflow="fold")
    inputs.add_column("data_id", overflow="fold")
    inputs.add_column("source", overflow="fold")
    inputs.add_column("as-of")
    inputs.add_column("hash", overflow="fold")
    inputs.add_column("记录指纹前缀匹配")

    for signal_id in signal_ids:
        signal = record.signals_by_id.get(signal_id)
        relationship = "\n".join(relations.get(signal_id) or ["未形成观点"])
        if signal is None:
            warnings.append(f"观点引用了缺失信号 {signal_id}")
            details.add_row(relationship, signal_id, "状态", "来源信号缺失")
            inputs.add_row(signal_id, "—", "—", "—", "—", "异常")
            continue
        rows = (
            ("方法", _method_name(signal)),
            ("view_type", signal.view_type),
            ("confidence", f"{repr(float(signal.confidence))}（{_percent(signal.confidence)}）"),
            ("abstain", _canonical(signal.abstain) if signal.abstain else "无"),
            ("agent / version", f"{signal.agent_id} / {signal.agent_version}"),
            ("code_version", signal.code_version),
            ("params", _canonical(signal.params)),
            ("source_refs", _canonical(signal.source_refs)),
            ("derivation", signal.derivation),
            ("rationale", signal.rationale),
        )
        for index, (field, value) in enumerate(rows):
            details.add_row(
                relationship if index == 0 else "",
                signal_id if index == 0 else "",
                field,
                value,
            )
        if not signal.inputs:
            inputs.add_row(signal_id, "—", "—", "—", "—", "无输入")
            continue
        for data_input in signal.inputs:
            matches = bool(data_input.hash) and record.input_fingerprint.startswith(data_input.hash)
            if not matches:
                warnings.append(
                    f"{signal_id} 的输入 {data_input.data_id} hash 与记录指纹前缀不匹配")
            inputs.add_row(
                signal_id,
                data_input.data_id,
                data_input.source,
                data_input.asof,
                data_input.hash,
                "是" if matches else "异常",
            )
    console.print(details)
    console.print(inputs)


def _print_warnings(console: Console, warnings: list[str]) -> None:
    unique = list(dict.fromkeys(warnings))
    if not unique:
        return
    table = Table(title="完整性警告")
    table.add_column("序号", justify="right")
    table.add_column("说明")
    for index, warning in enumerate(unique, start=1):
        table.add_row(str(index), warning)
    console.print(table)


@app.command("run")
def run_command(
    scenario: Annotated[str | None, typer.Option("--scenario", help="Demo 情景 ID")] = None,
    asof: Annotated[str | None, typer.Option("--asof", help="决策日期 YYYY-MM-DD")] = None,
) -> None:
    """运行一次确定性决策、原子落库并显示三层摘要。"""
    scenario_id, decision_asof = _resolve_run_inputs(scenario, asof)
    try:
        generated = run_decision_cached(scenario_id, decision_asof, AllocationConfig())
    except (DataError, InfeasibleConstraintsError) as exc:
        _fail(f"决策引擎中止（{type(exc).__name__}）：{exc}", code=1)
    record = store.save(generated)
    outcomes.store_pending(record)
    outcomes.resolve_pending()
    _print_run_summary(record)


@app.command("backtest")
def backtest_command() -> None:
    """运行默认配置的 walk-forward 回测并显示指标摘要。"""
    _print_backtest(run_backtest(AllocationConfig()))


@app.command("trace")
def trace_command(
    decision_id: Annotated[str, typer.Argument(help="不可变决策 ID")],
    view_id: Annotated[str | None, typer.Option("--view", help="只下钻指定观点 ID")] = None,
) -> None:
    """沿桶归因、观点、信号下钻到输入哈希。"""
    record = _load_record(decision_id)
    try:
        all_views = _record_views(record)
    except (TypeError, ValidationError) as exc:
        _fail(f"决策记录中的观点结构损坏（{type(exc).__name__}）", code=1)

    duplicate_ids = sorted({
        view.view_id for view in all_views
        if sum(candidate.view_id == view.view_id for candidate in all_views) > 1
    })
    if view_id is not None:
        matches = [view for view in all_views if view.view_id == view_id]
        if not matches:
            _fail(f"观点不存在：{view_id}")
        if len(matches) > 1:
            _fail(f"记录含重复观点 ID，无法唯一筛选：{view_id}", code=1)
        selected_views = matches
    else:
        selected_views = all_views

    registered_ids = {view.view_id for view in all_views}
    orphan_ids = _orphan_attribution_ids(record, registered_ids)
    segment_ids = [view.view_id for view in selected_views]
    if view_id is None:
        segment_ids.extend(orphan_ids)

    warnings = [f"记录含重复观点 ID：{item}" for item in duplicate_ids]
    warnings.extend(f"归因含未注册观点键：{item}" for item in orphan_ids)
    console = _console()

    metadata = Table(title="不可变决策血缘")
    metadata.add_column("字段")
    metadata.add_column("值", overflow="fold")
    for field, value in (
        ("decision_id", record.decision_id),
        ("scenario", record.scenario_id),
        ("as-of", record.asof),
        ("mode", record.mode),
        ("input_fingerprint", record.input_fingerprint),
        ("code_version", record.code_version),
    ):
        metadata.add_row(field, str(value))
    console.print(metadata)

    _print_attribution(console, record, all_views, segment_ids, warnings)
    _print_views(console, record, selected_views)
    signal_ids, relationships = _signal_relationships(
        record, selected_views, filtered=view_id is not None)
    _print_signals(console, record, signal_ids, relationships, warnings)
    _print_warnings(console, warnings)


@app.command("report")
def report_command(
    decision_id: Annotated[str, typer.Argument(help="不可变决策 ID")],
) -> None:
    """把确定性 Markdown 决策纪要原样写到 stdout。"""
    record = _load_record(decision_id)
    typer.echo(write_decision_report(record), nl=False)


if __name__ == "__main__":  # pragma: no cover - `python -m app.cli` 兼容入口
    app()
