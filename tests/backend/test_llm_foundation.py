"""LLM 客户端瘦身基建一文件防线。

锁定三 provider 注册表、默认零依赖、可信配置指纹、SDK 原生重试、严格 JSON
解析，以及内容寻址 trace 的脱敏、私有原子写、碰撞和并发重放语义。全程零网络。
"""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import threading
import tomllib
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.domain import pipeline as pipeline_module
from app.domain.pipeline import run_decision, run_decision_cached
from app.llm import client as client_module
from app.llm import traces as trace_store
from app.llm.client import (
    LLMClientError,
    LLMProviderConfigurationError,
    LLMResponseError,
    OpenAICompatibleClient,
    build_client,
)
from app.llm.config import (
    LLMRuntimeConfig,
    effective_config_digest,
    effective_config_payload,
)
from app.llm.providers import LLMProvider, get_provider_spec, provider_specs
from app.llm.traces import (
    TraceCollisionError,
    TraceCorruptError,
    TraceStoreError,
    build_trace_identity,
    load_trace,
    make_trace,
    persist_trace,
    replay_or_record,
    trace_identity_from_parts,
)
from app.main import app
from app.schemas.config import AllocationConfig
from app.schemas.llm import LLMTrace, QuadrantCall, RegimeCall, ViewExplanation
from app.services.llm_views import (
    quadrant_call_from_runtime,
    quadrant_call_or_abstain,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_SHA = "e9e97d36c0da0819c753ca3e830a74ba3ddba6688e5bfa203ca7439b8fdb3de1"


def _runtime(
    provider: LLMProvider = LLMProvider.OPENAI_COMPATIBLE,
    *,
    model: str = "pinned-test-model-2026-07-12",
    temperature: float = 0.0,
    max_retries: int = 2,
    timeout_seconds: float = 17,
) -> LLMRuntimeConfig:
    return LLMRuntimeConfig(
        provider=provider,
        model=model,
        temperature=temperature,
        max_retries=max_retries,
        timeout_seconds=timeout_seconds,
    )


def _identity(prompt: str = "仅输出 JSON", **runtime_kwargs):
    return build_trace_identity(
        _runtime(**runtime_kwargs),
        call_key="quadrant_call",
        prompt=prompt,
        response_schema=QuadrantCall,
        allowed_citations={"news_001", "news_002"},
    )


class _FakeCompletions:
    def __init__(self, response=None, exc: Exception | None = None):
        self.response = response
        self.exc = exc
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.response


def _sdk(response=None, exc: Exception | None = None):
    completions = _FakeCompletions(response=response, exc=exc)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
        completions_for_test=completions,
    )


def _response(
    content: str,
    *,
    finish_reason: str = "stop",
    choices: int = 1,
):
    rows = [
        SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(content=content),
        )
        for _ in range(choices)
    ]
    return SimpleNamespace(
        choices=rows,
        usage=SimpleNamespace(prompt_tokens=13, completion_tokens=7),
        id="chatcmpl_fixture",
        model="resolved-model-snapshot",
    )


def test_registry_is_frozen_and_contains_exactly_three_provider_types():
    specs = provider_specs()

    assert set(specs) == set(LLMProvider)
    assert len(specs) == 3
    assert {provider.value for provider in specs} == {
        "openai_compatible", "deepseek", "ollama"}
    with pytest.raises(TypeError):
        specs[LLMProvider.OPENAI_COMPATIBLE] = specs[LLMProvider.OLLAMA]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        specs[LLMProvider.OLLAMA].base_url = "http://attacker.invalid"  # type: ignore[misc]
    with pytest.raises(ValueError, match="不支持"):
        get_provider_spec("custom-provider")


def test_provider_specs_fix_endpoint_and_key_policy_without_secret_values():
    openai = get_provider_spec(LLMProvider.OPENAI_COMPATIBLE)
    deepseek = get_provider_spec(LLMProvider.DEEPSEEK)
    ollama = get_provider_spec(LLMProvider.OLLAMA)

    assert (openai.base_url, openai.api_key_env) == (
        "https://api.openai.com/v1", "OPENAI_API_KEY")
    assert (deepseek.base_url, deepseek.api_key_env) == (
        "https://api.deepseek.com", "DEEPSEEK_API_KEY")
    assert ollama.base_url == "http://127.0.0.1:11434/v1/"
    assert not ollama.requires_api_key and ollama.placeholder_api_key == "ollama"
    assert "sk-" not in repr(provider_specs())


def test_runtime_config_is_server_only_atomic_and_rejects_arbitrary_endpoint():
    assert LLMRuntimeConfig().identity_payload() is None
    assert not any(name.startswith("llm_") for name in AllocationConfig.model_fields)

    with pytest.raises(ValidationError, match="必须显式指定 model"):
        LLMRuntimeConfig(provider=LLMProvider.DEEPSEEK)
    with pytest.raises(ValidationError, match="关闭时"):
        LLMRuntimeConfig(model="hidden-model")
    with pytest.raises(ValidationError, match="关闭时"):
        LLMRuntimeConfig(temperature=0.1)
    with pytest.raises(ValidationError, match="base_url"):
        LLMRuntimeConfig.model_validate({"provider": "ollama", "model": "qwen",
                                         "base_url": "http://attacker.invalid"})


def test_effective_config_fingerprint_preserves_default_and_tracks_llm_identity():
    allocation = AllocationConfig().fingerprint_payload()
    disabled_payload = effective_config_payload(allocation, LLMRuntimeConfig())

    assert disabled_payload == allocation
    assert effective_config_digest(allocation, LLMRuntimeConfig()) == DEFAULT_CONFIG_SHA

    base = _runtime()
    variants = [
        base,
        _runtime(provider=LLMProvider.DEEPSEEK),
        _runtime(model="another-pinned-model"),
        _runtime(temperature=0.25),
        _runtime(max_retries=5),
    ]
    digests = {effective_config_digest(allocation, runtime) for runtime in variants}
    assert len(digests) == len(variants)
    safe_payload = effective_config_payload(allocation, base)["llm"]
    assert {"provider", "model", "temperature"} <= set(safe_payload)
    assert "api_key" not in json.dumps(safe_payload).lower()


def test_default_decision_id_stays_stable_and_enabled_identity_is_deterministic():
    config = AllocationConfig()
    default = run_decision("ci", "2026-07-09", config)
    enabled_a = run_decision(
        "ci", "2026-07-09", config, llm_runtime=_runtime())
    enabled_b = run_decision(
        "ci", "2026-07-09", config, llm_runtime=_runtime())

    assert default.decision_id == "dec_20260709_ci_d4e4fee9e97d"
    assert "llm" not in default.config
    assert enabled_a.decision_id == enabled_b.decision_id != default.decision_id
    assert enabled_a.target_weights == enabled_b.target_weights == default.target_weights
    assert enabled_a.config["llm"]["provider"] == "openai_compatible"
    assert enabled_a.llm_traces == [], "第 8 项只建基础设施，不接真实决策链"


def test_decision_cache_isolates_every_enabled_llm_runtime_identity():
    pipeline_module._run_cached.cache_clear()
    config = AllocationConfig()
    base = _runtime()
    first = run_decision_cached(
        "ci", "2026-07-09", config, llm_runtime=base)
    replayed = run_decision_cached(
        "ci", "2026-07-09", config, llm_runtime=base)
    variants = [
        _runtime(provider=LLMProvider.DEEPSEEK),
        _runtime(model="another-pinned-model"),
        _runtime(temperature=0.25),
        _runtime(max_retries=5),
        _runtime(timeout_seconds=29),
    ]
    records = [first, *(run_decision_cached(
        "ci", "2026-07-09", config, llm_runtime=runtime)
        for runtime in variants)]

    assert replayed is first
    assert len({record.decision_id for record in records}) == len(records)
    assert all(record.target_weights == first.target_weights for record in records)
    assert all(record.llm_traces == [] for record in records)


def test_public_api_cannot_enable_llm_or_spend_server_credentials(monkeypatch):
    calls: list[dict] = []

    def forbidden_factory(**kwargs):
        calls.append(kwargs)
        raise AssertionError("公开 API 不得构造 LLM client")

    monkeypatch.setattr("app.services.llm_views.build_client", forbidden_factory)
    api = TestClient(app)
    base = api.post(
        "/api/decisions/run", json={"scenario_id": "recovery_2026"})
    injected = api.post("/api/decisions/run", json={
        "scenario_id": "recovery_2026",
        "llm": {"provider": "deepseek", "model": "paid-model"},
        "config": {
            "llm": {"provider": "deepseek", "model": "paid-model"},
        },
    })
    backtest = api.post("/api/backtest/run", json={
        "llm": {"provider": "openai_compatible", "model": "paid-model"},
    })

    assert base.status_code == injected.status_code == backtest.status_code == 200
    assert injected.json()["decision_id"] == base.json()["decision_id"]
    assert "llm" not in injected.json()["config"]
    assert calls == []


def test_default_path_imports_no_optional_sdk_and_dependency_is_extra(monkeypatch):
    pyproject = tomllib.loads(
        (ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    assert not any(dep.startswith("openai") for dep in pyproject["project"]["dependencies"])
    assert pyproject["project"]["optional-dependencies"]["llm"] == ["openai>=2.0,<3"]

    imported: list[str] = []

    def forbidden_import(name: str):
        imported.append(name)
        raise AssertionError("关闭路径不得导入 SDK")

    monkeypatch.setattr(client_module.importlib, "import_module", forbidden_import)
    assert build_client(LLMRuntimeConfig()) is None
    assert imported == []


@pytest.mark.parametrize(
    "provider,environ,expected_key,expected_url",
    [
        (LLMProvider.OPENAI_COMPATIBLE, {"OPENAI_API_KEY": "openai-secret"},
         "openai-secret", "https://api.openai.com/v1"),
        (LLMProvider.DEEPSEEK, {"DEEPSEEK_API_KEY": "deepseek-secret"},
         "deepseek-secret", "https://api.deepseek.com"),
        (LLMProvider.OLLAMA, {}, "ollama", "http://127.0.0.1:11434/v1/"),
    ],
)
def test_sdk_factory_receives_fixed_endpoint_timeout_and_native_max_retries(
    provider, environ, expected_key, expected_url
):
    captured: list[dict] = []

    def factory(**kwargs):
        captured.append(kwargs)
        return _sdk()

    client = build_client(
        _runtime(provider=provider, max_retries=7),
        environ=environ,
        sdk_factory=factory,
    )

    assert client is not None and len(captured) == 1
    assert captured[0] == {
        "api_key": expected_key,
        "base_url": expected_url,
        "timeout": 17.0,
        "max_retries": 7,
    }
    assert not hasattr(client, "api_key")


def test_missing_cloud_key_fails_typed_without_loading_or_calling_sdk():
    calls = []

    with pytest.raises(LLMProviderConfigurationError, match="OPENAI_API_KEY"):
        build_client(
            _runtime(),
            environ={},
            sdk_factory=lambda **kwargs: calls.append(kwargs),
        )
    assert calls == []


def test_factory_dependency_and_key_failures_reach_same_abstain_boundary(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(trace_store, "TRACE_DIR", tmp_path / "llm_traces")
    missing_key_call, missing_key_trace = quadrant_call_from_runtime(
        _runtime(), "缺密钥调用", {"news_001"}, environ={})
    assert missing_key_call.quadrant == RegimeCall.ABSTAIN
    assert missing_key_trace.error_type == "LLMProviderConfigurationError"
    assert missing_key_trace.degraded_reason == (
        "client_init_error:LLMProviderConfigurationError")
    assert missing_key_trace.persisted

    monkeypatch.setattr(
        client_module.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("secret raw error")),
    )
    missing_sdk_call, missing_sdk_trace = quadrant_call_from_runtime(
        _runtime(), "缺 SDK 调用", {"news_001"},
        environ={"OPENAI_API_KEY": "sk-never-persist-this"},
    )
    assert missing_sdk_call.quadrant == RegimeCall.ABSTAIN
    assert missing_sdk_trace.error_type == "LLMDependencyError"
    assert "sk-never" not in missing_sdk_trace.model_dump_json()
    assert missing_sdk_trace.persisted

    factory_call, factory_trace = quadrant_call_from_runtime(
        _runtime(), "工厂失败调用", {"news_001"},
        environ={"OPENAI_API_KEY": "sk-never-persist-this"},
        sdk_factory=lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("Bearer sk-factory-secret")),
    )
    assert factory_call.quadrant == RegimeCall.ABSTAIN
    assert factory_trace.error_type == "LLMClientError"
    assert "factory-secret" not in factory_trace.model_dump_json()
    assert factory_trace.persisted


def test_runtime_mock_call_persists_then_replays_without_factory_or_sdk(
    tmp_path, monkeypatch
):
    directory = tmp_path / "llm_traces"
    monkeypatch.setattr(trace_store, "TRACE_DIR", directory)
    raw = json.dumps({
        "quadrant": "recovery",
        "confidence_band": "medium",
        "citations": ["news_001"],
        "rationale": "仅由本地 mock 返回",
    }, ensure_ascii=False)
    sdk = _sdk(_response(raw))
    factory_calls: list[dict] = []

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return sdk

    first_call, first_trace = quadrant_call_from_runtime(
        _runtime(),
        "本地 mock；仅输出 JSON",
        {"news_001"},
        environ={"OPENAI_API_KEY": "sk-local-mock-only"},
        sdk_factory=factory,
    )
    replayed_call, replayed_trace = quadrant_call_from_runtime(
        _runtime(),
        "本地 mock；仅输出 JSON",
        {"news_001"},
        environ={},
        sdk_factory=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("缓存命中不得构造 SDK")),
    )

    assert first_call == replayed_call
    assert first_trace == replayed_trace
    assert first_trace.persisted
    assert (directory / f"{first_trace.trace_id}.json").is_file()
    assert len(factory_calls) == 1
    assert len(sdk.completions_for_test.calls) == 1


def test_runtime_replay_rejects_schema_valid_cache_with_bogus_citation(
    tmp_path, monkeypatch
):
    directory = tmp_path / "llm_traces"
    monkeypatch.setattr(trace_store, "TRACE_DIR", directory)
    runtime = _runtime()
    prompt = "引用白名单；仅输出 JSON"
    identity = build_trace_identity(
        runtime,
        call_key="quadrant_call",
        prompt=prompt,
        response_schema=QuadrantCall,
        allowed_citations={"news_001"},
    )
    poison = make_trace(
        identity,
        prompt=prompt,
        structured_output={
            "quadrant": "recovery",
            "confidence_band": "high",
            "citations": ["news_DOES_NOT_EXIST"],
            "rationale": "结构合法但语义越界",
        },
    )
    persist_trace(poison)
    factory_calls: list[dict] = []

    call, trace = quadrant_call_from_runtime(
        runtime,
        prompt,
        {"news_001"},
        environ={},
        sdk_factory=lambda **kwargs: factory_calls.append(kwargs),
    )

    assert call.quadrant == RegimeCall.ABSTAIN
    assert trace.trace_id == "" and not trace.persisted
    assert trace.error_type == "TraceCorruptError"
    assert trace.degraded_reason == "trace_store_error:TraceCorruptError"
    assert factory_calls == [], "缓存重放不得为校验失败补发真实请求"


def test_runtime_trace_store_failure_abstains_without_dangling_id_or_file(
    tmp_path, monkeypatch
):
    directory = tmp_path / "llm_traces"
    monkeypatch.setattr(trace_store, "TRACE_DIR", directory)
    raw = json.dumps({
        "quadrant": "recovery",
        "confidence_band": "low",
        "citations": [],
        "rationale": "本地 mock",
    }, ensure_ascii=False)

    def fail_replace(_src, _dst):
        raise OSError("fixture replace failure")

    monkeypatch.setattr(trace_store.os, "replace", fail_replace)
    call, trace = quadrant_call_from_runtime(
        _runtime(provider=LLMProvider.OLLAMA),
        "写失败；仅输出 JSON",
        set(),
        environ={},
        sdk_factory=lambda **_kwargs: _sdk(_response(raw)),
    )

    assert call.quadrant == RegimeCall.ABSTAIN
    assert trace.trace_id == "" and not trace.persisted
    assert trace.degraded_reason == "trace_store_error:TraceStoreError"
    assert not list(directory.glob("trace_*.json"))
    assert not list(directory.glob("*.tmp"))


def test_common_transport_preserves_prompt_and_returns_structured_metadata():
    raw = json.dumps({
        "quadrant": "recovery",
        "confidence_band": "medium",
        "citations": ["news_001"],
        "rationale": "定性判断",
    }, ensure_ascii=False)
    sdk = _sdk(_response(raw))
    client = OpenAICompatibleClient(
        sdk, _runtime(), get_provider_spec(LLMProvider.OPENAI_COMPATIBLE))

    completion = client.complete_structured("原样 prompt；仅输出 JSON", QuadrantCall)

    assert completion.parsed.quadrant == RegimeCall.RECOVERY
    assert completion.tokens_in == 13 and completion.tokens_out == 7
    assert completion.response_id == "chatcmpl_fixture"
    assert completion.response_model == "resolved-model-snapshot"
    assert completion.raw_output_sha256 == hashlib.sha256(raw.encode()).hexdigest()
    assert sdk.completions_for_test.calls == [{
        "model": "pinned-test-model-2026-07-12",
        "temperature": 0.0,
        "messages": [{"role": "user", "content": "原样 prompt；仅输出 JSON"}],
        "response_format": {"type": "json_object"},
    }]


@pytest.mark.parametrize(
    "response,match",
    [
        (_response("{}", finish_reason="length"), "incomplete:length"),
        (_response(""), "empty_content"),
        (_response("free text"), "schema_validation_failed"),
        (_response("{}", choices=2), "invalid_choice_count"),
    ],
)
def test_empty_truncated_invalid_or_free_text_never_falls_back(response, match):
    client = OpenAICompatibleClient(
        _sdk(response), _runtime(), get_provider_spec(LLMProvider.OPENAI_COMPATIBLE))

    with pytest.raises(LLMResponseError, match=match):
        client.complete_structured("仅输出 JSON", QuadrantCall)


def test_valid_quadrant_with_numeric_injection_is_rejected_not_silently_dropped():
    injected = json.dumps({
        "quadrant": "recovery",
        "confidence_band": "high",
        "citations": [],
        "rationale": "表面合法",
        "target_weights": {"equity": 1.0},
        "Omega": 0.0001,
    })
    client = OpenAICompatibleClient(
        _sdk(_response(injected)), _runtime(),
        get_provider_spec(LLMProvider.OPENAI_COMPATIBLE))

    with pytest.raises(LLMResponseError, match="schema_validation_failed"):
        client.complete_structured("仅输出 JSON", QuadrantCall)


def test_sdk_exception_is_called_once_and_exposes_only_stable_error_type():
    secret = "sk-super-secret-value"
    sdk = _sdk(exc=TimeoutError(f"Bearer {secret}"))
    client = OpenAICompatibleClient(
        sdk, _runtime(), get_provider_spec(LLMProvider.OPENAI_COMPATIBLE))

    with pytest.raises(LLMClientError) as caught:
        client.complete_structured("仅输出 JSON", QuadrantCall)

    assert len(sdk.completions_for_test.calls) == 1, "外层不得自写重试循环"
    assert "TimeoutError" in str(caught.value)
    assert secret not in str(caught.value)


def test_call_fingerprint_and_trace_id_are_canonical_and_sensitive_to_identity():
    base = _identity()
    assert base == _identity()
    assert base.trace_id == f"trace_{base.call_fingerprint}"
    assert len(base.call_fingerprint) == 64

    variants = [
        build_trace_identity(
            _runtime(provider=LLMProvider.DEEPSEEK), call_key="quadrant_call",
            prompt="仅输出 JSON", response_schema=QuadrantCall,
            allowed_citations={"news_001", "news_002"}),
        _identity(model="another-model"),
        _identity(temperature=0.3),
        _identity(max_retries=4),
        _identity(prompt="不同 prompt"),
        build_trace_identity(
            _runtime(), call_key="explain_view", prompt="仅输出 JSON",
            response_schema=ViewExplanation, allowed_citations={"news_001"}),
    ]
    assert len({base.trace_id, *(item.trace_id for item in variants)}) == 7
    assert "secret" not in json.dumps(base.__dict__ if hasattr(base, "__dict__") else {
        "trace_id": base.trace_id, "provider": base.provider})


def test_endpoint_change_alone_changes_trace_identity():
    base = _identity()
    changed = trace_identity_from_parts(
        call_key=base.call_key,
        provider=base.provider,
        provider_spec_version=base.provider_spec_version,
        endpoint="https://fixed-endpoint.example/v2",
        model=base.model,
        temperature=base.temperature,
        max_retries=base.max_retries,
        timeout_seconds=base.timeout_seconds,
        prompt="仅输出 JSON",
        response_schema=QuadrantCall,
        allowed_citations={"news_001", "news_002"},
    )

    assert changed.trace_id != base.trace_id
    assert changed.endpoint != base.endpoint


def test_service_trace_id_is_stable_and_exception_text_is_not_persistable():
    secret = "sk-super-secret-value"

    class ExplodingClient:
        provider = "test"
        model = "fake-model"

        def complete_structured(self, prompt, schema):
            raise TimeoutError(f"Authorization: Bearer {secret}")

    call_a, trace_a = quadrant_call_or_abstain(
        ExplodingClient(), "仅输出 JSON", {"news_001"})
    call_b, trace_b = quadrant_call_or_abstain(
        ExplodingClient(), "仅输出 JSON", {"news_001"})

    assert call_a.quadrant == call_b.quadrant == RegimeCall.ABSTAIN
    assert trace_a.trace_id == trace_b.trace_id
    assert trace_a.error_type == "TimeoutError"
    assert secret not in trace_a.model_dump_json()
    assert trace_a.structured_output["quadrant"] == "abstain"


def test_trace_redacts_prompt_output_and_reason_before_hashing():
    secret = "super-secret-value"
    prompt = f"Authorization: Bearer {secret}\napi_key={secret}"
    identity = _identity(prompt=prompt)
    trace = make_trace(
        identity,
        prompt=prompt,
        structured_output={"quadrant": "abstain", "rationale": secret},
        response_id=f"response-{secret}",
        response_model=f"model-{secret}",
        degraded=True,
        degraded_reason=f"Bearer {secret}",
        error_type="FixtureError",
        secrets={secret},
        created_at="2026-07-12T00:00:00+00:00",
    )
    dumped = trace.model_dump_json()

    assert secret not in dumped
    assert dumped.count("[REDACTED]") >= 3
    assert trace.output_sha256 == hashlib.sha256(
        json.dumps(trace.structured_output, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode()
    ).hexdigest()


def test_redaction_covers_mapping_keys_and_nested_sequence_or_set_values():
    secret = "nested-secret-value"
    redacted = trace_store._redact_value({
        secret: (
            [f"Bearer {secret}", {secret, "safe"}],
            {f"api_key={secret}": "visible"},
        ),
    }, (secret,))
    dumped = json.dumps(redacted, ensure_ascii=False, sort_keys=True)

    assert secret not in dumped
    assert "[REDACTED]" in dumped


def test_trace_write_is_private_atomic_byte_idempotent_and_cleans_temps(
    tmp_path, monkeypatch
):
    directory = tmp_path / "runs" / "llm_traces"
    monkeypatch.setattr(trace_store, "TRACE_DIR", directory)
    identity = _identity()
    first = make_trace(
        identity, prompt="仅输出 JSON", structured_output={"quadrant": "recovery"},
        tokens_in=1, latency_ms=12, response_id="first",
        created_at="2026-07-12T00:00:00+00:00")
    observational_variant = make_trace(
        identity, prompt="仅输出 JSON", structured_output={"quadrant": "recovery"},
        tokens_in=999, latency_ms=999, response_id="second",
        created_at="2026-07-13T00:00:00+00:00")

    saved = persist_trace(first)
    path = directory / f"{identity.trace_id}.json"
    before = path.read_bytes()
    replayed = persist_trace(observational_variant)

    assert saved.persisted and replayed.persisted
    assert saved == replayed
    assert not first.persisted, "内存 trace 未落盘前不得谎报 persisted"
    assert path.read_bytes() == before
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(directory.glob("*.tmp"))
    assert LLMTrace.model_validate_json(path.read_text(encoding="utf-8")) == saved


def test_replace_failure_cleans_unique_temp_and_never_returns_dangling_trace(
    tmp_path, monkeypatch
):
    directory = tmp_path / "llm_traces"
    monkeypatch.setattr(trace_store, "TRACE_DIR", directory)
    identity = _identity()
    trace = make_trace(identity, prompt="仅输出 JSON",
                       structured_output={"quadrant": "recovery"})

    def fail_replace(_src, _dst):
        raise OSError("fixture replace failure")

    monkeypatch.setattr(trace_store.os, "replace", fail_replace)
    with pytest.raises(TraceStoreError, match="原子写失败"):
        persist_trace(trace)

    assert not (directory / f"{identity.trace_id}.json").exists()
    assert not list(directory.glob("*.tmp"))


def test_trace_collision_corruption_legacy_defaults_and_path_traversal(
    tmp_path, monkeypatch
):
    directory = tmp_path / "llm_traces"
    monkeypatch.setattr(trace_store, "TRACE_DIR", directory)
    identity = _identity()
    first = make_trace(identity, prompt="仅输出 JSON",
                       structured_output={"quadrant": "recovery"})
    persist_trace(first)
    original = (directory / f"{identity.trace_id}.json").read_bytes()

    with pytest.raises(TraceCollisionError, match="不同结构化结果"):
        persist_trace(make_trace(
            identity, prompt="仅输出 JSON",
            structured_output={"quadrant": "recession"}))
    assert (directory / f"{identity.trace_id}.json").read_bytes() == original

    corrupt_id = "trace_" + "b" * 64
    (directory / f"{corrupt_id}.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(TraceCorruptError, match="损坏"):
        load_trace(corrupt_id)

    legacy = LLMTrace(
        trace_id="trace_" + "c" * 12,
        model="legacy-model",
        prompt_sha256="d" * 64,
    )
    (directory / f"{legacy.trace_id}.json").write_text(
        legacy.model_dump_json(), encoding="utf-8")
    loaded_legacy = load_trace(legacy.trace_id)
    assert loaded_legacy is not None and loaded_legacy.schema_version == 0
    assert loaded_legacy.structured_output is None

    with pytest.raises(ValueError, match="格式非法"):
        load_trace("../../etc/passwd")
    with pytest.raises(TraceCollisionError, match="schema_version"):
        persist_trace(legacy)


def test_v1_trace_rejects_identity_output_and_schema_cache_poisoning(
    tmp_path, monkeypatch
):
    directory = tmp_path / "llm_traces"
    monkeypatch.setattr(trace_store, "TRACE_DIR", directory)
    directory.mkdir(parents=True)
    identity = _identity()
    trace = make_trace(
        identity,
        prompt="仅输出 JSON",
        structured_output={"quadrant": "recovery"},
        created_at="2026-07-12T00:00:00+00:00",
    )
    path = directory / f"{identity.trace_id}.json"

    with pytest.raises(TraceCollisionError, match="调用指纹"):
        persist_trace(trace.model_copy(update={"model": "poisoned-model"}))

    path.write_text(
        trace.model_copy(update={"model": "poisoned-model"}).model_dump_json(),
        encoding="utf-8",
    )
    with pytest.raises(TraceCorruptError, match="调用指纹"):
        load_trace(identity.trace_id)

    other_identity = _identity(prompt="另一个调用")
    other = make_trace(
        other_identity,
        prompt="另一个调用",
        structured_output={"quadrant": "recovery"},
    )
    path.write_text(other.model_dump_json(), encoding="utf-8")
    with pytest.raises(TraceCorruptError, match="文件名"):
        load_trace(identity.trace_id)

    path.unlink()
    saved = persist_trace(trace)
    payload = saved.model_dump(mode="json")
    payload["structured_output"]["quadrant"] = "recession"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TraceCorruptError, match="输出摘要"):
        replay_or_record(identity, lambda: trace)

    injected = saved.model_dump(mode="json")
    injected["structured_output"]["target_weights"] = {"equity": 1.0}
    injected["output_sha256"] = hashlib.sha256(json.dumps(
        injected["structured_output"], ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode()).hexdigest()
    path.write_text(json.dumps(injected), encoding="utf-8")
    with pytest.raises(TraceCorruptError, match="响应 schema"):
        replay_or_record(identity, lambda: trace)


def test_replay_serializes_same_call_and_concurrent_distinct_calls_survive(
    tmp_path, monkeypatch
):
    directory = tmp_path / "llm_traces"
    monkeypatch.setattr(trace_store, "TRACE_DIR", directory)
    identity = _identity()
    producer_calls = 0
    results: list[tuple[str, bool]] = []

    def producer():
        nonlocal producer_calls
        producer_calls += 1
        return make_trace(identity, prompt="仅输出 JSON",
                          structured_output={"quadrant": "recovery"})

    def same_worker():
        trace, replayed = replay_or_record(identity, producer)
        results.append((trace.trace_id, replayed))

    threads = [threading.Thread(target=same_worker) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert producer_calls == 1
    assert {trace_id for trace_id, _ in results} == {identity.trace_id}
    assert [replayed for _, replayed in results].count(False) == 1
    assert [replayed for _, replayed in results].count(True) == 9

    distinct = [
        (_identity(prompt=f"仅输出 JSON {index}"), f"仅输出 JSON {index}")
        for index in range(6)
    ]

    def distinct_worker(item, prompt):
        replay_or_record(
            item,
            lambda: make_trace(item, prompt=prompt,
                               structured_output={"quadrant": "abstain"}),
        )

    threads = [threading.Thread(target=distinct_worker, args=(item, prompt))
               for item, prompt in distinct]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert all(load_trace(item.trace_id) is not None for item, _ in distinct)
    assert len(list(directory.glob("trace_*.json"))) == 7


def test_trace_directory_is_inside_ignored_persistent_runs_volume():
    expected = ROOT / "data" / "runs" / "llm_traces"
    assert trace_store.TRACE_DIR == expected
    ignored = subprocess.run(
        ["git", "check-ignore", "data/runs/llm_traces/fixture.json"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    tracked = subprocess.run(
        ["git", "ls-files", "data/runs/llm_traces"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert ignored.returncode == 0
    assert tracked.stdout == ""
    assert "target: /app/data/runs" in (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert 'VOLUME ["/app/data/runs"]' in (ROOT / "Dockerfile").read_text(encoding="utf-8")
