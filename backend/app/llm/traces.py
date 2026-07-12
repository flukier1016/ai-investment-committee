"""内容寻址、可重放且私有原子落盘的 LLM trace。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows 退化为进程内锁
    fcntl = None

from pydantic import BaseModel, ValidationError

from ..schemas.llm import LLMTrace, QuadrantCall, ViewExplanation
from .config import LLMRuntimeConfig


ROOT = Path(__file__).resolve().parents[3]
TRACE_DIR = ROOT / "data" / "runs" / "llm_traces"
TRACE_SCHEMA_VERSION = 1
CLIENT_CONTRACT_VERSION = "openai-compatible-json-v1"

_NEW_TRACE_ID = re.compile(r"^trace_[0-9a-f]{64}$")
_READABLE_TRACE_ID = re.compile(r"^trace_(?:[0-9a-f]{12}|[0-9a-f]{64})$")
_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_RESPONSE_SCHEMAS: dict[str, type[BaseModel]] = {
    QuadrantCall.__name__: QuadrantCall,
    ViewExplanation.__name__: ViewExplanation,
}


class TraceStoreError(RuntimeError):
    pass


class TraceCollisionError(TraceStoreError):
    pass


class TraceCorruptError(TraceStoreError):
    pass


@dataclass(frozen=True, slots=True)
class TraceIdentity:
    trace_id: str
    call_fingerprint: str
    call_key: str
    provider: str
    provider_spec_version: str
    endpoint: str
    model: str
    temperature: float
    max_retries: int
    timeout_seconds: float
    prompt_sha256: str
    response_schema: str
    response_schema_sha256: str
    allowed_citations_sha256: str


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: object) -> str:
    encoded = value if isinstance(value, str) else _canonical_json(value)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _identity_payload(
    *,
    call_key: str,
    provider: str,
    provider_spec_version: str,
    endpoint: str,
    model: str,
    temperature: float,
    max_retries: int,
    timeout_seconds: float,
    prompt_sha256: str,
    response_schema_sha256: str,
    allowed_citations_sha256: str,
) -> dict[str, object]:
    return {
        "trace_schema_version": TRACE_SCHEMA_VERSION,
        "client_contract_version": CLIENT_CONTRACT_VERSION,
        "call_key": call_key,
        "provider": provider,
        "provider_spec_version": provider_spec_version,
        "endpoint": endpoint,
        "model": model,
        "temperature": temperature,
        "max_retries": max_retries,
        "timeout_seconds": timeout_seconds,
        "prompt_sha256": prompt_sha256,
        "response_schema_sha256": response_schema_sha256,
        "allowed_citations_sha256": allowed_citations_sha256,
    }


def trace_identity_from_parts(
    *,
    call_key: str,
    provider: str,
    provider_spec_version: str,
    endpoint: str,
    model: str,
    temperature: float,
    max_retries: int,
    timeout_seconds: float,
    prompt: str,
    response_schema: type[BaseModel],
    allowed_citations: Iterable[str] = (),
) -> TraceIdentity:
    schema_payload = response_schema.model_json_schema()
    prompt_sha = _sha256(prompt)
    schema_sha = _sha256(schema_payload)
    citations_sha = _sha256(sorted(set(allowed_citations)))
    payload = _identity_payload(
        call_key=call_key,
        provider=provider,
        provider_spec_version=provider_spec_version,
        endpoint=endpoint,
        model=model,
        temperature=temperature,
        max_retries=max_retries,
        timeout_seconds=timeout_seconds,
        prompt_sha256=prompt_sha,
        response_schema_sha256=schema_sha,
        allowed_citations_sha256=citations_sha,
    )
    fingerprint = _sha256(payload)
    return TraceIdentity(
        trace_id=f"trace_{fingerprint}",
        call_fingerprint=fingerprint,
        call_key=call_key,
        provider=provider,
        provider_spec_version=provider_spec_version,
        endpoint=endpoint,
        model=model,
        temperature=temperature,
        max_retries=max_retries,
        timeout_seconds=timeout_seconds,
        prompt_sha256=prompt_sha,
        response_schema=response_schema.__name__,
        response_schema_sha256=schema_sha,
        allowed_citations_sha256=citations_sha,
    )


def build_trace_identity(
    runtime_config: LLMRuntimeConfig,
    *,
    call_key: str,
    prompt: str,
    response_schema: type[BaseModel],
    allowed_citations: Iterable[str] = (),
) -> TraceIdentity:
    payload = runtime_config.identity_payload()
    if payload is None:
        raise ValueError("LLM 关闭时不能构造可持久化调用身份")
    return trace_identity_from_parts(
        call_key=call_key,
        provider=str(payload["provider"]),
        provider_spec_version=str(payload["provider_spec_version"]),
        endpoint=str(payload["endpoint"]),
        model=str(payload["model"]),
        temperature=float(payload["temperature"]),
        max_retries=int(payload["max_retries"]),
        timeout_seconds=float(payload["timeout_seconds"]),
        prompt=prompt,
        response_schema=response_schema,
        allowed_citations=allowed_citations,
    )


_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+")
_KEY_ASSIGNMENT_RE = re.compile(
    r"(?i)((?:api[_-]?key|authorization)\s*[:=]\s*)[^\s,;]+"
)
_OPENAI_STYLE_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


def redact_text(value: str, secrets: Iterable[str] = ()) -> str:
    redacted = value
    for secret in sorted({s for s in secrets if len(s) >= 4}, key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED]")
    redacted = _BEARER_RE.sub(r"\1[REDACTED]", redacted)
    redacted = _KEY_ASSIGNMENT_RE.sub(r"\1[REDACTED]", redacted)
    return _OPENAI_STYLE_KEY_RE.sub("[REDACTED]", redacted)


def _redact_value(value: Any, secrets: Iterable[str]) -> Any:
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, Mapping):
        return {
            redact_text(str(k), secrets): _redact_value(v, secrets)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_value(v, secrets) for v in value]
    if isinstance(value, (set, frozenset)):
        redacted = [_redact_value(v, secrets) for v in value]
        return sorted(redacted, key=_canonical_json)
    return deepcopy(value)


def make_trace(
    identity: TraceIdentity,
    *,
    prompt: str,
    structured_output: BaseModel | Mapping[str, Any] | None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: float = 0.0,
    response_id: str = "",
    response_model: str = "",
    degraded: bool = False,
    degraded_reason: str = "",
    error_type: str = "",
    created_at: str | None = None,
    secrets: Iterable[str] = (),
) -> LLMTrace:
    if _sha256(prompt) != identity.prompt_sha256:
        raise TraceCollisionError("trace prompt 与调用身份不一致")
    secret_values = tuple(sorted(
        {secret for secret in secrets if len(secret) >= 4},
        key=len,
        reverse=True,
    ))
    if isinstance(structured_output, BaseModel):
        output: dict[str, Any] | None = structured_output.model_dump(mode="json")
    elif structured_output is None:
        output = None
    else:
        output = dict(structured_output)
    if output is not None:
        schema = _RESPONSE_SCHEMAS.get(identity.response_schema)
        if schema is None:
            raise TraceCollisionError(
                f"不支持的 trace response_schema：{identity.response_schema}"
            )
        try:
            output = schema.model_validate(output).model_dump(mode="json")
        except ValidationError as exc:
            raise TraceCollisionError("trace structured_output 不符合响应 schema") from exc
    safe_output = (
        _redact_value(output, secret_values) if output is not None else None
    )
    safe_reason = redact_text(degraded_reason, secret_values)[:240]
    trace = LLMTrace(
        trace_id=identity.trace_id,
        schema_version=TRACE_SCHEMA_VERSION,
        call_key=identity.call_key,
        call_fingerprint=identity.call_fingerprint,
        provider=identity.provider,
        provider_spec_version=identity.provider_spec_version,
        endpoint=identity.endpoint,
        model=identity.model,
        temperature=identity.temperature,
        max_retries=identity.max_retries,
        timeout_seconds=identity.timeout_seconds,
        prompt_sha256=identity.prompt_sha256,
        prompt=redact_text(prompt, secret_values),
        response_schema=identity.response_schema,
        response_schema_sha256=identity.response_schema_sha256,
        allowed_citations_sha256=identity.allowed_citations_sha256,
        structured_output=safe_output,
        output_sha256=_sha256(safe_output) if safe_output is not None else "",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=round(float(latency_ms), 1),
        response_id=redact_text(response_id, secret_values),
        response_model=redact_text(response_model, secret_values),
        degraded=degraded,
        degraded_reason=safe_reason,
        error_type=redact_text(error_type, secret_values),
        created_at=created_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    serialized = trace.model_dump_json()
    if any(secret in serialized for secret in secret_values):
        raise TraceStoreError("LLM trace 脱敏校验失败")
    return trace


def _ensure_trace_dir() -> None:
    if TRACE_DIR.exists() and not TRACE_DIR.is_dir():
        raise TraceStoreError(f"trace 路径不是目录：{TRACE_DIR}")
    try:
        TRACE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        TRACE_DIR.chmod(0o700)
    except OSError as exc:
        raise TraceStoreError(f"无法准备私有 trace 目录：{TRACE_DIR}") from exc


def _trace_path(trace_id: str, *, for_write: bool = False) -> Path:
    pattern = _NEW_TRACE_ID if for_write else _READABLE_TRACE_ID
    if not pattern.fullmatch(trace_id):
        raise ValueError(f"trace_id 格式非法：{trace_id!r}")
    return TRACE_DIR / f"{trace_id}.json"


def _identity_from_trace(trace: LLMTrace) -> TraceIdentity:
    return TraceIdentity(
        trace_id=trace.trace_id,
        call_fingerprint=trace.call_fingerprint,
        call_key=trace.call_key,
        provider=trace.provider,
        provider_spec_version=trace.provider_spec_version,
        endpoint=trace.endpoint,
        model=trace.model,
        temperature=trace.temperature,
        max_retries=trace.max_retries,
        timeout_seconds=trace.timeout_seconds,
        prompt_sha256=trace.prompt_sha256,
        response_schema=trace.response_schema,
        response_schema_sha256=trace.response_schema_sha256,
        allowed_citations_sha256=trace.allowed_citations_sha256,
    )


def _validate_trace_content(
    trace: LLMTrace,
    *,
    path: Path | None = None,
    expected_identity: TraceIdentity | None = None,
    error_type: type[TraceStoreError] = TraceCorruptError,
) -> LLMTrace:
    def reject(reason: str) -> None:
        name = path.name if path is not None else trace.trace_id
        raise error_type(f"LLM trace 校验失败（{reason}）：{name}")

    if path is not None and path.stem != trace.trace_id:
        reject("文件名与 trace_id 不一致")

    # schema_version=0 只为读取历史记录保留；不得参与内容寻址缓存或新写入。
    if trace.schema_version == 0:
        if expected_identity is not None:
            reject("旧版 trace 不可重放")
        if not _READABLE_TRACE_ID.fullmatch(trace.trace_id):
            reject("旧版 trace_id 非法")
        return trace.model_copy(update={"persisted": path is not None})
    if trace.schema_version != TRACE_SCHEMA_VERSION:
        reject("未知 schema_version")
    if not _NEW_TRACE_ID.fullmatch(trace.trace_id):
        reject("trace_id 非法")

    sha_fields = (
        trace.call_fingerprint,
        trace.prompt_sha256,
        trace.response_schema_sha256,
        trace.allowed_citations_sha256,
    )
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in sha_fields):
        reject("摘要字段非法")

    schema = _RESPONSE_SCHEMAS.get(trace.response_schema)
    if schema is None:
        reject("响应 schema 不受支持")
    if _sha256(schema.model_json_schema()) != trace.response_schema_sha256:
        reject("响应 schema 摘要不一致")

    fingerprint = _sha256(_identity_payload(
        call_key=trace.call_key,
        provider=trace.provider,
        provider_spec_version=trace.provider_spec_version,
        endpoint=trace.endpoint,
        model=trace.model,
        temperature=trace.temperature,
        max_retries=trace.max_retries,
        timeout_seconds=trace.timeout_seconds,
        prompt_sha256=trace.prompt_sha256,
        response_schema_sha256=trace.response_schema_sha256,
        allowed_citations_sha256=trace.allowed_citations_sha256,
    ))
    if trace.call_fingerprint != fingerprint:
        reject("调用指纹不一致")
    if trace.trace_id != f"trace_{fingerprint}":
        reject("trace_id 与调用指纹不一致")

    if trace.structured_output is None:
        reject("缺少结构化输出")
    if trace.output_sha256 != _sha256(trace.structured_output):
        reject("输出摘要不一致")
    try:
        normalized_output = schema.model_validate(
            trace.structured_output
        ).model_dump(mode="json")
    except ValidationError:
        reject("结构化输出不符合响应 schema")
    if normalized_output != trace.structured_output:
        reject("结构化输出不是规范形状")

    if expected_identity is not None:
        actual = _identity_from_trace(trace)
        if actual != expected_identity:
            reject("与预期调用身份不一致")

    return trace.model_copy(update={"persisted": path is not None or trace.persisted})


def _load_path(
    path: Path,
    *,
    expected_identity: TraceIdentity | None = None,
) -> LLMTrace:
    try:
        trace = LLMTrace.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise TraceCorruptError(f"LLM trace 损坏：{path.name}") from exc
    return _validate_trace_content(
        trace,
        path=path,
        expected_identity=expected_identity,
        error_type=TraceCorruptError,
    )


def load_trace(trace_id: str) -> LLMTrace | None:
    _ensure_trace_dir()
    path = _trace_path(trace_id)
    if not path.exists():
        return None
    return _load_path(path)


def _thread_lock(trace_id: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(trace_id, threading.RLock())


@contextmanager
def _locked_trace(trace_id: str):
    _ensure_trace_dir()
    with _thread_lock(trace_id):
        lock_path = TRACE_DIR / f".{trace_id}.lock"
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            os.chmod(lock_path, 0o600)
        except OSError as exc:
            if "fd" in locals():
                os.close(fd)
            raise TraceStoreError("无法取得 LLM trace 写锁") from exc
        with os.fdopen(fd, "a+b") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _serialized(trace: LLMTrace) -> str:
    return json.dumps(
        trace.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"


def _atomic_write(path: Path, trace: LLMTrace) -> None:
    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_serialized(trace))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        raise TraceStoreError("LLM trace 原子写失败") from exc
    finally:
        tmp.unlink(missing_ok=True)


_OBSERVATIONAL_FIELDS = {
    "tokens_in",
    "tokens_out",
    "latency_ms",
    "response_id",
    "created_at",
}


def _logical_payload(trace: LLMTrace) -> dict[str, Any]:
    return {
        key: value
        for key, value in trace.model_dump(mode="json").items()
        if key not in _OBSERVATIONAL_FIELDS
    }


def _write_or_compare(
    path: Path,
    trace: LLMTrace,
    identity: TraceIdentity,
) -> LLMTrace:
    if path.exists():
        existing = _load_path(path, expected_identity=identity)
        if _logical_payload(existing) == _logical_payload(trace):
            return existing
        raise TraceCollisionError(
            f"同一 trace_id 出现不同结构化结果：{trace.trace_id}"
        )
    _atomic_write(path, trace)
    return trace


def _validate_new_trace(
    trace: LLMTrace,
    *,
    expected_identity: TraceIdentity | None = None,
) -> LLMTrace:
    if trace.schema_version != TRACE_SCHEMA_VERSION:
        raise TraceCollisionError("新 trace 必须使用当前 schema_version")
    return _validate_trace_content(
        trace,
        expected_identity=expected_identity,
        error_type=TraceCollisionError,
    )


def persist_trace(trace: LLMTrace) -> LLMTrace:
    validated = _validate_new_trace(trace)
    identity = _identity_from_trace(validated)
    persisted = validated.model_copy(update={"persisted": True})
    path = _trace_path(persisted.trace_id, for_write=True)
    with _locked_trace(persisted.trace_id):
        return _write_or_compare(path, persisted, identity)


def replay_or_record(
    identity: TraceIdentity,
    producer: Callable[[], LLMTrace],
) -> tuple[LLMTrace, bool]:
    """同逻辑调用 first-write-wins；命中缓存时绝不再次执行 producer。"""
    path = _trace_path(identity.trace_id, for_write=True)
    with _locked_trace(identity.trace_id):
        if path.exists():
            return _load_path(path, expected_identity=identity), True
        trace = producer()
        validated = _validate_new_trace(trace, expected_identity=identity)
        persisted = validated.model_copy(update={"persisted": True})
        return _write_or_compare(path, persisted, identity), False


__all__ = [
    "TRACE_DIR",
    "TraceCollisionError",
    "TraceCorruptError",
    "TraceIdentity",
    "TraceStoreError",
    "build_trace_identity",
    "load_trace",
    "make_trace",
    "persist_trace",
    "redact_text",
    "replay_or_record",
    "trace_identity_from_parts",
]
