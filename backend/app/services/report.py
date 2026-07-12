"""不可变 DecisionRecord 的确定性 Markdown 决策纪要。

本模块只读取已经落库的决策字段与静态资产宇宙，不调用行情、信号或决策引擎，
也不写文件。相同 DecisionRecord 因而会得到逐字节相同的报告。
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from typing import Any

from ..domain import universe
from ..domain.labels import BUCKET_ZH, CLASS_ZH
from ..domain.stance import resolve_bucket_stances
from ..schemas.decision import DecisionRecord, TracedSignal, View


METHOD_NAMES = {
    "risk_parity": "Risk Parity",
    "tsmom": "Time Series Momentum",
    "clock": "Merrill Lynch Investment Clock",
    "erp": "Equity Risk Premium",
}


_MARKDOWN_PLAIN_ESCAPES = frozenset("\\`*_{}[]()#!~")


def _neutralize_protocols(value: str) -> str:
    return re.sub(r"(?i)javascript:", "javascript&#58;", value)


def _cell(value: Any) -> str:
    """把不可信字符串渲染为单行纯文本，不允许改变 Markdown 结构。"""
    raw = str(value).replace("\r\n", "\n").replace("\r", "\n")
    raw = raw.replace("\n", " ⏎ ")
    escaped = _neutralize_protocols(html.escape(raw, quote=False)).replace("|", "&#124;")
    escaped = "".join(
        f"\\{char}" if char in _MARKDOWN_PLAIN_ESCAPES else char
        for char in escaped
    )
    # 换行已被收平；这里再阻断字符串位于行首时可能形成的列表或分隔线。
    escaped = re.sub(r"^(\d+)([.)])(?=\s)", r"\1\\\2", escaped)
    escaped = re.sub(r"^([+-])(?=\s)", r"\\\1", escaped)
    escaped = re.sub(r"^(-)(?=--)", r"\\\1", escaped)
    return escaped


def _code(value: Any) -> str:
    """用长于内容中任意反引号串的定界符生成安全行内代码。"""
    raw = str(value).replace("\r\n", "\n").replace("\r", "\n")
    raw = raw.replace("\n", r"\n")
    raw = _neutralize_protocols(html.escape(raw, quote=False)).replace("|", "&#124;")
    longest = max((len(run) for run in re.findall(r"`+", raw)), default=0)
    delimiter = "`" * (longest + 1)
    if raw.startswith(("`", " ")) or raw.endswith(("`", " ")):
        raw = f" {raw} "
    return f"{delimiter}{raw}{delimiter}"


def _fenced_code(value: Any, language: str = "") -> list[str]:
    """生成无法被内容中的反引号提前闭合的 fenced code block。"""
    raw = str(value).replace("\r\n", "\n").replace("\r", "\n")
    raw = _neutralize_protocols(html.escape(raw, quote=False))
    longest = max((len(run) for run in re.findall(r"`+", raw)), default=0)
    fence = "`" * max(3, longest + 1)
    return [f"{fence}{language}", raw, fence]


def _number(value: float | int) -> str:
    """输出落库数值的稳定十进制表示，不引入二次舍入计算。"""
    if isinstance(value, int):
        return str(value)
    return repr(float(value))


def _percent(value: float, *, signed: bool = False) -> str:
    sign = "+" if signed else ""
    return f"{float(value):{sign}.6%}"


def _canonical(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(by_alias=True)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _check_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, str):
        return value
    return _canonical(value)


def _view_rows(record: DecisionRecord) -> list[View]:
    return [v if isinstance(v, View) else View.model_validate(v)
            for v in record.bl_inputs.get("views", [])]


def _ordered_signal_ids(record: DecisionRecord) -> list[str]:
    """先保留决策声明顺序，再补入 signals_by_id 中的兼容字段。"""
    ordered = list(record.input_signals)
    ordered.extend(sid for sid in record.signals_by_id if sid not in ordered)
    return ordered


def _method_name(signal: TracedSignal | None) -> str:
    if signal is None:
        return "来源信号缺失"
    return METHOD_NAMES[signal.method]


def _source_methods(record: DecisionRecord, view: View) -> str:
    methods: list[str] = []
    for signal_id in view.source_signal_ids:
        name = _method_name(record.signals_by_id.get(signal_id))
        if name not in methods:
            methods.append(name)
    return " / ".join(methods) if methods else "来源信号缺失"


def _sum(values: Iterable[float]) -> float:
    return float(sum(float(value) for value in values))


def write_decision_report(record: DecisionRecord) -> str:
    """将一条 DecisionRecord 渲染为完整、稳定且只读的 Markdown 纪要。"""
    uni = universe.load_universe()
    classes = list(uni["asset_classes"])
    buckets = list(uni["display_buckets"])
    assets = list(uni["assets"])
    asset_by_id = {asset["id"]: asset for asset in assets}

    prior_assets = record.prior.w_strategic
    prior_buckets = universe.aggregate_to_buckets(prior_assets)
    prior_classes = universe.aggregate_to_classes(prior_buckets)
    stances = resolve_bucket_stances(
        record.bucket_stances,
        prior_buckets,
        record.bucket_weights,
        [bucket["id"] for bucket in buckets],
    )
    views = _view_rows(record)
    triggered_count = sum(1 for action in record.guardrail_actions if action.triggered)

    lines = [
        "# 智策 AI 投委会决策纪要",
        "",
        f"> 技术索引（机器标识）：decision_id {_code(record.decision_id)} · "
        f"scenario_id {_code(record.scenario_id)} · mode {_code(record.mode)}",
        f"> 决策时点：{_cell(record.asof)}",
        "> 本纪要仅用于研究推演，不构成任何投资建议或交易指令。",
        "",
        "## 一、摘要",
        "",
        _cell(record.conclusion),
        "",
        "本纪要记录 Risk Parity 战略底仓，由 Time Series Momentum、"
        "Merrill Lynch Investment Clock 与 Equity Risk Premium 形成战术观点，"
        "再由 Black-Litterman Model 完成确定性融合。",
        "",
        f"- 观点数量：{len(views)}",
        f"- 风控规则：共 {len(record.guardrail_actions)} 条，触发 {triggered_count} 条",
        f"- 降级输入：{len(record.degraded_inputs)} 项",
        "- 数字口径：全部直接取自本条不可变 DecisionRecord 或由其三层权重做确定性汇总；无叙事模型参与数值计算。",
        "",
        "## 二、三层权重",
        "",
        "### 2.1 五大类",
        "",
        "| 大类 | Risk Parity 先验 | 目标权重 | 偏离 |",
        "|---|---:|---:|---:|",
    ]
    for asset_class in classes:
        class_id = asset_class["id"]
        prior = prior_classes[class_id]
        target = record.class_weights[class_id]
        lines.append(
            f"| {_cell(CLASS_ZH[class_id])} | {_percent(prior)} | "
            f"{_percent(target)} | {_percent(target - prior, signed=True)} |"
        )

    lines += [
        "",
        "### 2.2 七个资产桶",
        "",
        "| 桶 | Risk Parity 先验 | 目标权重 | 偏离 | 五档立场 |",
        "|---|---:|---:|---:|---|",
    ]
    for bucket in buckets:
        bucket_id = bucket["id"]
        prior = prior_buckets[bucket_id]
        target = record.bucket_weights[bucket_id]
        lines.append(
            f"| {_cell(BUCKET_ZH[bucket_id])} | {_percent(prior)} | "
            f"{_percent(target)} | {_percent(target - prior, signed=True)} | "
            f"{_cell(stances[bucket_id])} |"
        )

    lines += [
        "",
        "### 2.3 二十七项明细资产",
        "",
        "| 桶 | 资产 | 代码 | Risk Parity 先验 | 目标权重 | 偏离 |",
        "|---|---|---|---:|---:|---:|",
    ]
    for asset in assets:
        asset_id = asset["id"]
        prior = prior_assets[asset_id]
        target = record.target_weights[asset_id]
        lines.append(
            f"| {_cell(BUCKET_ZH[asset['bucket']])} | {_cell(asset['name'])} | "
            f"{_cell(asset['code'])} | {_percent(prior)} | {_percent(target)} | "
            f"{_percent(target - prior, signed=True)} |"
        )

    lines += [
        "",
        "## 三、Black-Litterman Model 观点与归因",
        "",
        "### 融合参数与桶级后验收益",
        "",
        f"- 风险厌恶系数 delta：{_code(_number(record.prior.delta))}",
        f"- 先验不确定性 tau：{_code(_number(record.prior.tau))}",
        "",
        "| 资产桶 | 后验期望收益 | 落库值 |",
        "|---|---:|---:|",
    ]
    for bucket in buckets:
        bucket_id = bucket["id"]
        posterior = record.posterior_ER[bucket_id]
        lines.append(
            f"| {_cell(BUCKET_ZH[bucket_id])} | {_percent(posterior, signed=True)} | "
            f"{_code(_number(posterior))} |"
        )

    if not views:
        lines += ["", "本批次没有可采纳的战术观点，Black-Litterman Model 保持先验。"]

    p_asset_order = list(record.bl_inputs.get("asset_order") or [a["id"] for a in assets])
    for index, view in enumerate(views, start=1):
        lines += [
            "",
            f"### 观点 {index} · {_cell(view.label)}",
            "",
            f"- 来源方法：{_source_methods(record, view)}",
            f"- P 推导：{_cell(view.P_derivation)}",
            f"- Q 推导：{_cell(view.Q_derivation)}",
            f"- 融合说明：{_cell(view.derivation)}",
            "",
            "| 参数 | 落库值 | 展示值 |",
            "|---|---:|---:|",
            f"| Q | {_code(_number(view.Q))} | {_percent(view.Q, signed=True)} |",
            f"| confidence | {_code(_number(view.confidence))} | {_percent(view.confidence)} |",
            f"| view_variance | {_code(_number(view.view_variance))} | "
            f"{_code(_number(view.view_variance))} |",
            f"| Omega | {_code(_number(view.Omega))} | {_code(_number(view.Omega))} |",
            f"| lambda_raw | {_code(_number(view.lam_raw))} | "
            f"{_percent(view.lam_raw, signed=True)} |",
            f"| lambda | {_code(_number(view.lam))} | {_percent(view.lam, signed=True)} |",
            "",
            "#### 完整 P（技术矩阵）",
            "",
            "| 资产技术标识 | 资产 | 代码 | 桶 | P 系数 |",
            "|---|---|---|---|---:|",
        ]
        for asset_id in p_asset_order:
            asset = asset_by_id.get(asset_id)
            if asset is None:
                lines.append(
                    f"| {_code(asset_id)} | {_cell(asset_id)} | — | — | "
                    f"{_code(_number(view.P.get(asset_id, 0.0)))} |"
                )
                continue
            lines.append(
                f"| {_code(asset_id)} | {_cell(asset['short_name'])} | {_cell(asset['code'])} | "
                f"{_cell(BUCKET_ZH[asset['bucket']])} | "
                f"{_code(_number(view.P.get(asset_id, 0.0)))} |"
            )

        lines += [
            "",
            "#### 桶级权重归因",
            "",
            "| 资产桶 | 本观点贡献 | 落库值 |",
            "|---|---:|---:|",
        ]
        for bucket in buckets:
            bucket_id = bucket["id"]
            contribution = record.attribution.get(bucket_id, {}).get(view.view_id, 0.0)
            lines.append(
                f"| {_cell(BUCKET_ZH[bucket_id])} | "
                f"{_percent(contribution, signed=True)} | {_code(_number(contribution))} |"
            )

    lines += [
        "",
        "## 四、风控闸门与闭合检查（技术审计区）",
        "",
        "### 全部风控规则",
        "",
        "| 规则技术标识 | 规则 | 是否触发 | 详情 |",
        "|---|---|---|---|",
    ]
    if record.guardrail_actions:
        for action in record.guardrail_actions:
            lines.append(
                f"| {_code(action.rule)} | {_cell(action.label)} | "
                f"{'是' if action.triggered else '否'} | {_cell(action.detail)} |"
            )
    else:
        lines.append("| — | 无风控规则 | 否 | — |")

    asset_sum = _sum(record.target_weights.values())
    bucket_sum = _sum(record.bucket_weights.values())
    class_sum = _sum(record.class_weights.values())
    asset_to_bucket: dict[str, float] = {}
    for bucket in buckets:
        bucket_id = bucket["id"]
        asset_to_bucket[bucket_id] = _sum(
            record.target_weights[asset["id"]]
            for asset in assets
            if asset["bucket"] == bucket_id
        )
    bucket_to_class = {
        asset_class["id"]: _sum(
            record.bucket_weights[bucket_id]
            for bucket_id in asset_class["bucket_ids"]
        )
        for asset_class in classes
    }
    asset_bucket_diffs = {
        bucket_id: asset_to_bucket[bucket_id] - record.bucket_weights[bucket_id]
        for bucket_id in asset_to_bucket
    }
    bucket_class_diffs = {
        class_id: bucket_to_class[class_id] - record.class_weights[class_id]
        for class_id in bucket_to_class
    }
    lines += [
        "",
        "### 三层权重闭合",
        "",
        "| 层级 | 加总 | 与 1 的差 | 结果（容差 1e-6） |",
        "|---|---:|---:|---|",
    ]
    for label, total in (("二十七项明细资产", asset_sum),
                         ("七个资产桶", bucket_sum),
                         ("五大类", class_sum)):
        difference = total - 1.0
        lines.append(
            f"| {label} | {_code(_number(total))} | {_code(_number(difference))} | "
            f"{'通过' if abs(difference) <= 1e-6 else '异常'} |"
        )

    for label, differences in (
        ("明细资产 → 七个资产桶", asset_bucket_diffs),
        ("七个资产桶 → 五大类", bucket_class_diffs),
    ):
        max_difference = max((abs(value) for value in differences.values()), default=0.0)
        lines.append(
            f"| {label} | — | {_code(_number(max_difference))} | "
            f"{'通过' if max_difference <= 1e-6 else '异常'} |"
        )

    lines += [
        "",
        "### 二十七项明细资产 → 七个资产桶逐项映射审计",
        "",
        "| 资产桶 | 成员资产技术标识 | 明细资产聚合值 | DecisionRecord 桶值 | diff | status |",
        "|---|---|---:|---:|---:|---|",
    ]
    for bucket in buckets:
        bucket_id = bucket["id"]
        member_ids = [asset["id"] for asset in assets if asset["bucket"] == bucket_id]
        aggregated = asset_to_bucket[bucket_id]
        persisted = record.bucket_weights[bucket_id]
        difference = asset_bucket_diffs[bucket_id]
        lines.append(
            f"| {_cell(BUCKET_ZH[bucket_id])} | "
            f"{'、'.join(_code(asset_id) for asset_id in member_ids)} | "
            f"{_code(_number(aggregated))} | {_code(_number(persisted))} | "
            f"{_code(_number(difference))} | "
            f"{'通过' if abs(difference) <= 1e-6 else '异常'} |"
        )

    lines += [
        "",
        "### 七个资产桶 → 五大类逐项映射审计",
        "",
        "| 大类 | 成员桶技术标识 | 桶聚合值 | DecisionRecord 大类值 | diff | status |",
        "|---|---|---:|---:|---:|---|",
    ]
    for asset_class in classes:
        class_id = asset_class["id"]
        member_ids = list(asset_class["bucket_ids"])
        aggregated = bucket_to_class[class_id]
        persisted = record.class_weights[class_id]
        difference = bucket_class_diffs[class_id]
        lines.append(
            f"| {_cell(CLASS_ZH[class_id])} | "
            f"{'、'.join(_code(bucket_id) for bucket_id in member_ids)} | "
            f"{_code(_number(aggregated))} | {_code(_number(persisted))} | "
            f"{_code(_number(difference))} | "
            f"{'通过' if abs(difference) <= 1e-6 else '异常'} |"
        )

    attribution_keys = {
        key
        for bucket_id in (bucket["id"] for bucket in buckets)
        for key in record.attribution[bucket_id]
        if key not in {"prior", "guardrail"}
    }
    ordered_view_ids = [view.view_id for view in views if view.view_id in attribution_keys]
    extra_view_ids = sorted(attribution_keys.difference(ordered_view_ids))
    attribution_columns = [*ordered_view_ids, *extra_view_ids]
    matrix_header = [
        "资产桶", "prior", *(_code(view_id) for view_id in attribution_columns),
        "guardrail", "target", "加总", "diff", "status",
    ]
    lines += [
        "",
        "### 完整桶级原始归因矩阵与闭合",
        "",
        "| " + " | ".join(matrix_header) + " |",
        "|---|" + "---:|" * (len(matrix_header) - 2) + "---|",
    ]
    for bucket in buckets:
        bucket_id = bucket["id"]
        parts = record.attribution[bucket_id]
        attribution_sum = _sum(parts.values())
        target = record.bucket_weights[bucket_id]
        difference = attribution_sum - target
        raw_values = [
            parts.get("prior", 0.0),
            *(parts.get(view_id, 0.0) for view_id in attribution_columns),
            parts.get("guardrail", 0.0),
            target,
            attribution_sum,
            difference,
        ]
        lines.append(
            f"| {_cell(BUCKET_ZH[bucket_id])} | "
            + " | ".join(_code(_number(value)) for value in raw_values)
            + f" | {'通过' if abs(difference) <= 1e-6 else '异常'} |"
        )

    lines += [
        "",
        "### DecisionRecord 全部检查项",
        "",
        "| 检查技术标识 | 落库值 |",
        "|---|---|",
    ]
    if record.checks:
        for check_id, value in record.checks.items():
            lines.append(f"| {_code(check_id)} | {_code(_check_value(value))} |")
    else:
        lines.append("| — | 无检查项 |")

    lines += [
        "",
        "## 五、血缘、降级与审批（技术区）",
        "",
        "### 决策记录技术元数据",
        "",
        "| 字段 | 值 |",
        "|---|---|",
        f"| decision_id | {_code(record.decision_id)} |",
        f"| scenario_id | {_code(record.scenario_id)} |",
        f"| mode | {_code(record.mode)} |",
        f"| input_fingerprint | {_code(record.input_fingerprint)} |",
        f"| code_version | {_code(record.code_version)} |",
        f"| created_at | {_code(record.created_at)} |",
        f"| engine_runtime_ms | {_code(_number(record.engine_runtime_ms))} |",
        f"| approver | {_code(record.approver)} |",
        "",
        "### 观点 → 信号 → 输入数据血缘索引",
        "",
        "| 观点技术标识 | 信号技术标识 | 来源方法 | data_id | source | asof | hash |",
        "|---|---|---|---|---|---|---|",
    ]

    linked_signal_ids: set[str] = set()
    for view in views:
        for signal_id in view.source_signal_ids:
            linked_signal_ids.add(signal_id)
            signal = record.signals_by_id.get(signal_id)
            if signal is None or not signal.inputs:
                lines.append(
                    f"| {_code(view.view_id)} | {_code(signal_id)} | "
                    f"{_cell(_method_name(signal))} | — | — | — | — |"
                )
                continue
            for data_input in signal.inputs:
                lines.append(
                    f"| {_code(view.view_id)} | {_code(signal_id)} | "
                    f"{_cell(_method_name(signal))} | {_code(data_input.data_id)} | "
                    f"{_cell(data_input.source)} | {_cell(data_input.asof)} | "
                    f"{_code(data_input.hash)} |"
                )

    for signal_id in _ordered_signal_ids(record):
        if signal_id in linked_signal_ids:
            continue
        signal = record.signals_by_id.get(signal_id)
        relationship = "Risk Parity 战略先验" if signal and signal.method == "risk_parity" else "未形成观点"
        if signal is None or not signal.inputs:
            lines.append(
                f"| {relationship} | {_code(signal_id)} | {_cell(_method_name(signal))} | "
                "— | — | — | — |"
            )
            continue
        for data_input in signal.inputs:
            lines.append(
                f"| {relationship} | {_code(signal_id)} | {_cell(_method_name(signal))} | "
                f"{_code(data_input.data_id)} | {_cell(data_input.source)} | "
                f"{_cell(data_input.asof)} | {_code(data_input.hash)} |"
            )

    lines += [
        "",
        "### 输入信号技术详情",
        "",
        "| 信号技术标识 | 方法 | 状态 | agent_id / agent_version | code_version | params | derivation | source_refs |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for signal_id in _ordered_signal_ids(record):
        signal = record.signals_by_id.get(signal_id)
        if signal is None:
            lines.append(
                f"| {_code(signal_id)} | 来源信号缺失 | 异常 | — | — | — | — | — |"
            )
            continue
        status = "abstain" if signal.view_type == "abstain" else "active"
        lines.append(
            f"| {_code(signal_id)} | {_cell(_method_name(signal))} | {_code(status)} | "
            f"{_code(signal.agent_id)} / {_code(signal.agent_version)} | "
            f"{_code(signal.code_version)} | {_code(_canonical(signal.params))} | "
            f"{_cell(signal.derivation)} | {_code(_canonical(signal.source_refs))} |"
        )

    lines += [
        "",
        "### 降级输入",
        "",
    ]
    if record.degraded_inputs:
        lines += ["| 序号 | 完整落库内容 |", "|---:|---|"]
        for index, degraded in enumerate(record.degraded_inputs, start=1):
            lines.append(f"| {index} | {_code(_canonical(degraded))} |")
    else:
        lines.append("无降级输入。")

    lines += [
        "",
        "### LLM trace 与审批",
        "",
        f"- approver：{_code(record.approver)}",
    ]
    if record.llm_traces:
        lines.append("- LLM trace：")
        lines.extend(f"  - {_code(trace_id)}" for trace_id in record.llm_traces)
    else:
        lines.append("- LLM trace：无")

    lines += ["", "### 确定性配置快照", ""]
    lines += _fenced_code(_canonical(record.config), "json")
    lines.append("")
    return "\n".join(lines)
