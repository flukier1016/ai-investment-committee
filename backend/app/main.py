"""AI 资产配置投委会 · FastAPI 入口。

开发：uvicorn app.main:app --reload --port 8000（前端 Vite 代理 /api）
生产/一体：构建 frontend/dist 后由本服务同端口托管静态文件。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from .api.routes import router


class SPAStaticFiles(StaticFiles):
    """为 BrowserRouter 提供受限 index fallback，不吞掉 API/静态资源 404。"""

    @staticmethod
    def _can_fallback(path: str, scope: Scope) -> bool:
        normalized = path.lstrip("/")
        return (
            scope.get("method") in {"GET", "HEAD"}
            and normalized != "api"
            and not normalized.startswith("api/")
            and not Path(normalized).suffix
        )

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or not self._can_fallback(path, scope):
                raise
        else:
            if response.status_code != 404 or not self._can_fallback(path, scope):
                return response
        return await super().get_response("index.html", scope)


app = FastAPI(title="AI 资产配置投委会", version="1.0.0",
              description="五方法三层：Risk Parity 战略底仓 + 三种战术信号 + Black-Litterman Model 整合")
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(router)

_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/", SPAStaticFiles(directory=_dist, html=True), name="frontend")
