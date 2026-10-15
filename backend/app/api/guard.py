"""公网演示部署的防护：计算类 POST 接口限流。

决策运行和回测都会占用算力；开发 API 没有认证，部署到公网后任何人都能反复触发。
这里按“同一来源”和“全站”各设一个滑动窗口上限，额度放宽到正常浏览完全够用，
超限返回 429。来源取 X-Forwarded-For 的第一个地址（可伪造，所以全站上限才是兜底）。
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque


class RateGate:
    def __init__(self, per_client: int, client_window: float, total: int, total_window: float) -> None:
        self.per_client, self.client_window = per_client, client_window
        self.total, self.total_window = total, total_window
        self._lock = threading.Lock()
        self._by_client: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()

    def take(self, client: str) -> str | None:
        """记一次调用；超限时不记，返回原因。"""
        now = time.monotonic()
        with self._lock:
            while self._all and now - self._all[0] > self.total_window:
                self._all.popleft()
            q = self._by_client.setdefault(client, deque())
            while q and now - q[0] > self.client_window:
                q.popleft()
            if len(q) >= self.per_client:
                return f"请求太频繁：同一来源 {self.client_window / 60:g} 分钟最多 {self.per_client} 次计算"
            if len(self._all) >= self.total:
                return f"全站计算请求太多：每 {self.total_window / 3600:g} 小时最多 {self.total} 次，请稍后再试"
            q.append(now)
            self._all.append(now)
            if len(self._by_client) > 5000:
                self._by_client = {k: v for k, v in self._by_client.items() if v and now - v[-1] <= self.client_window}
            return None


def client_id(headers, fallback: str | None) -> str:
    forwarded = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return (forwarded or fallback or "unknown")[:100]


compute_gate = RateGate(
    per_client=int(os.getenv("AIC_POST_LIMIT_PER_CLIENT", "60")), client_window=600,
    total=int(os.getenv("AIC_POST_LIMIT_PER_HOUR", "600")), total_window=3600,
)
