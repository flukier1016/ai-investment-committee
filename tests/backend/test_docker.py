"""Docker 一键复现防线。

日常 pytest 静态锁定多阶段构建、仓库路径、非 root、命名卷与 SPA 回退；
仅显式 RUN_DOCKER_SMOKE=1 时真实 build/up，验证健康、写权和卷持久化。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain import versioning
from app.main import SPAStaticFiles


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"
COMPOSE = ROOT / "compose.yaml"
DOCKERIGNORE = ROOT / ".dockerignore"


def _logical_lines(path: Path) -> list[str]:
    """合并 Dockerfile 续行，避免只靠注释/原始子串产生假阳性。"""
    logical: list[str] = []
    pending = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pending = f"{pending} {stripped}".strip()
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        logical.append(re.sub(r"\s+", " ", pending))
        pending = ""
    assert not pending, "Dockerfile 末尾存在未闭合续行"
    return logical


def test_dockerfile_multistage_paths_non_root_and_health_contract():
    lines = _logical_lines(DOCKERFILE)
    from_lines = [line for line in lines if line.upper().startswith("FROM ")]

    assert len(from_lines) == 3
    assert re.search(r"^FROM node:22-[^ ]+ AS ", from_lines[0], re.IGNORECASE)
    assert "latest" not in from_lines[0].lower()
    assert re.search(r"^FROM ghcr\.io/astral-sh/uv:0\.\d+\.\d+ AS ",
                     from_lines[1], re.IGNORECASE)
    assert re.search(r"^FROM python:3\.12-slim-[^ ]+ AS ",
                     from_lines[2], re.IGNORECASE)

    node_stage = re.search(r"\sAS\s+(\S+)$", from_lines[0], re.IGNORECASE).group(1)
    uv_stage = re.search(r"\sAS\s+(\S+)$", from_lines[1], re.IGNORECASE).group(1)
    assert "COPY frontend/package.json frontend/package-lock.json ./" in lines
    assert "COPY frontend/ ./" in lines
    assert next(i for i, line in enumerate(lines) if line == "RUN npm ci") \
        < next(i for i, line in enumerate(lines) if line == "RUN npm run build")

    runtime_start = lines.index(from_lines[-1])
    runtime = lines[runtime_start:]
    runtime_text = "\n".join(runtime)
    assert f"COPY --from={uv_stage} /uv /uvx /bin/" in runtime
    assert f"COPY --from={node_stage} /build/frontend/dist /app/frontend/dist" in runtime
    assert [line for line in runtime if line.startswith("WORKDIR ")][-1] \
        == "WORKDIR /app/backend"
    assert "COPY backend/pyproject.toml backend/uv.lock ./" in runtime
    assert "COPY backend/app ./app" in runtime
    assert "COPY data/demo /app/data/demo" in runtime
    assert "/app/data/runs" in runtime_text
    assert re.search(r"chown 10001:10001 /app/data/runs", runtime_text)
    assert re.search(r"chmod 0770 /app/data/runs", runtime_text)

    sync_lines = [line for line in runtime if line.startswith("RUN uv sync ")]
    assert len(sync_lines) == 2
    assert all("--locked" in line and "--no-dev" in line for line in sync_lines)
    assert "--no-install-project" in sync_lines[0]
    assert "--no-install-project" not in sync_lines[1]
    assert "--no-editable" not in sync_lines[1]
    revision_arg = runtime.index("ARG APP_REVISION=unknown")
    assert revision_arg > runtime.index(sync_lines[-1])
    assert 'LABEL org.opencontainers.image.revision="${APP_REVISION}"' \
        in runtime[revision_arg:]
    assert 'ENV APP_REVISION="${APP_REVISION}"' in runtime[revision_arg:]

    users = [line.split(maxsplit=1)[1] for line in runtime if line.startswith("USER ")]
    assert users and users[-1] == "10001:10001"
    assert "EXPOSE 8000" in runtime
    assert 'VOLUME ["/app/data/runs"]' in runtime
    health = next(line for line in runtime if line.startswith("HEALTHCHECK "))
    assert "/api/health" in health
    assert "root/'data/runs'" in health
    assert "data/demo/manifest.json" in health
    assert "os.access" in health and "os.W_OK" in health

    command = next(line for line in runtime if line.startswith("CMD "))
    argv = json.loads(command.removeprefix("CMD "))
    assert argv == [
        "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000",
    ]
    assert runtime.index(next(line for line in runtime if line.startswith("USER "))) \
        < runtime.index(command)


def test_compose_has_one_hardened_service_and_only_runs_named_volume():
    model = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))

    assert "version" not in model
    assert len(model["services"]) == 1
    _, service = next(iter(model["services"].items()))
    assert service["build"]["context"] == "."
    assert service["build"]["dockerfile"] == "Dockerfile"
    assert service["build"]["args"]["APP_REVISION"] == "${APP_REVISION:-unknown}"
    assert service["image"] == "${IMAGE_NAME:-ai-investment-committee:local}"
    assert service.get("user") not in {"root", "0", "0:0"}
    assert service["init"] is True
    assert service["read_only"] is True
    assert "ALL" in service["cap_drop"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert any("${PORT:-8000}:8000" in str(port) for port in service["ports"])

    mounts = service["volumes"]
    assert len(mounts) == 1
    mount = mounts[0]
    assert mount["type"] == "volume"
    assert mount["target"] == "/app/data/runs"
    assert mount["source"] in model["volumes"]
    assert mount["volume"]["nocopy"] is False
    assert all(item.get("target") != "/app/data" for item in mounts)
    assert any(str(item).startswith("/tmp:") for item in service["tmpfs"])


def test_dockerignore_excludes_local_state_but_keeps_locked_inputs():
    patterns = {
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert {
        ".git",
        "backend/.venv",
        "frontend/node_modules",
        "frontend/dist",
        "frontend/test-results",
        "frontend/playwright-report",
        "data/runs",
        "**/__pycache__",
        "**/.pytest_cache",
    }.issubset(patterns)
    assert not {"backend", "frontend", "data", "data/demo"}.intersection(patterns)
    assert not {
        "*", "**", "backend/*", "backend/**", "frontend/*", "frontend/**",
        "data/*", "data/**", "data/demo/*", "data/demo/**",
    }.intersection(patterns)
    assert "backend/uv.lock" not in patterns
    assert "frontend/package-lock.json" not in patterns


def test_spa_fallback_serves_routes_but_preserves_api_and_asset_errors(tmp_path):
    (tmp_path / "index.html").write_text("<main>spa-index</main>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    test_app = FastAPI()
    test_app.mount("/", SPAStaticFiles(directory=tmp_path, html=True), name="frontend")
    client = TestClient(test_app)

    assert client.get("/").text == "<main>spa-index</main>"
    assert client.get("/trace").text == "<main>spa-index</main>"
    assert client.head("/overview").status_code == 200
    assert client.get("/assets/app.js").text == "console.log('ok')"
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/api/unknown").status_code == 404
    assert client.post("/trace").status_code == 405


def test_container_revision_env_preserves_git_lineage(monkeypatch):
    revision = "ABCDEF0123456789abcdef0123456789abcdef01"
    versioning.code_version.cache_clear()
    try:
        monkeypatch.setenv("APP_REVISION", revision)
        assert versioning.code_version() == "git:abcdef0"
    finally:
        versioning.code_version.cache_clear()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(url: str, *, payload: dict | None = None) -> tuple[int, bytes]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@pytest.mark.skipif(
    os.getenv("RUN_DOCKER_SMOKE") != "1",
    reason="显式设置 RUN_DOCKER_SMOKE=1 才执行昂贵的真实容器烟测",
)
def test_compose_build_run_non_root_health_and_volume_persistence():
    if shutil.which("docker") is None:
        pytest.fail("RUN_DOCKER_SMOKE=1 但未安装 docker CLI")
    for probe in (["docker", "compose", "version"], ["docker", "info"]):
        checked = subprocess.run(
            probe, cwd=ROOT, capture_output=True, text=True, timeout=30)
        if checked.returncode != 0:
            pytest.fail(f"Docker/Compose 不可用：{' '.join(probe)}\n{checked.stderr}")

    project = f"aic-smoke-{uuid.uuid4().hex[:10]}"
    port = _free_port()
    env = {
        **os.environ,
        "COMPOSE_PROJECT_NAME": project,
        "PORT": str(port),
        "IMAGE_NAME": f"ai-investment-committee:{project}",
    }
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", env.get("APP_REVISION", "")):
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        env["APP_REVISION"] = revision
    service = next(iter(yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]))
    base_url = f"http://127.0.0.1:{port}"

    def compose(*args: str, check: bool = True, timeout: int = 900):
        return subprocess.run(
            ["docker", "compose", *args], cwd=ROOT, env=env,
            capture_output=True, text=True, check=check, timeout=timeout,
        )

    def wait_healthy(timeout: int = 180) -> dict:
        deadline = time.monotonic() + timeout
        last = "尚未请求"
        while time.monotonic() < deadline:
            try:
                status, body = _request(f"{base_url}/api/health")
                last = f"status={status}, body={body[:200]!r}"
                if status == 200:
                    payload = json.loads(body)
                    if payload.get("status") == "ok" and payload.get("mode") == "demo":
                        return payload
            except (OSError, ValueError) as exc:
                last = repr(exc)
            time.sleep(2)
        raise AssertionError(f"容器在 {timeout}s 内未健康：{last}")

    def wait_docker_health(timeout: int = 180) -> None:
        container_id = compose("ps", "-q", service, timeout=60).stdout.strip()
        assert container_id, "Compose 未返回服务容器 ID"
        deadline = time.monotonic() + timeout
        last = "unknown"
        while time.monotonic() < deadline:
            inspected = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_id],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
            )
            last = inspected.stdout.strip() or inspected.stderr.strip()
            if inspected.returncode == 0 and last == "healthy":
                return
            if last == "unhealthy":
                break
            time.sleep(2)
        raise AssertionError(f"Docker HEALTHCHECK 未进入 healthy：{last}")

    try:
        compose("config", "--quiet", timeout=60)
        compose("up", "--build", "-d")
        wait_healthy()
        wait_docker_health()

        uid = compose("exec", "-T", service, "id", "-u", timeout=60).stdout.strip()
        assert uid == "10001"
        compose("exec", "-T", service, "test", "-w", "/app/data/runs", timeout=60)

        root_status, root_body = _request(f"{base_url}/")
        route_status, route_body = _request(f"{base_url}/trace")
        assert root_status == route_status == 200
        assert b'id="root"' in root_body and route_body == root_body
        assert _request(f"{base_url}/assets/missing.js")[0] == 404
        assert _request(f"{base_url}/api/unknown")[0] == 404

        status, body = _request(f"{base_url}/api/decisions/run", payload={
            "scenario_id": "recovery_2026",
            "asof": "2026-07-09",
        })
        assert status == 200
        first = json.loads(body)
        decision_id = first["decision_id"]
        expected_weights = first["target_weights"]
        assert first["code_version"] == f"git:{env['APP_REVISION'][:7].lower()}"
        compose(
            "exec", "-T", service, "test", "-f",
            f"/app/data/runs/{decision_id}.json", timeout=60,
        )

        compose("down", timeout=120)
        compose("up", "-d", timeout=120)
        wait_healthy()
        wait_docker_health()
        encoded_id = urllib.parse.quote(decision_id, safe="")
        status, body = _request(f"{base_url}/api/decisions/{encoded_id}/record")
        persisted = json.loads(body)
        assert status == 200
        assert persisted["decision_id"] == decision_id
        assert persisted["target_weights"] == expected_weights
    except Exception as exc:
        logs = compose("logs", "--no-color", check=False, timeout=60)
        command_output = ""
        if isinstance(exc, subprocess.CalledProcessError):
            command_output = (
                f"\n--- failed command stdout ---\n{exc.stdout or ''}"
                f"\n--- failed command stderr ---\n{exc.stderr or ''}"
            )
        raise AssertionError(
            f"Docker 烟测失败：{exc}{command_output}"
            f"\n--- compose stdout ---\n{logs.stdout}"
            f"\n--- compose stderr ---\n{logs.stderr}"
        ) from exc
    finally:
        try:
            compose(
                "down", "-v", "--rmi", "all", "--remove-orphans",
                check=False, timeout=180,
            )
        except subprocess.TimeoutExpired:
            pass  # best effort：保留原始失败作为主诊断
