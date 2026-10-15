"""不可变 DecisionRecord 存储（结构清晰的本地 JSON）。

每次运行落一个只写一次的 JSON 文件；decision_id 由输入指纹派生，
相同输入天然幂等（不会产生第二份不同内容的记录）。
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from ..schemas.decision import DecisionRecord

ROOT = Path(__file__).resolve().parents[3]
RUNS = ROOT / "data" / "runs"
# 存储上限：公网演示时防止有人换着参数反复运行把磁盘写满；超出后淘汰最早写入的记录
MAX_RECORDS = int(os.getenv("AIC_MAX_DECISION_RECORDS", "1000"))


def _path(decision_id: str) -> Path:
    return RUNS / f"{decision_id}.json"


def save(record: DecisionRecord) -> DecisionRecord:
    RUNS.mkdir(parents=True, exist_ok=True)
    path = _path(record.decision_id)
    if path.exists():  # 不可变：已存在即返回原记录
        try:
            return DecisionRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            pass  # 并发半写残留：用本次（确定性相同的）记录原子覆盖
    _evict_oldest()
    # 原子写（唯一临时名 + os.replace）：并发请求写同一决策时，
    # 读者永远只能看到完整文件，不会读到半写状态（CI 并发曾暴露此竞态）
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return record


def _evict_oldest() -> None:
    """写入新记录前，若已达到存储上限，按写入时间淘汰最早的记录，给新记录腾出位置。"""
    files = list(RUNS.glob("dec_*.json"))
    excess = len(files) - MAX_RECORDS + 1
    if excess <= 0:
        return
    for p in sorted(files, key=lambda f: f.stat().st_mtime)[:excess]:
        p.unlink(missing_ok=True)


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
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return payload
