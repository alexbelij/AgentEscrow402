"""Operator surface: enriched health, dependency status, retry visibility (AE-A2).

The existing `/health` endpoint is the load-balancer probe — it must be
cheap and boolean-shaped. Operators (and judges evaluating operator UX)
need a richer surface that says:

- What's connected right now (db, LLM providers, casper client)?
- What's been failing (recent failed txs, retry queue depth)?
- What's the circuit-breaker state on each provider?
- What's the effective config version / build?

This module keeps that logic out of `app.py` so it can be tested in
isolation and grown without polluting the main router.

Design:
- Zero external calls in the fast path (no live LLM ping). We report
  the *last observed* state of each dependency.
- Deterministic response shape — same keys always present, so a UI
  can bind fields without conditional guards.
- No secrets in the response: provider readiness is boolean +
  configured-model name, never keys.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderState:
    """One LLM / infra dependency's runtime state.

    `configured` — env is wired for this provider.
    `last_ok_at` — unix ts of most recent successful call (0 = never).
    `last_error_at` — unix ts of most recent failure (0 = never).
    `consecutive_failures` — since last success.
    `circuit_state` — "closed" (normal), "open" (skipped), "half_open" (probing).
    """

    name: str
    configured: bool
    model: str | None = None
    last_ok_at: int = 0
    last_error_at: int = 0
    consecutive_failures: int = 0
    circuit_state: str = "closed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "configured": self.configured,
            "model": self.model,
            "last_ok_at": self.last_ok_at,
            "last_error_at": self.last_error_at,
            "consecutive_failures": self.consecutive_failures,
            "circuit_state": self.circuit_state,
        }


@dataclass
class RetryStats:
    """Aggregate retry-queue visibility."""

    pending: int = 0
    failed_last_24h: int = 0
    succeeded_last_24h: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "pending": self.pending,
            "failed_last_24h": self.failed_last_24h,
            "succeeded_last_24h": self.succeeded_last_24h,
        }


@dataclass
class OpsSnapshot:
    """Everything an operator (or judge) needs in one payload."""

    started_at: int
    uptime_s: int
    build_sha: str
    config_version: str
    mode: str  # "sandbox" | "live"
    strict_mode: dict[str, Any]
    dependencies: list[ProviderState] = field(default_factory=list)
    retries: RetryStats = field(default_factory=RetryStats)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "uptime_s": self.uptime_s,
            "build_sha": self.build_sha,
            "config_version": self.config_version,
            "mode": self.mode,
            "strict_mode": self.strict_mode,
            "dependencies": [d.as_dict() for d in self.dependencies],
            "retries": self.retries.as_dict(),
            "warnings": list(self.warnings),
        }


def _provider_from_env(name: str, env_key: str, model_env_key: str | None = None) -> ProviderState:
    return ProviderState(
        name=name,
        configured=bool(os.getenv(env_key)),
        model=os.getenv(model_env_key) if model_env_key else None,
    )


def build_snapshot(
    *,
    started_at: int,
    build_sha: str,
    config_version: str,
    mode: str,
    strict_mode: dict[str, Any],
    provider_states: list[ProviderState] | None = None,
    retries: RetryStats | None = None,
) -> OpsSnapshot:
    """Assemble a snapshot. Callers can override `provider_states` (tests,
    live circuit-breaker state) and `retries` (real queue depth); when
    omitted we fall back to env-only introspection.
    """
    if provider_states is None:
        provider_states = [
            _provider_from_env("groq", "GROQ_API_KEY", "GROQ_MODEL"),
            _provider_from_env("nvidia", "NVIDIA_API_KEY", "NVIDIA_MODEL"),
            _provider_from_env("openrouter", "OPENROUTER_API_KEY", "OPENROUTER_MODEL"),
            _provider_from_env("gemini", "GEMINI_API_KEY", "GEMINI_MODEL"),
        ]

    warnings: list[str] = []
    if not any(p.configured for p in provider_states if p.name != "gemini"):
        warnings.append("no primary LLM provider configured — arbitration will use heuristic fallback")
    for p in provider_states:
        if p.circuit_state == "open":
            warnings.append(f"provider {p.name}: circuit breaker OPEN")

    return OpsSnapshot(
        started_at=started_at,
        uptime_s=max(0, int(time.time()) - started_at),
        build_sha=build_sha,
        config_version=config_version,
        mode=mode,
        strict_mode=strict_mode,
        dependencies=provider_states,
        retries=retries or RetryStats(),
        warnings=warnings,
    )


__all__ = [
    "OpsSnapshot",
    "ProviderState",
    "RetryStats",
    "build_snapshot",
]
