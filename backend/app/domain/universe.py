"""27 明细资产宇宙：资产 → 7 展示桶 → 5 大类的静态映射。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "data" / "demo"


@lru_cache(maxsize=1)
def load_universe() -> dict:
    return json.loads((DEMO / "assets.json").read_text(encoding="utf-8"))


def asset_ids() -> list[str]:
    return [a["id"] for a in load_universe()["assets"]]


def risky_asset_ids() -> list[str]:
    return [a for a in asset_ids() if a != "cash"]


def bucket_of() -> dict[str, str]:
    return {a["id"]: a["bucket"] for a in load_universe()["assets"]}


def assets_in_bucket(bucket_id: str) -> list[str]:
    return [a["id"] for a in load_universe()["assets"] if a["bucket"] == bucket_id]


def bucket_ids() -> list[str]:
    return [b["id"] for b in load_universe()["display_buckets"]]


def class_of_bucket() -> dict[str, str]:
    return {b["id"]: b["asset_class"] for b in load_universe()["display_buckets"]}


def class_ids() -> list[str]:
    return [c["id"] for c in load_universe()["asset_classes"]]


def aggregate_to_buckets(weights: dict[str, float]) -> dict[str, float]:
    bmap = bucket_of()
    out = {b: 0.0 for b in bucket_ids()}
    for aid, w in weights.items():
        out[bmap[aid]] += w
    return {k: round(v, 10) for k, v in out.items()}


def aggregate_to_classes(bucket_weights: dict[str, float]) -> dict[str, float]:
    cmap = class_of_bucket()
    out = {c: 0.0 for c in class_ids()}
    for b, w in bucket_weights.items():
        out[cmap[b]] += w
    return {k: round(v, 10) for k, v in out.items()}
