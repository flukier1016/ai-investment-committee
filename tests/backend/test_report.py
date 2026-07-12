"""决策纪要导出防线。

防止 Markdown 导出丢失三层权重、观点参数、归因/风控或血缘，锁定逐字确定性、
旧记录五档立场中央补算，以及下载 API 的不可变落库同源、MIME 与 404 契约。
"""

from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient

from app.domain import universe
from app.domain.labels import BUCKET_ZH, CLASS_ZH
from app.main import app
from app.schemas.decision import DecisionRecord
from app.services import store
from app.services.report import write_decision_report


SECTION_HEADINGS = (
    "## 一、摘要",
    "## 二、三层权重",
    "## 三、Black-Litterman Model 观点与归因",
    "## 四、风控闸门与闭合检查（技术审计区）",
    "## 五、血缘、降级与审批（技术区）",
)
METHOD_NAMES = (
    "Risk Parity",
    "Time Series Momentum",
    "Merrill Lynch Investment Clock",
    "Equity Risk Premium",
    "Black-Litterman Model",
)
FORBIDDEN_METHOD_ABBREVIATION = re.compile(
    r"(?<![A-Za-z0-9_])(?:CTA|TSMOM|ERP|BL)(?![A-Za-z0-9_])"
)


def _cells(line: str) -> list[str]:
    stripped = line.strip()
    body = stripped[1:-1] if stripped.startswith("|") and stripped.endswith("|") else stripped
    cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", body)]
    return [
        re.sub(r"\\([\\`*_{}\[\]()#!|~])", r"\1", cell)
        for cell in cells
    ]


def _rendered_plain_text(markdown: str) -> str:
    return re.sub(r"\\([\\`*_{}\[\]()#!|~])", r"\1", markdown)


def _markdown_tables(markdown: str) -> list[tuple[list[str], list[list[str]]]]:
    """提取标准 Markdown 表，返回（表头，数据行）；避免按固定行号做脆弱断言。"""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in [*markdown.splitlines(), ""]:
        if line.startswith("|") and line.endswith("|"):
            current.append(line)
        elif current:
            blocks.append(current)
            current = []

    tables = []
    for block in blocks:
        if len(block) < 2:
            continue
        separator = _cells(block[1])
        if not separator or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
            continue
        tables.append((_cells(block[0]), [_cells(line) for line in block[2:]]))
    return tables


def _table_with_header(
    tables: list[tuple[list[str], list[list[str]]]], required: set[str]
) -> list[list[str]]:
    return _table_and_header(tables, required)[1]


def _table_and_header(
    tables: list[tuple[list[str], list[list[str]]]], required: set[str]
) -> tuple[list[str], list[list[str]]]:
    for header, rows in tables:
        normalized_header = [_inline_code_value(cell) for cell in header]
        if required.issubset(normalized_header):
            return normalized_header, rows
    raise AssertionError(f"未找到表头字段：{sorted(required)}")


def _percent(value: float, *, signed: bool = False) -> str:
    return f"{float(value):{ '+' if signed else ''}.6%}"


def _inline_code_value(cell: str) -> str:
    return cell.strip().strip("` ").strip()


def test_report_is_byte_deterministic_and_covers_five_sections_and_three_layers(record):
    first = write_decision_report(record)
    second = write_decision_report(record)

    assert first.encode("utf-8") == second.encode("utf-8")
    assert first.endswith("\n")
    assert tuple(re.findall(r"^## .+$", first, flags=re.MULTILINE)) == SECTION_HEADINGS

    tables = _markdown_tables(first)
    class_rows = _table_with_header(tables, {"大类", "目标权重"})
    bucket_rows = _table_with_header(tables, {"桶", "目标权重", "五档立场"})
    asset_rows = _table_with_header(tables, {"桶", "资产", "代码", "目标权重"})

    assert len(class_rows) == 5
    assert len(bucket_rows) == 7
    assert len(asset_rows) == 27

    prior_buckets = universe.aggregate_to_buckets(record.prior.w_strategic)
    prior_classes = universe.aggregate_to_classes(prior_buckets)
    expected_classes = []
    for class_id in universe.class_ids():
        prior = prior_classes[class_id]
        target = record.class_weights[class_id]
        expected_classes.append([
            CLASS_ZH[class_id], _percent(prior), _percent(target),
            _percent(target - prior, signed=True),
        ])
    assert class_rows == expected_classes

    expected_buckets = []
    for bucket_id in universe.bucket_ids():
        prior = prior_buckets[bucket_id]
        target = record.bucket_weights[bucket_id]
        expected_buckets.append([
            BUCKET_ZH[bucket_id], _percent(prior), _percent(target),
            _percent(target - prior, signed=True), record.bucket_stances[bucket_id],
        ])
    assert bucket_rows == expected_buckets

    expected_assets = []
    for asset in universe.load_universe()["assets"]:
        asset_id = asset["id"]
        prior = record.prior.w_strategic[asset_id]
        target = record.target_weights[asset_id]
        expected_assets.append([
            BUCKET_ZH[asset["bucket"]], asset["name"], asset["code"],
            _percent(prior), _percent(target), _percent(target - prior, signed=True),
        ])
    assert asset_rows == expected_assets


def test_report_audits_cross_layer_mapping_not_only_each_layer_sum(record):
    clean_tables = _markdown_tables(write_decision_report(record))
    clean_audit = _table_with_header(clean_tables, {"层级", "加总", "结果（容差 1e-6）"})
    clean_status = {row[0]: row[-1] for row in clean_audit}
    assert clean_status["明细资产 → 七个资产桶"] == "通过"
    assert clean_status["七个资产桶 → 五大类"] == "通过"

    bucket_weights = dict(record.bucket_weights)
    bucket_weights["cn_equity"] += 0.01
    bucket_weights["foreign_equity"] -= 0.01
    class_weights = dict(record.class_weights)
    class_weights["equity"] += 0.01
    class_weights["bond"] -= 0.01
    tampered = record.model_copy(update={
        "bucket_weights": bucket_weights,
        "class_weights": class_weights,
    })

    assert abs(sum(tampered.bucket_weights.values()) - 1.0) < 1e-9
    assert abs(sum(tampered.class_weights.values()) - 1.0) < 1e-9
    audit = _table_with_header(
        _markdown_tables(write_decision_report(tampered)),
        {"层级", "加总", "结果（容差 1e-6）"},
    )
    status = {row[0]: row[-1] for row in audit}
    assert status["七个资产桶"] == "通过"
    assert status["五大类"] == "通过"
    assert status["明细资产 → 七个资产桶"] == "异常"
    assert status["七个资产桶 → 五大类"] == "异常"


def test_report_has_complete_raw_attribution_matrix(record):
    actual_view_ids = [
        view["view_id"]
        for view in record.bl_inputs["views"]
        if any(view["view_id"] in parts for parts in record.attribution.values())
    ]
    required_header = {"资产桶", "prior", "guardrail", "target", *actual_view_ids}
    header, rows = _table_and_header(
        _markdown_tables(write_decision_report(record)), required_header)

    expected_prefix = ["资产桶", "prior", *actual_view_ids, "guardrail", "target"]
    assert header[:len(expected_prefix)] == expected_prefix
    assert len(rows) == 7
    assert any(
        abs(parts.get("guardrail", 0.0)) > 0 for parts in record.attribution.values())

    by_bucket = {row[0]: dict(zip(header, row)) for row in rows}
    for bucket_id in universe.bucket_ids():
        cells = by_bucket[BUCKET_ZH[bucket_id]]
        parts = record.attribution[bucket_id]
        assert _inline_code_value(cells["prior"]) == repr(float(parts["prior"]))
        for view_id in actual_view_ids:
            if view_id in parts:
                assert _inline_code_value(cells[view_id]) == repr(float(parts[view_id]))
        assert _inline_code_value(cells["guardrail"]) == repr(
            float(parts.get("guardrail", 0.0)))
        assert _inline_code_value(cells["target"]) == repr(
            float(record.bucket_weights[bucket_id]))


def test_report_keeps_views_parameters_attribution_guardrails_and_full_lineage(record):
    markdown = write_decision_report(record)
    rendered_text = _rendered_plain_text(markdown)

    assert all(name in markdown for name in METHOD_NAMES)
    assert FORBIDDEN_METHOD_ABBREVIATION.search(markdown) is None
    assert "P" in markdown
    assert "Q" in markdown
    assert "confidence" in markdown
    assert "归因" in markdown
    assert "guardrail" in markdown
    assert "五档立场" in markdown

    for stance in set(record.bucket_stances.values()):
        assert stance in markdown

    for view in record.bl_inputs["views"]:
        assert view["view_id"] in rendered_text
        assert all(asset_id in rendered_text for asset_id in view["P"])
        for signal_id in view["source_signal_ids"]:
            assert signal_id in rendered_text
            signal = record.signals_by_id[signal_id]
            for input_ in signal.inputs:
                assert input_.data_id in rendered_text
                assert input_.hash in rendered_text

    for action in record.guardrail_actions:
        assert action.rule in rendered_text
        assert action.label in rendered_text


def test_report_escapes_adversarial_record_text_without_breaking_markdown(record):
    attack = (
        "pipe | tick ` <script>alert(1)</script>\r\n"
        "```evil\n## 伪造章节\n[恶意链接](javascript:alert(1))"
    )
    views = [dict(view) for view in record.bl_inputs["views"]]
    views[0] = {**views[0], "label": attack, "derivation": attack}
    first_signal_id = record.input_signals[0]
    signals = dict(record.signals_by_id)
    signals[first_signal_id] = signals[first_signal_id].model_copy(
        update={"derivation": attack})
    actions = list(record.guardrail_actions)
    actions[0] = actions[0].model_copy(update={"detail": attack})
    adversarial = record.model_copy(update={
        "conclusion": attack,
        "bl_inputs": {**record.bl_inputs, "views": views},
        "signals_by_id": signals,
        "guardrail_actions": actions,
        "config": {**record.config, attack: "injected config key"},
    })

    markdown = write_decision_report(adversarial)

    assert tuple(re.findall(r"^## .+$", markdown, flags=re.MULTILINE)) == SECTION_HEADINGS
    assert re.search(r"<\s*/?\s*script", markdown, flags=re.IGNORECASE) is None
    assert "javascript:" not in markdown.lower()
    assert r"\[恶意链接\]\(" in markdown

    fence_lines = re.findall(
        r"^(`{3,})(?:[A-Za-z0-9_-]+)?\s*$", markdown, flags=re.MULTILINE)
    assert len(fence_lines) == 2
    assert fence_lines[0] == fence_lines[1]

    tables = _markdown_tables(markdown)
    assert tables
    assert all(
        len(row) == len(header)
        for header, rows in tables
        for row in rows
    )
    guardrail_rows = _table_with_header(
        tables, {"规则技术标识", "规则", "是否触发", "详情"})
    signal_rows = _table_with_header(
        tables, {"信号技术标识", "方法", "状态", "derivation"})
    assert len(guardrail_rows) == len(record.guardrail_actions)
    assert len(signal_rows) == len(record.signals_by_id)


def test_legacy_record_without_bucket_stances_uses_central_fallback(record):
    payload = json.loads(record.model_dump_json())
    payload.pop("bucket_stances")
    legacy = DecisionRecord.model_validate(payload)

    assert legacy.bucket_stances == {}
    assert write_decision_report(legacy) == write_decision_report(record)


def test_report_api_returns_canonical_markdown_and_missing_id_is_404(
    tmp_path, monkeypatch, record
):
    runs = tmp_path / "runs"
    monkeypatch.setattr(store, "RUNS", runs)
    canonical = record.model_copy(update={"conclusion": "仅存在于不可变落库记录的结论。"})
    canonical = store.save(canonical)
    expected = write_decision_report(canonical)

    client = TestClient(app)
    response = client.get(f"/api/decisions/{canonical.decision_id}/report")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.content == expected.encode("utf-8")
    assert response.text == expected
    assert "仅存在于不可变落库记录的结论。" in response.text

    missing = client.get("/api/decisions/dec_not_exist/report")
    assert missing.status_code == 404
