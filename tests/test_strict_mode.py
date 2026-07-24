"""Integration tests for AE402_STRICT=1 fail-loud mode (feat/ae402-strict-mode).

Strict mode is the operator-facing guarantee that a 200 response from the
backend actually corresponds to a real testnet write. Under
AE402_STRICT=1, every documented silent-fallback branch raises
:class:`server.strict.StrictModeError` instead of returning a synthesised
or mock result. See server/strict.py for the full contract.

These tests exercise the strict-mode surface in three layers:

  1. Config preconditions and startup gate. A misconfigured strict-mode
     app (empty CASPER_NODE_URL / empty contract_hash / SANDBOX=true)
     must refuse to start; a fully-configured one must start clean.

  2. Runtime guard behaviour. The `guard(cfg, path, reason)` helper must
     be a no-op when strict is off and raise :class:`StrictModeError`
     when it is on. `ensure_strict(cfg)` at startup must have the same
     asymmetry.

  3. HTTP surface. /health must expose the capability breakdown (empty
     when strict is off, populated with violations / guarantees when
     it is on) and the FastAPI exception handler must render an
     accidentally-raised StrictModeError as a 503 with a structured
     JSON body instead of a generic 500.

Every test uses an isolated Config instance and does NOT touch process
env vars, so the whole file runs cleanly regardless of the caller's
AE402_STRICT setting.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.config import Config
from server.strict import StrictModeError, ensure_strict, guard

# ---------------------------------------------------------------------------
# Layer 1: config preconditions + startup gate
# ---------------------------------------------------------------------------


class TestConfigPreconditions:
    def test_default_config_has_strict_disabled(self):
        cfg = Config()
        assert cfg.strict_mode is False

    def test_defaults_violate_all_four_preconditions(self):
        # Empty node_url, empty contract_hash, sandbox=True (default), empty
        # private key path -- this is the *dev* baseline. It must report
        # all four violations.
        cfg = Config()
        violations = cfg.require_strict_preconditions()
        assert len(violations) == 4
        joined = " ".join(violations)
        assert "casper_node_url" in joined
        assert "contract_hash" in joined
        assert "sandbox" in joined
        assert "casper_private_key_path" in joined

    def test_fully_configured_has_no_violations(self):
        cfg = Config(
            casper_node_url="https://node.testnet.example",
            contract_hash="hash-abcdef",
            sandbox=False,
            casper_private_key_path="/tmp/key.pem",
        )
        assert cfg.require_strict_preconditions() == []

    def test_missing_private_key_is_a_violation_even_with_everything_else_set(self):
        # server/app.py only constructs a live CasperClient when
        # `not sandbox and casper_node_url and casper_private_key_path` are
        # ALL set. Before this precondition existed, a strict-mode app with
        # casper_node_url/contract_hash/sandbox=false but no private key
        # would pass require_strict_preconditions() yet still silently fall
        # through to the None-casper-client / SandboxStore branch on every
        # request -- a strict-mode app returning green 200s that never
        # touched testnet. See docs/STRICT_MODE_ROLLOUT.md.
        cfg = Config(
            casper_node_url="https://node.testnet.example",
            contract_hash="hash-abcdef",
            sandbox=False,
            casper_private_key_path="",
        )
        violations = cfg.require_strict_preconditions()
        assert len(violations) == 1
        assert "casper_private_key_path" in violations[0]

    def test_partial_config_reports_specific_violations(self):
        # Node URL missing but everything else OK.
        cfg = Config(contract_hash="hash-abc", sandbox=False, casper_private_key_path="/tmp/key.pem")
        violations = cfg.require_strict_preconditions()
        assert len(violations) == 1
        assert "casper_node_url" in violations[0]

    def test_ensure_strict_noop_when_disabled(self):
        # Even with all preconditions failing, ensure_strict is a no-op
        # when strict_mode=False. Dev / demo mode must not be affected.
        cfg = Config()
        assert cfg.strict_mode is False
        ensure_strict(cfg)  # no exception

    def test_ensure_strict_raises_when_enabled_and_violated(self):
        cfg = Config(strict_mode=True)  # defaults => all 3 violations
        with pytest.raises(StrictModeError) as exc_info:
            ensure_strict(cfg)
        assert exc_info.value.path == "config.startup"
        assert "AE402_STRICT=1" in exc_info.value.reason
        # All three violations must be surfaced in the message so the
        # operator sees the full picture, not just the first.
        assert "casper_node_url" in exc_info.value.reason
        assert "contract_hash" in exc_info.value.reason
        assert "sandbox" in exc_info.value.reason

    def test_ensure_strict_passes_when_enabled_and_configured(self):
        cfg = Config(
            strict_mode=True,
            casper_node_url="https://node.testnet.example",
            contract_hash="hash-abc",
            sandbox=False,
            casper_private_key_path="/tmp/key.pem",
        )
        ensure_strict(cfg)  # no exception


# ---------------------------------------------------------------------------
# Layer 2: runtime guard behaviour
# ---------------------------------------------------------------------------


class TestRuntimeGuard:
    def test_guard_noop_when_strict_disabled(self):
        # A silent-fallback branch protected by guard() must be free to
        # fall back when the operator has not opted into strict mode.
        cfg = Config()  # strict_mode=False
        guard(cfg, "some.path", "some reason")  # no exception

    def test_guard_raises_when_strict_enabled(self):
        cfg = Config(
            strict_mode=True,
            casper_node_url="https://node.example",
            contract_hash="hash-abc",
            sandbox=False,
        )
        with pytest.raises(StrictModeError) as exc_info:
            guard(cfg, "casper_client.put_deploy.no_key", "private key path empty")
        assert exc_info.value.path == "casper_client.put_deploy.no_key"
        assert exc_info.value.reason == "private key path empty"

    def test_strict_mode_error_str_is_greppable(self):
        # Operators grep production logs for "[strict-mode]"; ensure the
        # str() format never changes silently.
        err = StrictModeError(path="rpc.timeout", reason="node did not respond in 5s")
        assert str(err) == "[strict-mode] rpc.timeout: node did not respond in 5s"

    def test_capabilities_shape_when_disabled(self):
        cfg = Config()
        caps = cfg.strict_mode_capabilities()
        # Structural: 4 top-level keys, no guarantees advertised.
        assert caps == {
            "enabled": False,
            "preconditions_ok": False,  # defaults still fail, but strict is off
            "violations": [
                "casper_node_url is empty (set CASPER_NODE_URL)",
                "contract_hash is empty (set ESCROW_CONTRACT_HASH)",
                "sandbox=true (set SANDBOX=false for live mode)",
                "casper_private_key_path is empty (set CASPER_PRIVATE_KEY_PATH or DEPLOYER_KEY_B64)",
            ],
            "guarantees": [],
        }

    def test_capabilities_shape_when_enabled_and_configured(self):
        cfg = Config(
            strict_mode=True,
            casper_node_url="https://node.example",
            contract_hash="hash-abc",
            sandbox=False,
            casper_private_key_path="/tmp/key.pem",
        )
        caps = cfg.strict_mode_capabilities()
        assert caps["enabled"] is True
        assert caps["preconditions_ok"] is True
        assert caps["violations"] == []
        # At least four documented operator-visible guarantees.
        assert len(caps["guarantees"]) >= 4
        joined = " ".join(caps["guarantees"])
        assert "RPC" in joined
        assert "contract hash" in joined
        assert "private key" in joined
        assert "DB write" in joined


# ---------------------------------------------------------------------------
# Layer 3: HTTP surface -- /health and exception handler
# ---------------------------------------------------------------------------


def _minimal_app(cfg: Config) -> FastAPI:
    """Build a minimal FastAPI app wired to the real /health handler +
    strict-mode exception handler, with the Config dependency swapped for
    the test-provided one.

    We build a fresh app per test instead of importing the production
    `server.app.app` singleton because the production app already loads
    a Config from env and holds background tasks; injecting a synthetic
    Config into it would fight the lifespan setup. The handler code
    under test is imported directly so the tests still cover the real
    path.

    Important: the /health handler in server/app.py uses a MODULE-LOCAL
    `get_config` (`@lru_cache`) as its FastAPI dependency, not the one
    exported from server.config. To make dependency_overrides actually
    fire we import that specific function and use it as the override key.
    """
    # NOTE: import from server.app, NOT server.config -- see docstring.
    from server.app import get_config as app_get_config
    from server.app import health as health_handler
    from server.strict import StrictModeError as _S

    app = FastAPI()

    async def _override_cfg():
        return cfg

    app.dependency_overrides[app_get_config] = _override_cfg
    app.get("/health")(health_handler)

    # Register the same exception handler shape as production.
    from fastapi.responses import JSONResponse

    @app.exception_handler(_S)
    async def _h(request, exc):
        return JSONResponse(
            status_code=503,
            content={
                "error": "strict_mode_violation",
                "path": exc.path,
                "reason": exc.reason,
            },
        )

    # A dev-only endpoint that intentionally trips guard(), so we can
    # exercise the exception handler end-to-end without stubbing an
    # entire chain client.
    @app.get("/_test/trigger_strict")
    async def trigger():
        guard(cfg, "test.forced", "intentional trigger for test")
        return {"status": "ok"}

    return app

    # ------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_reports_strict_disabled_by_default(self):
        cfg = Config()  # dev defaults
        client = TestClient(_minimal_app(cfg))
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["strict_mode"]["enabled"] is False
        # Still reports the underlying preconditions state.
        assert body["strict_mode"]["preconditions_ok"] is False
        assert len(body["strict_mode"]["violations"]) == 4

    def test_health_reports_strict_enabled_and_configured(self):
        cfg = Config(
            strict_mode=True,
            casper_node_url="https://node.example",
            contract_hash="hash-abc",
            sandbox=False,
            casper_private_key_path="/tmp/key.pem",
        )
        client = TestClient(_minimal_app(cfg))
        r = client.get("/health")
        assert r.status_code == 200
        caps = r.json()["strict_mode"]
        assert caps["enabled"] is True
        assert caps["preconditions_ok"] is True
        assert caps["violations"] == []
        assert len(caps["guarantees"]) >= 4

    def test_health_reports_strict_enabled_but_misconfigured(self):
        # Turn strict on WITHOUT satisfying preconditions. Not something a
        # real deployment does (startup would refuse), but a useful
        # observability signal: /health must show enabled=True + the
        # violations so an operator inspecting a stuck app sees the
        # actual reason.
        cfg = Config(strict_mode=True)  # all 4 defaults violated
        client = TestClient(_minimal_app(cfg))
        r = client.get("/health")
        assert r.status_code == 200
        caps = r.json()["strict_mode"]
        assert caps["enabled"] is True
        assert caps["preconditions_ok"] is False
        assert len(caps["violations"]) == 4


class TestExceptionHandler:
    def test_strict_mode_error_becomes_503_with_structured_body(self):
        cfg = Config(
            strict_mode=True,
            casper_node_url="https://node.example",
            contract_hash="hash-abc",
            sandbox=False,
        )
        client = TestClient(_minimal_app(cfg))
        r = client.get("/_test/trigger_strict")
        assert r.status_code == 503
        body = r.json()
        assert body == {
            "error": "strict_mode_violation",
            "path": "test.forced",
            "reason": "intentional trigger for test",
        }

    def test_no_503_when_strict_disabled(self):
        # Same endpoint, but strict off -- guard() is a no-op, handler
        # reaches the normal 200.
        cfg = Config()  # strict_mode=False
        client = TestClient(_minimal_app(cfg))
        r = client.get("/_test/trigger_strict")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestSandboxDbWriteGuard:
    """server/db.py::save_escrow returns False (does not raise) when
    Postgres is unreachable, and server/app.py's create_escrow /
    create_escrow_batch handlers previously ignored that return value --
    a strict-mode app could report a created escrow that was never
    persisted. See docs/STRICT_MODE_ROLLOUT.md."""

    def test_create_escrow_raises_under_strict_when_db_write_fails(self):
        import hashlib
        from unittest.mock import patch

        import server.app as appmod
        from server.sandbox import SandboxStore

        strict_cfg = Config(
            strict_mode=True,
            casper_node_url="https://node.example",
            contract_hash="hash-abc",
            sandbox=True,  # sandbox path is the one under test
            casper_private_key_path="/tmp/key.pem",
        )
        sandbox_store = SandboxStore()
        appmod.app.dependency_overrides[appmod.get_config] = lambda: strict_cfg
        appmod.app.dependency_overrides[appmod.get_sandbox] = lambda: sandbox_store
        try:
            with patch("server.app.pgdb.save_escrow", return_value=False):
                client = TestClient(appmod.app)
                h = hashlib.sha256(b"strict-db-write-fail").hexdigest()
                res = client.post(
                    "/escrow",
                    json={"receiver": "ab" * 32, "amount": 5000, "service_hash": h},
                )
            assert res.status_code == 503
            body = res.json()
            assert body["error"] == "strict_mode_violation"
            assert body["path"] == "app.create_escrow.sandbox_db_write_failed"
        finally:
            appmod.app.dependency_overrides.clear()

    def test_create_escrow_succeeds_when_strict_disabled_even_if_db_write_fails(self):
        import hashlib
        from unittest.mock import patch

        import server.app as appmod
        from server.sandbox import SandboxStore

        cfg = Config(sandbox=True)  # strict_mode=False
        sandbox_store = SandboxStore()
        appmod.app.dependency_overrides[appmod.get_config] = lambda: cfg
        appmod.app.dependency_overrides[appmod.get_sandbox] = lambda: sandbox_store
        try:
            with patch("server.app.pgdb.save_escrow", return_value=False):
                client = TestClient(appmod.app)
                h = hashlib.sha256(b"non-strict-db-write-fail").hexdigest()
                res = client.post(
                    "/escrow",
                    json={"receiver": "cd" * 32, "amount": 5000, "service_hash": h},
                )
            assert res.status_code == 200
        finally:
            appmod.app.dependency_overrides.clear()


class TestVrfElectionGuard:
    """server/vrf_election.py::elect_arbiter silently falls back from
    on-chain VRF to local CSPRNG when the on-chain call raises or returns no
    candidate. Under AE402_STRICT=1 with VRF configured, that fallback must
    raise StrictModeError instead (docs/STRICT_MODE_ROLLOUT.md item 6)."""

    def _reset(self):
        import server.vrf_election as vrf_mod

        vrf_mod._registered_arbiters.clear()
        vrf_mod._election_results.clear()

    def test_onchain_vrf_exception_raises_under_strict(self):
        import server.app as appmod
        import server.vrf_election as vrf_mod

        self._reset()
        strict_cfg = Config(
            strict_mode=True,
            casper_node_url="https://node.example",
            contract_hash="hash-abc",
            sandbox=False,
            casper_private_key_path="/tmp/key.pem",
            vrf_contract_hash="hash-vrf",
        )

        class _RaisingCasper:
            async def select_arbiters(self, dispute_id: str, count: int) -> str:
                raise RuntimeError("RPC timeout")

            async def confirm_election(self, *a, **kw):
                return None, None

        appmod._casper = _RaisingCasper()
        appmod.app.dependency_overrides[vrf_mod.get_config] = lambda: strict_cfg
        try:
            client = TestClient(appmod.app)
            client.post(
                "/vrf/arbiters/register",
                json={"agent": "neutral-arbiter", "score": 70, "completed": 3, "disputed": 0},
            )
            res = client.post(
                "/vrf/elect",
                json={
                    "dispute_id": "strict-onchain-fail-dispute",
                    "sender": "sender-account-hash",
                    "receiver": "receiver-account-hash",
                    "seed_hash": "ab" * 32,
                },
            )
            assert res.status_code == 503
            body = res.json()
            assert body["error"] == "strict_mode_violation"
            assert body["path"] == "vrf_election.elect_arbiter.onchain_vrf_failed"
        finally:
            appmod.app.dependency_overrides.pop(vrf_mod.get_config, None)
            appmod._casper = None

    def test_onchain_vrf_still_falls_back_when_strict_disabled(self):
        import server.app as appmod

        self._reset()

        class _RaisingCasper:
            async def select_arbiters(self, dispute_id: str, count: int) -> str:
                raise RuntimeError("RPC timeout")

            async def confirm_election(self, *a, **kw):
                return None, None

        appmod._casper = _RaisingCasper()
        try:
            client = TestClient(appmod.app)
            client.post(
                "/vrf/arbiters/register",
                json={"agent": "neutral-arbiter-2", "score": 70, "completed": 3, "disputed": 0},
            )
            res = client.post(
                "/vrf/elect",
                json={
                    "dispute_id": "non-strict-onchain-fail-dispute",
                    "sender": "sender-account-hash",
                    "receiver": "receiver-account-hash",
                    "seed_hash": "cd" * 32,
                },
            )
            assert res.status_code == 201
            assert res.json()["method"] == "local_csprng"
        finally:
            appmod._casper = None
