"""不可变 DecisionRecord 存储（结构清晰的本地 JSON）。

每次运行落一个只写一次的 JSON 文件；decision_id 由输入指纹派生，
相同输入天然幂等（不会产生第二份不同内容的记录）。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..schemas.decision import DecisionRecord

ROOT = Path(__file__).resolve().parents[3]
RUNS = ROOT / "data" / "runs"


def _path(decision_id: str) -> Path:
    return RUNS / f"{decision_id}.json"


def save(record: DecisionRecord) -> DecisionRecord:
    RUNS.mkdir(parents=True, exist_ok=True)
    path = _path(record.decision_id)
    if path.exists():  # 不可变：已存在即返回原记录
        return DecisionRecord.model_validate_json(path.read_text(encoding="utf-8"))
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return record


def get(decision_id: str) -> DecisionRecord | None:
    path = _path(decision_id)
    if not path.exists():
        return None
    return DecisionRecord.model_validate_json(path.read_text(encoding="utf-8"))


def list_index() -> list[dict]:
    RUNS.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(RUNS.glob("dec_*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({
                "decision_id": d["decision_id"], "asof": d["asof"],
                "scenario_id": d["scenario_id"], "created_at": d["created_at"],
                "conclusion": d["conclusion"],
                "class_weights": d["class_weights"],
                "guardrails_triggered": sum(1 for a in d["guardrail_actions"] if a["triggered"]),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return sorted(out, key=lambda x: x["created_at"], reverse=True)


def cache_json(name: str, payload: dict | None = None) -> dict | None:
    """通用派生结果缓存（回测/日更），键含输入指纹，内容可由代码重算。"""
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"{name}.json"
    if payload is None:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload
