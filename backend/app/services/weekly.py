"""周度纪要：从本周 DecisionRecord 与上周对比结构化生成。

所有数字从结构化数据插入，不由 LLM 编造；支持 Markdown 导出。
"""

from __future__ import annotations

import pandas as pd

from ..domain import universe
from ..domain.market_data import _prices, trading_dates
from ..domain.pipeline import run_decision_cached as run_decision
from ..schemas.config import AllocationConfig

BUCKET_ZH = {"cn_equity": "中国股票", "foreign_equity": "外国股票", "cn_bond": "中国债券",
             "foreign_bond": "外国债券", "commodity": "商品", "fx": "外汇", "cash": "现金"}
METHOD_ORDER = ["risk_parity", "tsmom", "clock", "erp"]


def build_weekly(scenario_id: str, asof: str, config: AllocationConfig) -> dict:
    dates = trading_dates()
    dates = dates[dates <= pd.Timestamp(asof)]
    this_day = dates[-1]
    prev_day = dates[-6] if len(dates) > 6 else dates[0]

    record = run_decision(scenario_id, this_day.date().isoformat(), config)
    prev_record = run_decision(scenario_id, prev_day.date().isoformat(), config, mode="weekly_prev")

    prices = _prices()
    week_ret = {}
    for b in universe.bucket_ids():
        if b == "cash":
            continue
        cols = universe.assets_in_bucket(b)
        rel = (prices.loc[this_day, cols] / prices.loc[prev_day, cols] - 1)
        week_ret[b] = round(float(rel.mean()), 4)

    signals = []
    for sid in record.input_signals:
        s = record.signals_by_id[sid]
        signals.append({
            "method": s.method, "method_name": s.method_name, "layer": s.layer,
            "confidence": s.confidence, "rationale": s.rationale,
            "abstain": s.abstain, "signal_id": s.signal_id,
        })

    changes = []
    for b in universe.bucket_ids():
        delta = record.bucket_weights[b] - prev_record.bucket_weights[b]
        if abs(delta) > 0.002:
            changes.append({"bucket": b, "label": BUCKET_ZH[b],
                            "prev": prev_record.bucket_weights[b],
                            "now": record.bucket_weights[b], "delta": round(delta, 4)})
    changes.sort(key=lambda x: -abs(x["delta"]))

    triggered = [a.model_dump() for a in record.guardrail_actions if a.triggered]
    prior_b = universe.aggregate_to_buckets(record.prior.w_strategic)
    tactical = {b: round(record.bucket_weights[b] - prior_b[b], 4)
                for b in universe.bucket_ids()
                if abs(record.bucket_weights[b] - prior_b[b]) > 0.002}

    report = {
        "week_of": this_day.date().isoformat(),
        "prev_ref": prev_day.date().isoformat(),
        "decision_id": record.decision_id,
        "scenario_id": scenario_id,
        "market_summary": week_ret,
        "signals": signals,
        "strategic_base": {b: round(v, 4) for b, v in prior_b.items()},
        "tactical_tilts": tactical,
        "target_classes": record.class_weights,
        "target_buckets": record.bucket_weights,
        "weight_changes": changes,
        "risk_events": triggered,
        "guardrail_summary": {
            "total": len(record.guardrail_actions),
            "triggered": len(triggered),
        },
        "checks": record.checks,
        "conclusion": record.conclusion,
        "data_note": "Demo 合成数据；所有数字来自 DecisionRecord 与价格面板，无 LLM 生成数字。",
    }
    report["markdown"] = _to_markdown(report)
    return report


def _fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _to_markdown(r: dict) -> str:
    lines = [
        f"# 周度投资纪要 · {r['week_of']}",
        "",
        f"> 决策批次 `{r['decision_id']}` · 情景 `{r['scenario_id']}` · 数据为 Demo 演示",
        "",
        "## 一、本周市场速览",
        "",
        "| 资产桶 | 周涨跌 |", "|---|---|",
        *[f"| {BUCKET_ZH[b]} | {v * 100:+.2f}% |" for b, v in r["market_summary"].items()],
        "",
        "## 二、四方法信号",
        "",
    ]
    for s in r["signals"]:
        layer = "战略底仓" if s["layer"] == "strategic" else "战术偏离"
        lines.append(f"- **{s['method_name']}**（{layer}，置信度 {s['confidence']:.0%}）："
                     f"{s['rationale']}")
    lines += [
        "",
        "## 三、战略底仓（Risk Parity）",
        "",
        "| 资产桶 | 战略权重 |", "|---|---|",
        *[f"| {BUCKET_ZH[b]} | {_fmt_pct(v)} |" for b, v in r["strategic_base"].items()],
        "",
        "## 四、战术偏离（Black-Litterman Model 融合）",
        "",
    ]
    if r["tactical_tilts"]:
        lines += [f"- {BUCKET_ZH[b]}：{v * 100:+.1f} 个百分点" for b, v in r["tactical_tilts"].items()]
    else:
        lines.append("- 本周战术观点接近中性")
    lines += [
        "",
        "## 五、目标权重与变化",
        "",
        "| 大类 | 目标权重 |", "|---|---|",
        *[f"| {c} | {_fmt_pct(v)} |" for c, v in r["target_classes"].items()],
        "",
    ]
    if r["weight_changes"]:
        lines += ["与上周相比的主要变化：", ""]
        lines += [f"- {c['label']}：{_fmt_pct(c['prev'])} → {_fmt_pct(c['now'])}"
                  f"（{c['delta'] * 100:+.1f}pp）" for c in r["weight_changes"]]
    else:
        lines.append("与上周相比目标权重基本稳定（变化 < 0.2pp）。")
    lines += [
        "",
        "## 六、风控状态",
        "",
        f"- 风控规则 {r['guardrail_summary']['total']} 条，触发 {r['guardrail_summary']['triggered']} 条",
    ]
    for t in r["risk_events"]:
        lines.append(f"- ⚠️ {t['label']}：{t['detail']}")
    lines += [
        "",
        "## 七、结论与调仓建议",
        "",
        r["conclusion"],
        "",
        "---",
        f"*{r['data_note']}*",
    ]
    return "\n".join(lines)
