"""代码版本标识（写入血缘字段 code_version）。"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENGINE_VERSION = "v1.0.0"


@lru_cache(maxsize=1)
def code_version() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        return f"git:{sha}"
    except Exception:
        return f"engine:{ENGINE_VERSION}"
