"""DecisionRecord → DecisionTraceBundle（前端消费形状，交接 MD 第 6 节）。

前端只渲染本数据包，不自行重算；bundle 内所有数字来自 DecisionRecord。
"""

from __future__ import annotations

from ..domain import universe
from ..schemas.decision import DecisionRecord


def to_bundle(record: DecisionRecord) -> dict:
    uni = universe.load_universe()
    prior_assets = record.prior.w_strategic
    prior_buckets = universe.aggregate_to_buckets(prior_assets)
    prior_classes = universe.aggregate_to_classes(prior_buckets)

    # 桶级先验隐含收益（桶内按先验权重加权）
    pi_buckets: dict[str, float] = {}
    for b in universe.bucket_ids():
        members = universe.assets_in_bucket(b)
        wsum = sum(prior_assets[a] for a in members)
        pi_buckets[b] = round(
            sum(record.prior.pi[a] * prior_assets[a] for a in members) / wsum, 5) \
            if wsum > 1e-12 else 0.0

    assets = [{
        **a,
        "prior": round(prior_assets[a["id"]], 6),
        "target": record.target_weights[a["id"]],
    } for a in uni["assets"]]

    return {
        "decision_id": record.decision_id,
        "asof": record.asof,
        "scenario_id": record.scenario_id,
        "mode": record.mode,
        "conclusion": record.conclusion,
        "display_buckets": uni["display_buckets"],
        "asset_classes": uni["asset_classes"],
        "assets": assets,
        "input_signals": record.input_signals,
        "signals_by_id": {k: v.model_dump() for k, v in record.signals_by_id.items()},
        "prior": {
            "w_strategic": prior_assets,
            "pi": record.prior.pi,
            "delta": record.prior.delta,
            "tau": record.prior.tau,
            "bucket_weights": prior_buckets,
            "class_weights": prior_classes,
            "pi_buckets": pi_buckets,
        },
        "bl_inputs": record.bl_inputs,
        "posterior_ER": record.posterior_ER,
        "target_weights": record.target_weights,
        "bucket_weights": record.bucket_weights,
        "class_weights": record.class_weights,
        "attribution": record.attribution,
        "guardrail_actions": [a.model_dump() for a in record.guardrail_actions],
        "checks": record.checks,
        "config": record.config,
        "input_fingerprint": record.input_fingerprint,
        "engine_runtime_ms": record.engine_runtime_ms,
        "code_version": record.code_version,
        "created_at": record.created_at,
    }
