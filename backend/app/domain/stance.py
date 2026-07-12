"""七桶目标权重相对 Risk Parity 先验的五档立场刻度。

立场只由确定性代码根据 ``target - prior`` 映射；周报、前端与
outcomes analysis 均必须复用本模块，不得各自定义阈值或方向。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from decimal import Decimal

STANCE_5_TIER = ("显著超配", "超配", "中性", "低配", "显著低配")
STANCE_NEUTRAL = "中性"

_OVERWEIGHT_THRESHOLD = 0.004  # 0.4 个百分点
_SIGNIFICANT_THRESHOLD = 0.02  # 2 个百分点


def stance_from_delta(delta: float) -> str:
    """将权重差（小数口径）映射为五档立场，达到阈值即进入外档。"""
    if not math.isfinite(delta):
        raise ValueError(f"立场权重差必须为有限数: {delta!r}")
    if delta >= _SIGNIFICANT_THRESHOLD:
        return STANCE_5_TIER[0]
    if delta >= _OVERWEIGHT_THRESHOLD:
        return STANCE_5_TIER[1]
    if delta <= -_SIGNIFICANT_THRESHOLD:
        return STANCE_5_TIER[4]
    if delta <= -_OVERWEIGHT_THRESHOLD:
        return STANCE_5_TIER[3]
    return STANCE_NEUTRAL


def _ordered_bucket_ids(target: Mapping[str, float],
                        bucket_ids: Iterable[str] | None) -> list[str]:
    """显式顺序原样保留；缺省时按桶 id 排序，避免输入字典来源影响输出。"""
    return list(bucket_ids) if bucket_ids is not None else sorted(target)


def bucket_stances_from_weights(
    prior: Mapping[str, float],
    target: Mapping[str, float],
    bucket_ids: Iterable[str] | None = None,
) -> dict[str, str]:
    """按桶生成完整五档立场；缺桶会以 ``KeyError`` 响亮失败。

    权重已是落库十进制小数，先按其字符串值做 Decimal 相减，避免
    ``0.104 - 0.1`` 在二进制浮点中变成 ``0.003999…`` 而误掉内档。
    """
    ids = _ordered_bucket_ids(target, bucket_ids)
    return {
        bucket: stance_from_delta(float(
            Decimal(str(target[bucket])) - Decimal(str(prior[bucket]))))
        for bucket in ids
    }


def resolve_bucket_stances(
    stored: Mapping[str, str] | None,
    prior: Mapping[str, float],
    target: Mapping[str, float],
    bucket_ids: Iterable[str] | None = None,
) -> dict[str, str]:
    """完整新记录直接消费落库立场；仅为旧/部分记录补算缺失桶。"""
    ids = _ordered_bucket_ids(target, bucket_ids)
    stored = stored or {}
    for stance in stored.values():
        if stance not in STANCE_5_TIER:
            raise ValueError(f"未知立场档位: {stance!r}")
    missing = [bucket for bucket in ids if bucket not in stored]
    fallback = bucket_stances_from_weights(prior, target, missing) if missing else {}
    return {bucket: stored[bucket] if bucket in stored else fallback[bucket] for bucket in ids}


def stance_direction(stance: str) -> int:
    """返回立场方向：超配 ``+1``，中性 ``0``，低配 ``-1``。"""
    if stance not in STANCE_5_TIER:
        raise ValueError(f"未知立场档位: {stance!r}")
    idx = STANCE_5_TIER.index(stance)
    return 1 if idx < 2 else (-1 if idx > 2 else 0)
