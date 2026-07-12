"""委员会正反检验：对最终配置的机器化「质疑-回应」叙事。

借鉴 TradingAgents 的 bull/bear 辩论形态，但完全去 LLM 化（V3 第七节明确
多 agent 自由对话是 Prompt Infection 攻击面）：正反论据全部由规则从已落库
的 DecisionRecord 抽取，模板渲染，每条论据携带可回跳的血缘引用
（view_id / signal_id / rule），裁决由计分规则给出。
"""

from __future__ import annotations

from ..domain import universe
from ..domain.guardrails import asset_caps
from ..domain.labels import BUCKET_ZH
from ..schemas.config import AllocationConfig
from ..schemas.decision import DecisionRecord
METHOD_NAMES = {"risk_parity": "Risk Parity", "tsmom": "Time Series Momentum",
                "clock": "Merrill Lynch Investment Clock", "erp": "Equity Risk Premium"}

# 三视角只按约束边界和闭合容差分类，不另造经验阈值；不参与权重或裁决计分。
RISK_FACT_TOL = 1e-6


def _number(value: float) -> float:
    return round(float(value), 6)


def aggressive_risk_perspective(portfolio_vol: float, target_vol: float) -> dict:
    """激进视角：只读波动预算使用率，不建议或生成任何权重。"""
    if portfolio_vol < 0 or target_vol <= 0:
        raise ValueError("波动率必须满足 portfolio_vol >= 0 且 target_vol > 0")
    utilization = portfolio_vol / target_vol
    remaining_vol = target_vol - portfolio_vol
    remaining_share = 1.0 - utilization
    if utilization < 1.0 - RISK_FACT_TOL:
        assessment = "capacity_remaining"
        interpretation = "激进视角认为仍有战术表达空间，但任何增配仍须通过硬约束。"
    elif utilization <= 1.0 + RISK_FACT_TOL:
        assessment = "at_budget"
        interpretation = "激进视角也不支持继续扩张风险，新增表达应先释放现有预算。"
    else:
        assessment = "over_budget"
        interpretation = "组合已超过波动预算，必须升级复核，不能以激进偏好绕过硬约束。"
    return {
        "id": "risk_aggressive",
        "persona": "激进视角",
        "role": "aggressive",
        "metric": "vol_budget_utilization",
        "value": _number(utilization),
        "assessment": assessment,
        "text": (f"组合事前波动 {portfolio_vol:.2%}，占目标波动 {target_vol:.2%} 的 "
                 f"{utilization:.1%}，绝对余量 {remaining_vol:.2%}。{interpretation}"),
        "metrics": {
            "portfolio_vol": _number(portfolio_vol),
            "target_vol": _number(target_vol),
            "utilization": _number(utilization),
            "remaining_vol": _number(remaining_vol),
            "remaining_budget_share": _number(remaining_share),
        },
        "refs": {
            "portfolio_vol": "checks.portfolio_vol",
            "target_vol": "config.target_vol",
        },
    }


def conservative_risk_perspective(*, subject: str, current: float, limit: float,
                                  refs: dict[str, str]) -> dict:
    """保守视角：评论最紧有效上限的绝对余量。"""
    if current < 0 or limit <= 0:
        raise ValueError("上限口径必须满足 current >= 0 且 limit > 0")
    headroom = limit - current
    if headroom < -RISK_FACT_TOL:
        assessment = "breach"
        interpretation = "保守视角要求阻断放行并升级复核。"
    elif headroom <= RISK_FACT_TOL:
        assessment = "binding"
        interpretation = "保守视角要求将这条约束列为首要复核项。"
    else:
        assessment = "headroom"
        interpretation = "保守视角确认当前仍在硬约束范围内，并保留精确余量供复核。"
    return {
        "id": "risk_conservative",
        "persona": "保守视角",
        "role": "conservative",
        "metric": "cap_headroom",
        "value": _number(headroom),
        "assessment": assessment,
        "text": (f"最紧有效上限为“{subject}”：当前 {current:.2%}，上限 {limit:.2%}，"
                 f"绝对余量 {headroom * 100:+.2f} 个百分点。{interpretation}"),
        "metrics": {
            "subject": subject,
            "current": _number(current),
            "limit": _number(limit),
            "headroom": _number(headroom),
        },
        "refs": dict(refs),
    }


def neutral_risk_perspective(asset_turnover_proxy: float, bucket_shift: float) -> dict:
    """中性视角：用桶级可解释比例评价理论换手代理是否相称。"""
    if asset_turnover_proxy < 0 or bucket_shift < 0:
        raise ValueError("换手代理与桶级净偏离不得为负")
    explainable_share = (bucket_shift / asset_turnover_proxy
                         if asset_turnover_proxy > 1e-12
                         else (1.0 if bucket_shift <= RISK_FACT_TOL else 0.0))
    intra_bucket_churn = max(asset_turnover_proxy - bucket_shift, 0.0)
    if bucket_shift > asset_turnover_proxy + RISK_FACT_TOL:
        assessment = "inconsistent"
        interpretation = "桶级净偏离大于资产换手代理，记录需复核，不能静默截断比例。"
    elif asset_turnover_proxy <= RISK_FACT_TOL:
        assessment = "no_turnover"
        interpretation = "目标与战略先验一致，没有需要解释的理论换手。"
    elif intra_bucket_churn <= RISK_FACT_TOL:
        assessment = "fully_explained"
        interpretation = "中性视角确认理论换手由可见的桶级战术偏离完全解释。"
    elif bucket_shift <= RISK_FACT_TOL:
        assessment = "intra_bucket_only"
        interpretation = "中性视角确认理论换手全部来自桶内调整，需要下钻明细归因。"
    else:
        assessment = "partly_explained"
        interpretation = "中性视角同时保留桶级偏离与桶内调整，供实施前逐项复核。"
    return {
        "id": "risk_neutral",
        "persona": "中性视角",
        "role": "neutral",
        "metric": "turnover_proportionality",
        "value": _number(explainable_share),
        "assessment": assessment,
        "text": ("这不是实际成交换手：目标相对 Risk Parity 战略先验的资产单边换手代理为 "
                 f"{asset_turnover_proxy:.2%}，桶级净偏离为 {bucket_shift:.2%}，"
                 f"可解释比例 {explainable_share:.1%}。{interpretation}"),
        "metrics": {
            "asset_turnover_proxy": _number(asset_turnover_proxy),
            "bucket_shift": _number(bucket_shift),
            "explainable_share": _number(explainable_share),
            "intra_bucket_churn": _number(intra_bucket_churn),
        },
        "refs": {
            "target": "target_weights",
            "strategic_prior": "prior.w_strategic",
            "bucket_target": "bucket_weights",
            "bucket_prior": "prior.w_strategic",
        },
    }


def _tightest_upper_limit(record: DecisionRecord,
                          config: AllocationConfig) -> dict:
    """复用风控层资产 cap，并加入桶/大类 cap，选择绝对余量最小者。"""
    asset_order = sorted(record.target_weights)
    caps = asset_caps(asset_order, config)
    asset_meta = {a["id"]: a for a in universe.load_universe()["assets"]}
    candidates: list[dict] = []
    for asset_id, cap in zip(asset_order, caps, strict=True):
        risk_cap = None
        if asset_id in config.risk_caps_wan and config.principal > 0:
            risk_cap = config.risk_caps_wan[asset_id] * 10_000 / config.principal
        base_cap = 1.0 if asset_id == "cash" else config.single_asset_cap
        # 默认现金技术 cap=100% 不参与“最近配置上限”；显式金额 cap 生效时仍须纳入。
        if asset_id == "cash" and (risk_cap is None or risk_cap >= base_cap):
            continue
        limit_ref = (f"config.risk_caps_wan.{asset_id}"
                     if risk_cap is not None and risk_cap < base_cap
                     else "config.single_asset_cap")
        current = record.target_weights[asset_id]
        candidates.append({
            "id": f"asset_cap:{asset_id}",
            "subject": f"{asset_meta[asset_id]['short_name']}明细资产上限",
            "current": current,
            "limit": float(cap),
            "refs": {"current": f"target_weights.{asset_id}", "limit": limit_ref},
        })
    candidates.extend([
        {
            "id": "bucket_cap:cn_equity",
            "subject": "中国股票桶上限",
            "current": record.bucket_weights["cn_equity"],
            "limit": config.cn_equity_cap,
            "refs": {"current": "bucket_weights.cn_equity",
                     "limit": "config.cn_equity_cap"},
        },
        {
            "id": "class_cap:equity",
            "subject": "权益大类上限",
            "current": record.class_weights["equity"],
            "limit": config.equity_class_cap,
            "refs": {"current": "class_weights.equity",
                     "limit": "config.equity_class_cap"},
        },
    ])
    return min(candidates, key=lambda item: (item["limit"] - item["current"], item["id"]))


def build_risk_perspectives(record: DecisionRecord) -> list[dict]:
    """从不可变记录派生固定顺序的三张风控视角卡，不改记录或裁决。"""
    config = AllocationConfig.model_validate(record.config)
    limit = _tightest_upper_limit(record, config)
    # 换手代理与桶级偏离必须只由落库的 6 位小数权重派生。优化器（Risk Parity ERC /
    # CVXPY 投影）全精度输出在不同 runner 硬件上有 ±1e-7 差异；这些代理是近似相等
    # 两量之比（可解释比例 ≈1.0，intra_bucket_churn≈1e-4），会把 1e-7 放大到 1e-5，
    # 与只存 6 位的固定 fixture 做精确 == 时偶发不等。落到与权重一致的 6 位精度后，
    # 相同 6 位权重必得逐字节相同的派生值（见 test_risk_perspectives 稳定性防线）。
    asset_turnover_proxy = _number(0.5 * sum(
        abs(record.target_weights[asset_id] - record.prior.w_strategic[asset_id])
        for asset_id in sorted(record.target_weights)
    ))
    missing_prior = [bucket_id for bucket_id in sorted(record.bucket_weights)
                     if "prior" not in record.attribution.get(bucket_id, {})]
    if missing_prior:
        raise ValueError(f"风控换手代理缺少桶级 prior 归因：{missing_prior}")
    # 桶级 prior 从落库的 6 位明细战略先验重新聚合并落 6 位，与资产级换手代理同源
    # 同精度；不直接引用 attribution.*.prior——后者是全精度聚合后再舍入，会把 6 位
    # 以下的求解器噪声（如 cn_bond 0.299791 vs 0.299792）经比值放大。
    bucket_prior = universe.aggregate_to_buckets(record.prior.w_strategic)
    bucket_shift = _number(0.5 * sum(
        abs(_number(record.bucket_weights[bucket_id]) - _number(bucket_prior[bucket_id]))
        for bucket_id in sorted(record.bucket_weights)
    ))
    return [
        aggressive_risk_perspective(
            float(record.checks["portfolio_vol"]), config.target_vol),
        conservative_risk_perspective(
            subject=limit["subject"], current=limit["current"], limit=limit["limit"],
            refs=limit["refs"],
        ),
        neutral_risk_perspective(asset_turnover_proxy, bucket_shift),
    ]


def _view_method(record: DecisionRecord, view: dict) -> str:
    sids = view.get("source_signal_ids") or []
    if sids and sids[0] in record.signals_by_id:
        return record.signals_by_id[sids[0]].method
    return "unknown"


def build_committee_review(record: DecisionRecord) -> dict:
    """返回确定性三视角、质疑回应与不改权重的规则裁决。"""
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
        "risk_perspectives": build_risk_perspectives(record),
        "challenges": challenges,
        "verdict": {"result": verdict, "text": verdict_text, "score": score},
        "note": ("三视角点评与正反论据均由规则从 DecisionRecord 确定性抽取，"
                 "无 LLM 参与；每条可回跳血缘。"),
    }
