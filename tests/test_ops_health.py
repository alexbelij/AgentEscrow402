"""Operator health snapshot (AE-A2)."""

from __future__ import annotations

from server.ops_health import (
    ProviderState,
    RetryStats,
    build_snapshot,
)


def test_snapshot_default_shape():
    snap = build_snapshot(
        started_at=1_700_000_000,
        build_sha="abc123",
        config_version="v3",
        mode="sandbox",
        strict_mode={"capabilities_allow_list": []},
    )
    d = snap.as_dict()
    for key in [
        "started_at",
        "uptime_s",
        "build_sha",
        "config_version",
        "mode",
        "strict_mode",
        "dependencies",
        "retries",
        "warnings",
    ]:
        assert key in d
    assert d["build_sha"] == "abc123"
    assert d["mode"] == "sandbox"


def test_snapshot_uptime_monotonic():
    snap = build_snapshot(
        started_at=1_000_000_000,
        build_sha="x",
        config_version="v1",
        mode="live",
        strict_mode={},
    )
    assert snap.uptime_s > 0


def test_snapshot_warns_when_no_providers_configured(monkeypatch):
    for key in ["GROQ_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"]:
        monkeypatch.delenv(key, raising=False)
    snap = build_snapshot(
        started_at=1_700_000_000,
        build_sha="x",
        config_version="v1",
        mode="live",
        strict_mode={},
    )
    assert any("no primary LLM provider" in w for w in snap.warnings)


def test_snapshot_no_warn_when_provider_configured(monkeypatch):
    for key in ["NVIDIA_API_KEY", "OPENROUTER_API_KEY"]:
        monkeypatch.delenv(key, raising=False)
    # Groq alone should suppress the "no primary" warning.
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake_key_for_test_only_not_real")
    snap = build_snapshot(
        started_at=1_700_000_000,
        build_sha="x",
        config_version="v1",
        mode="live",
        strict_mode={},
    )
    assert not any("no primary LLM provider" in w for w in snap.warnings)


def test_snapshot_warns_on_open_circuit_breaker():
    states = [
        ProviderState(name="groq", configured=True, circuit_state="open", consecutive_failures=5),
    ]
    snap = build_snapshot(
        started_at=1_700_000_000,
        build_sha="x",
        config_version="v1",
        mode="live",
        strict_mode={},
        provider_states=states,
    )
    assert any("groq" in w and "OPEN" in w for w in snap.warnings)


def test_snapshot_carries_retry_stats():
    snap = build_snapshot(
        started_at=1_700_000_000,
        build_sha="x",
        config_version="v1",
        mode="live",
        strict_mode={},
        retries=RetryStats(pending=3, failed_last_24h=7, succeeded_last_24h=42),
    )
    r = snap.retries.as_dict()
    assert r == {"pending": 3, "failed_last_24h": 7, "succeeded_last_24h": 42}


def test_provider_state_never_leaks_key():
    """Provider state persists the *env var name* effect (configured yes/no),
    never the value."""
    ps = ProviderState(name="groq", configured=True, model="llama-3.1-70b")
    d = ps.as_dict()
    assert d == {
        "name": "groq",
        "configured": True,
        "model": "llama-3.1-70b",
        "last_ok_at": 0,
        "last_error_at": 0,
        "consecutive_failures": 0,
        "circuit_state": "closed",
    }
    # No 'api_key', 'key', 'secret' anywhere in the persisted shape:
    for forbidden in ("api_key", "key", "secret", "token", "authorization"):
        assert forbidden not in d


def test_env_only_snapshot_reflects_configured_state(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_dummy_test_value_never_used")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.1-70b")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    snap = build_snapshot(
        started_at=1_700_000_000,
        build_sha="x",
        config_version="v1",
        mode="live",
        strict_mode={},
    )
    providers = {p.name: p for p in snap.dependencies}
    assert providers["groq"].configured is True
    assert providers["groq"].model == "llama-3.1-70b"
    assert providers["nvidia"].configured is False
    assert providers["openrouter"].configured is False
