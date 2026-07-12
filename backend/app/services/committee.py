"""委员会正反检验：对最终配置的机器化「质疑-回应」叙事。

借鉴 TradingAgents 的 bull/bear 辩论形态，但完全去 LLM 化（V3 第七节明确
多 agent 自由对话是 Prompt Infection 攻击面）：正反论据全部由规则从已落库
的 DecisionRecord 抽取，模板渲染，每条论据携带可回跳的血缘引用
（view_id / signal_id / rule），裁决由计分规则给出。
"""

from __future__ import annotations

from ..domain.labels import BUCKET_ZH
from ..schemas.decision import DecisionRecord
METHOD_NAMES = {"risk_parity": "Risk Parity", "tsmom": "Time Series Momentum",
                "clock": "Merrill Lynch Investment Clock", "erp": "Equity Risk Premium"}


def _view_method(record: DecisionRecord, view: dict) -> str:
    sids = view.get("source_signal_ids") or []
    if sids and sids[0] in record.signals_by_id:
        return record.signals_by_id[sids[0]].method
    return "unknown"


def build_committee_review(record: DecisionRecord) -> dict:
    """返回 {challenges: [{id, text, refs, response: {text, refs}}], verdict}。"""
    views = record.bl_inputs.get("views", [])
    challenges: list[dict] = []

    # --- 质疑 1：被截断的观点（原始判断远强于最终采纳量） ---
    capped = [v for v in views
              if v.get("lambda", 0.0) != 0.0
              and abs(v.get("lambda", 0.0)) < abs(v.get("lambda_raw", 0.0))]
    for v in capped:
        method = _view_method(record, v)
        challenges.append({
            "id": f"challenge_capped_{v['view_id']}",
            "kind": "capped",
            "text": f"「{v.get('label', v['view_id'])}」的原始推力 λ={v.get('lambda_raw', 0):+.4f} "
                    f"被截断到 {v.get('lambda', 0):+.4f}——{METHOD_NAMES.get(method, method)} "
                    "的判断强度远超最终采纳量，是否低估了该观点？",
            "refs": {"view_id": v["view_id"], "signal_ids": v.get("source_signal_ids", [])},
            "response": {
                "text": "截断是 Idzorek 式单观点推力上限的既定纪律：低波动腿的 λ 在无约束"
                        "解中天然放大，不设上限会让单一观点主导整个组合。原始 λ 已完整"
                        "落库，可在技术工作台复核。",
                "refs": {"view_id": v["view_id"]},
            },
        })

    # --- 质疑 2：未采纳的观点（方向纪律拒绝） ---
    rejected = [v for v in views
                if v.get("lambda", 0.0) == 0.0 and v.get("lambda_raw", 0.0) != 0.0]
    for v in rejected:
        method = _view_method(record, v)
        challenges.append({
            "id": f"challenge_rejected_{v['view_id']}",
            "kind": "rejected",
            "text": f"{METHOD_NAMES.get(method, method)} 的「{v.get('label', v['view_id'])}」"
                    "被完全弃用（λ=0）——一位专家的意见被无视了？",
            "refs": {"view_id": v["view_id"], "signal_ids": v.get("source_signal_ids", [])},
            "response": {
                "text": "联合贝叶斯融合中该观点被同资产上更强的观点支配，原始 λ 与其自身"
                        "判断方向相反；方向纪律选择显式置零并留痕，而不是让观点以反向"
                        "出现在归因里误导审计。",
                "refs": {"view_id": v["view_id"]},
            },
        })

    # --- 质疑 3：方法间方向冲突（同一桶上有正有负的观点贡献） ---
    for bucket, parts in record.attribution.items():
        view_parts = {k: x for k, x in parts.items() if k not in ("prior", "guardrail")}
        pos = [k for k, x in view_parts.items() if x > 5e-4]
        neg = [k for k, x in view_parts.items() if x < -5e-4]
        if pos and neg:
            challenges.append({
                "id": f"challenge_conflict_{bucket}",
                "kind": "conflict",
                "text": f"{BUCKET_ZH.get(bucket, bucket)}上专家意见相互冲突："
                        f"{len(pos)} 条观点加仓、{len(neg)} 条观点减仓——委员会真的有共识吗？",
                "refs": {"bucket": bucket, "view_ids": pos + neg},
                "response": {
                    "text": "分歧本身是委员会架构的特性而非缺陷：各方法收益来源正交、"
                            "失效场景错开。Black-Litterman 按各观点的不确定性 Ω 加权融合，"
                            f"{BUCKET_ZH.get(bucket, bucket)}的净偏离为 "
                            f"{sum(view_parts.values()) * 100:+.1f} 个百分点，"
                            "每一段贡献都可展开复核。",
                    "refs": {"bucket": bucket},
                },
            })

    # --- 质疑 4：触发的风控规则 ---
    triggered = [a for a in record.guardrail_actions if a.triggered]
    for a in triggered:
        challenges.append({
            "id": f"challenge_guardrail_{a.rule}",
            "kind": "guardrail",
            "text": f"风控规则「{a.label}」被触发（{a.detail}）——"
                    "无约束的委员会意见本身是越界的？",
            "refs": {"rule": a.rule},
            "response": {
                "text": "是，这正是三层架构的设计：观点层只负责表达判断，硬约束由风控"
                        "投影统一执行；裁剪量作为独立的「风控段」入账，归因仍严格闭合，"
                        "裁剪前后的权重都可审计。",
                "refs": {"rule": a.rule},
            },
        })

    # --- 质疑 5：弃权与降级（信息缺失） ---
    for d in record.degraded_inputs:
        challenges.append({
            "id": f"challenge_degraded_{d['input']}",
            "kind": "degraded",
            "text": f"{METHOD_NAMES.get(d['input'], d['input'])} 本批次缺席"
                    f"（{d['reason'][:60]}）——委员会在信息不全的情况下开会？",
            "refs": {"method": d["input"]},
            "response": {
                "text": "缺数据弃权优于硬凑信号（V3 容错纪律）：该方法的观点不进入 P/Q/Ω，"
                        "融合自动退回其余专家与 Risk Parity 先验，降级事实已记入决策记录。",
                "refs": {"method": d["input"]},
            },
        })

    # --- 裁决计分（纯规则） ---
    adopted = [v for v in views if v.get("lambda", 0.0) != 0.0]
    score = {
        "views_total": len(views),
        "views_adopted": len(adopted),
        "views_capped": len(capped),
        "views_rejected": len(rejected),
        "guardrails_triggered": len(triggered),
        "degraded_inputs": len(record.degraded_inputs),
        "closure_ok": bool(record.checks.get("attribution_closure")),
    }
    concerns = len(rejected) + len(triggered) + len(record.degraded_inputs)
    if not score["closure_ok"]:
        verdict_text = "闭合校验未通过，配置不予放行。"
        verdict = "blocked"
    elif concerns == 0 and not capped:
        verdict_text = f"全部 {len(views)} 条观点议案顺利采纳，风控无触发，配置通过质询。"
        verdict = "clean_pass"
    else:
        verdict_text = (f"{len(views)} 条议案中 {len(adopted)} 条被采纳"
                        f"（截断 {len(capped)}、未采纳 {len(rejected)}），"
                        f"风控触发 {len(triggered)} 项均已投影处理"
                        + (f"，{len(record.degraded_inputs)} 项输入降级已留痕" if record.degraded_inputs else "")
                        + "；质询意见均有据可查，配置有保留地通过。")
        verdict = "pass_with_notes"
    return {
        "challenges": challenges,
        "verdict": {"result": verdict, "text": verdict_text, "score": score},
        "note": "正反论据由规则从 DecisionRecord 确定性抽取，无 LLM 参与；每条可回跳血缘。",
    }
