"""代码版本标识（写入血缘字段 code_version）。"""

from __future__ import annotations

import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENGINE_VERSION = "v1.0.0"


@lru_cache(maxsize=1)
def code_version() -> str:
    # 容器构建上下文不复制 .git；由受校验的 OCI build arg 保留真实提交血缘。
    revision = os.getenv("APP_REVISION", "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{7,40}", revision):
        return f"git:{revision[:7].lower()}"
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        return f"git:{sha}"
    except Exception:
        return f"engine:{ENGINE_VERSION}"
