"""AI 资产配置投委会 · FastAPI 入口。

开发：uvicorn app.main:app --reload --port 8000（前端 Vite 代理 /api）
生产/一体：构建 frontend/dist 后由本服务同端口托管静态文件。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router

app = FastAPI(title="AI 资产配置投委会", version="1.0.0",
              description="五方法三层：Risk Parity 战略底仓 + 三种战术信号 + Black-Litterman Model 整合")
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(router)

_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
