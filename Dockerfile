# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM ghcr.io/astral-sh/uv:0.11.28 AS uv-bin


FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="智策 AI 投委会" \
      org.opencontainers.image.source="https://github.com/flukier1016/ai-investment-committee"

ENV PATH="/app/backend/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0

COPY --from=uv-bin /uv /uvx /bin/

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin app

WORKDIR /app/backend

# 依赖层只随契约/锁文件变化；随后保留 editable 源码路径，确保 Path.parents
# 仍从 /app/backend/app 回到 /app 读取 data 与 frontend/dist。
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/app ./app
RUN uv sync --locked --no-dev

COPY data/demo /app/data/demo
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist

ARG APP_REVISION=unknown
LABEL org.opencontainers.image.revision="${APP_REVISION}"
ENV APP_REVISION="${APP_REVISION}"

RUN mkdir -p /app/data/runs \
    && chown 10001:10001 /app/data/runs \
    && chmod 0770 /app/data/runs

EXPOSE 8000
# 不在镜像里声明 VOLUME（Railway 构建器不支持）：持久化由 compose 的命名卷或平台卷挂到 /app/data/runs
USER 10001:10001

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import json,os,pathlib,urllib.request; root=pathlib.Path('/app'); assert (root/'data/demo/manifest.json').is_file(); assert os.access(root/'data/runs', os.W_OK); payload=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)); assert payload.get('status') == 'ok' and payload.get('mode') == 'demo'"]

STOPSIGNAL SIGTERM
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
