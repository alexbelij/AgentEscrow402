"""Integration tests for the FastAPI application."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from server.app import app, get_casper, get_config, get_sandbox
from server.config import Config
from server.sandbox import SandboxStore


def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


# EscrowRequest.receiver requires a raw 64-hex string (optionally
# "account-hash-" prefixed) — see server/models.py. Plain slugs like "r" or
# "receiver-001" fail pydantic validation with a 422, so tests use these
# realistic-looking hex receivers instead.
RECEIVER_HEX = "ab" * 32
RECEIVER_HEX_2 = "cd" * 32


@pytest.fixture
def sandbox_store():
    return SandboxStore()


@pytest.fixture
def client(sandbox_store):
    cfg = Config(sandbox=True)
    app.dependency_overrides[get_config] = lambda: cfg
    app.dependency_overrides[get_sandbox] = lambda: sandbox_store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["sandbox"] is True

    def test_health_version(self, client):
        resp = client.get("/health")
        assert resp.json()["version"] == "0.3.0"


class TestEscrowEndpoint:
    def test_create_escrow(self, client):
        h = _hash("svc-001")
        resp = client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 5000,
                "service_hash": h,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["amount"] == 4900  # net after 2% insurance fee
        assert body["status"] == "pending"

    def test_create_duplicate_escrow_returns_409(self, client):
        h = _hash("svc-dup")
        client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
            },
        )
        resp = client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
            },
        )
        assert resp.status_code == 409


class TestBatchEscrowEndpoint:
    """escrow-manager.create_batch() wiring (A2 backlog item) — sandbox mode.

    Live-mode on-chain path (server/casper_client.py CasperClient.create_batch,
    contracts/batch-funder session-wasm) was verified directly against
    testnet (5-escrow batch, error_message: None, 6 transfers) rather than
    mocked here, since a real Casper deploy can't run in a unit test.
    """

    def test_create_batch(self, client):
        resp = client.post(
            "/escrows/batch",
            json={
                "escrows": [
                    {"receiver": RECEIVER_HEX, "amount": 1000, "service_hash": _hash("batch-1")},
                    {"receiver": RECEIVER_HEX_2, "amount": 2000, "service_hash": _hash("batch-2")},
                ]
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["created"] == 2
        assert body["deploy_hash"] is None  # sandbox mode: no real deploy
        assert len(body["records"]) == 2
        assert {r["amount"] for r in body["records"]} == {1000, 2000}
        assert all(r["status"] == "pending" for r in body["records"])

    def test_create_batch_duplicate_service_hash_in_request_rejected(self, client):
        h = _hash("batch-dup-in-request")
        resp = client.post(
            "/escrows/batch",
            json={
                "escrows": [
                    {"receiver": RECEIVER_HEX, "amount": 1000, "service_hash": h},
                    {"receiver": RECEIVER_HEX_2, "amount": 2000, "service_hash": h},
                ]
            },
        )
        assert resp.status_code == 422

    def test_create_batch_conflicts_with_existing_escrow(self, client):
        h = _hash("batch-existing")
        client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 100, "service_hash": h},
        )
        resp = client.post(
            "/escrows/batch",
            json={"escrows": [{"receiver": RECEIVER_HEX, "amount": 100, "service_hash": h}]},
        )
        assert resp.status_code == 409

    def test_create_batch_empty_list_rejected(self, client):
        resp = client.post("/escrows/batch", json={"escrows": []})
        assert resp.status_code == 422

    def test_create_batch_over_max_size_rejected(self, client):
        escrows = [
            {"receiver": RECEIVER_HEX, "amount": 100, "service_hash": _hash(f"batch-big-{i}")} for i in range(51)
        ]
        resp = client.post("/escrows/batch", json={"escrows": escrows})
        assert resp.status_code == 422


class TestBatchLifecycle:
    """batch_release / batch_cancel with server-side cap/quorum guard."""

    def _create_batch(self, client, prefix: str, count: int = 2):
        """Helper: create a batch of pending escrows and return their hashes."""
        hashes = [_hash(f"{prefix}-{i}") for i in range(count)]
        resp = client.post(
            "/escrows/batch",
            json={"escrows": [{"receiver": RECEIVER_HEX, "amount": 1000, "service_hash": h} for h in hashes]},
        )
        assert resp.status_code == 200
        return hashes

    def test_batch_release_success(self, client):
        hashes = self._create_batch(client, "brel")
        resp = client.post("/escrows/batch-release", json={"service_hashes": hashes})
        assert resp.status_code == 200
        body = resp.json()
        assert body["processed"] == 2
        # Verify escrows are now released
        for h in hashes:
            r = client.get(f"/escrow/{h}")
            assert r.status_code == 200
            assert r.json()["status"] == "released"

    def test_batch_cancel_success(self, client):
        hashes = self._create_batch(client, "bcan")
        resp = client.post("/escrows/batch-cancel", json={"service_hashes": hashes})
        assert resp.status_code == 200
        body = resp.json()
        assert body["processed"] == 2
        for h in hashes:
            r = client.get(f"/escrow/{h}")
            assert r.status_code == 200
            assert r.json()["status"] == "refunded"

    def test_batch_release_not_found(self, client):
        resp = client.post(
            "/escrows/batch-release",
            json={"service_hashes": [_hash("no-exist")]},
        )
        assert resp.status_code == 404

    def test_batch_cancel_already_released(self, client):
        hashes = self._create_batch(client, "bcan-rel")
        client.post("/escrows/batch-release", json={"service_hashes": hashes})
        resp = client.post("/escrows/batch-cancel", json={"service_hashes": hashes})
        assert resp.status_code == 422

    def test_batch_release_empty_rejected(self, client):
        resp = client.post("/escrows/batch-release", json={"service_hashes": []})
        assert resp.status_code == 422

    def test_batch_release_over_max_rejected(self, client):
        resp = client.post(
            "/escrows/batch-release",
            json={"service_hashes": [_hash(f"big-{i}") for i in range(51)]},
        )
        assert resp.status_code == 422


class TestStreamClaim:
    """POST /escrow/{hash}/stream-claim — API-timed vesting + on-chain settlement.

    The stream-claim endpoint itself has no x402 dependency (the vesting
    schedule proves entitlement), so we test it by seeding the in-memory
    _streaming_escrows dict + SandboxStore directly — bypassing the x402-
    gated /escrow/stream creation path that would need real signatures.
    """

    @staticmethod
    def _seed_stream(sandbox_store, service_hash, start_time, end_time, amount=5000):
        """Seed a streaming escrow directly into the in-memory store."""
        from server.multi_asset import _streaming_escrows

        record = sandbox_store.create_escrow(
            sender="aa" * 32,
            receiver=RECEIVER_HEX,
            amount=amount,
            service_hash=service_hash,
            ttl=86400,
        )
        _streaming_escrows[service_hash] = {
            "escrow_record": record,
            "token": {"token_type": "CSPR"},
            "start_time": start_time,
            "end_time": end_time,
            "streamed_amount": 0,
            "last_payout_time": None,
        }

    def test_stream_claim_not_found(self, client):
        resp = client.post(f"/escrow/{_hash('no-stream')}/stream-claim")
        assert resp.status_code == 404

    def test_stream_claim_before_vested(self, client, sandbox_store):
        """Stream not yet fully elapsed → 422."""
        import time

        now = int(time.time())
        h = _hash("stream-early")
        self._seed_stream(sandbox_store, h, now - 10, now + 3600)
        resp = client.post(f"/escrow/{h}/stream-claim")
        assert resp.status_code == 422
        assert "not fully vested" in resp.json()["detail"]

    def test_stream_claim_after_vested(self, client, sandbox_store):
        """Stream fully elapsed → on-chain release triggered."""
        import time

        now = int(time.time())
        h = _hash("stream-done")
        self._seed_stream(sandbox_store, h, now - 3600, now - 1)
        resp = client.post(f"/escrow/{h}/stream-claim")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "claimed"
        assert body["service_hash"] == h

    def test_stream_double_claim(self, client, sandbox_store):
        """Second claim returns already_claimed."""
        import time

        now = int(time.time())
        h = _hash("stream-dbl")
        self._seed_stream(sandbox_store, h, now - 3600, now - 1)
        client.post(f"/escrow/{h}/stream-claim")
        resp = client.post(f"/escrow/{h}/stream-claim")
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_claimed"


class TestEscrowEndpointInvalid:
    def test_create_escrow_invalid_amount(self, client):
        h = _hash("invalid")
        resp = client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 0,
                "service_hash": h,
            },
        )
        assert resp.status_code == 422

    def test_get_escrow(self, client):
        h = _hash("get-test")
        client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
            },
        )
        resp = client.get(f"/escrow/{h}")
        assert resp.status_code == 200
        assert resp.json()["service_hash"] == h

    def test_get_nonexistent_escrow(self, client):
        resp = client.get(f"/escrow/{_hash('missing')}")
        assert resp.status_code == 404


class TestWasmEscrowFunderEndpoint:
    def test_serves_wasm_bytes(self, client):
        resp = client.get("/wasm/escrow_funder")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/wasm"
        assert len(resp.content) > 0


class TestLiveWalletCreateEscrow:
    """`/escrow` POST when `wallet_tx_hash` is set — live-wallet path from
    `useCreateEscrowAction` (frontend), see server/casper_client.py
    `confirm_wallet_created_escrow`."""

    @pytest.fixture
    def live_client(self, sandbox_store):
        cfg = Config(sandbox=False)
        mock_casper = AsyncMock()
        app.dependency_overrides[get_config] = lambda: cfg
        app.dependency_overrides[get_sandbox] = lambda: sandbox_store
        app.dependency_overrides[get_casper] = lambda: mock_casper
        with TestClient(app) as c:
            yield c, mock_casper
        app.dependency_overrides.clear()

    def test_requires_sender_public_key_hex(self, live_client):
        c, _ = live_client
        h = _hash("wallet-missing-sender")
        resp = c.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 5000,
                "service_hash": h,
                "wallet_tx_hash": "deploy-abc",
            },
        )
        assert resp.status_code == 422

    def test_confirmed_wallet_tx_creates_record(self, live_client):
        c, mock_casper = live_client
        mock_casper.confirm_wallet_created_escrow = AsyncMock(return_value=(True, None))
        h = _hash("wallet-confirmed")
        resp = c.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 5000,
                "service_hash": h,
                "wallet_tx_hash": "deploy-abc",
                "sender_public_key_hex": "01" + "ab" * 32,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["deploy_hash"] == "deploy-abc"
        assert body["sender"] == "01" + "ab" * 32
        mock_casper.confirm_wallet_created_escrow.assert_awaited_once()

    def test_unconfirmed_wallet_tx_returns_502_with_revert_reason(self, live_client):
        c, mock_casper = live_client
        mock_casper.confirm_wallet_created_escrow = AsyncMock(
            return_value=(False, "Mint error: 4 (InvalidAccessRights)")
        )
        h = _hash("wallet-reverted")
        resp = c.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 5000,
                "service_hash": h,
                "wallet_tx_hash": "deploy-def",
                "sender_public_key_hex": "01" + "cd" * 32,
            },
        )
        assert resp.status_code == 502
        assert "InvalidAccessRights" in resp.json()["detail"]

    def test_unconfirmed_wallet_tx_without_revert_reason_still_502(self, live_client):
        c, mock_casper = live_client
        mock_casper.confirm_wallet_created_escrow = AsyncMock(return_value=(False, None))
        h = _hash("wallet-pending")
        resp = c.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 5000,
                "service_hash": h,
                "wallet_tx_hash": "deploy-ghi",
                "sender_public_key_hex": "01" + "ef" * 32,
            },
        )
        assert resp.status_code == 502
        assert "not yet confirmed" in resp.json()["detail"]

    def test_non_wallet_live_path_uses_hosted_casper_create_escrow(self, live_client):
        c, mock_casper = live_client
        mock_casper.create_escrow = AsyncMock(return_value="deploy-hosted-1")
        h = _hash("hosted-live")
        resp = c.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 5000,
                "service_hash": h,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["deploy_hash"] == "deploy-hosted-1"
        mock_casper.create_escrow.assert_awaited_once()


class TestReleaseEndpoint:
    def test_release(self, client):
        h = _hash("release-test")
        client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
            },
            params={"sender": "alice"},
        )
        resp = client.post(
            "/release",
            json={
                "service_hash": h,
            },
            params={"sender": "alice"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "released"

    def test_release_nonexistent(self, client):
        resp = client.post(
            "/release",
            json={
                "service_hash": _hash("no-such"),
            },
        )
        assert resp.status_code == 404

    def test_release_blocked_by_flash_guard_when_enabled(self, sandbox_store):
        # T2.12: with the guard on, a release attempted immediately after
        # funding must be rejected — this is the exact fund-then-release
        # window a flash-loan-funded attacker would exploit.
        cfg = Config(sandbox=True, flash_guard_enabled=True)
        app.dependency_overrides[get_config] = lambda: cfg
        app.dependency_overrides[get_sandbox] = lambda: sandbox_store
        c = TestClient(app)
        h = _hash("flash-guard-block")
        c.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 100, "service_hash": h},
            params={"sender": "alice"},
        )
        resp = c.post("/release", json={"service_hash": h}, params={"sender": "alice"})
        assert resp.status_code == 422
        assert "flash guard" in resp.json()["detail"]
        assert "hold period not met" in resp.json()["detail"]

    def test_release_allowed_by_flash_guard_after_hold_period(self, sandbox_store):
        # Same guard, but the escrow's created_at is back-dated past the
        # hold window -- release must go through normally.
        cfg = Config(sandbox=True, flash_guard_enabled=True)
        app.dependency_overrides[get_config] = lambda: cfg
        app.dependency_overrides[get_sandbox] = lambda: sandbox_store
        c = TestClient(app)
        h = _hash("flash-guard-pass")
        c.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 100, "service_hash": h},
            params={"sender": "alice"},
        )
        rec = sandbox_store.get_escrow(h)
        rec.created_at -= 301  # push funding time past MIN_HOLD_PERIOD_SECS
        sandbox_store._escrows[h]["created_at"] = rec.created_at
        resp = c.post("/release", json={"service_hash": h}, params={"sender": "alice"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "released"

    def test_release_flash_guard_disabled_by_default(self, client):
        # Default Config() has flash_guard_enabled=False -- the existing
        # instant create->release happy path (test_release above) must
        # keep working unmodified for anyone not opting in.
        h = _hash("flash-guard-default-off")
        client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 100, "service_hash": h},
            params={"sender": "alice"},
        )
        resp = client.post("/release", json={"service_hash": h}, params={"sender": "alice"})
        assert resp.status_code == 200


class TestRefundEndpoint:
    def test_refund(self, client):
        h = _hash("refund-test")
        client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
            },
            params={"sender": "bob"},
        )
        resp = client.post(
            "/refund",
            json={
                "service_hash": h,
            },
            params={"sender": "bob"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "refunded"


class TestDisputeEndpoint:
    def test_dispute(self, client):
        h = _hash("dispute-test")
        client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
            },
        )
        resp = client.post(
            "/dispute",
            json={
                "service_hash": h,
                "reason_hash": "b" * 64,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "disputed"

    def test_dispute_nonexistent(self, client):
        resp = client.post(
            "/dispute",
            json={
                "service_hash": _hash("gone"),
                "reason_hash": "c" * 64,
            },
        )
        assert resp.status_code == 404


class TestReputationEndpoint:
    def test_default_reputation(self, client):
        resp = client.get("/reputation/unknown-agent")
        assert resp.status_code == 200
        body = resp.json()
        assert body["completed"] == 0
        assert body["score"] == 50

    def test_reputation_increases_on_release(self, client):
        h = _hash("rep-test")
        client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX_2,
                "amount": 100,
                "service_hash": h,
            },
            params={"sender": "payer"},
        )
        client.post(
            "/release",
            json={
                "service_hash": h,
            },
            params={"sender": "payer"},
        )
        resp = client.get(f"/reputation/{RECEIVER_HEX_2}")
        assert resp.json()["completed"] == 1


class TestResolveEndpoint:
    """`/resolve` now requires real Ed25519 arbiter vote signatures, verified
    locally against `Config.arbiter_pubkeys` (mirrors the on-chain check)."""

    @staticmethod
    def _make_arbiters(n: int):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        keys = [Ed25519PrivateKey.generate() for _ in range(n)]
        pubkeys = tuple("01" + k.public_key().public_bytes_raw().hex() for k in keys)
        return keys, pubkeys

    @staticmethod
    def _sign(key, service_hash: str, in_favor_of: str) -> str:
        message = f"resolve:{service_hash}:{in_favor_of}".encode()
        return "01" + key.sign(message).hex()

    def _client_with_arbiters(self, sandbox_store, pubkeys):
        cfg = Config(sandbox=True, arbiter_pubkeys=pubkeys, arbiter_threshold=3)
        app.dependency_overrides[get_config] = lambda: cfg
        app.dependency_overrides[get_sandbox] = lambda: sandbox_store
        client = TestClient(app)
        return client

    def _open_disputed_escrow(self, client, h: str):
        client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 100, "service_hash": h},
        )
        resp = client.post("/dispute", json={"service_hash": h, "reason_hash": "b" * 64})
        assert resp.status_code == 200

    def test_resolve_with_valid_threshold_signatures_succeeds(self, sandbox_store):
        keys, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys)
        try:
            h = _hash("resolve-ok")
            self._open_disputed_escrow(client, h)
            sigs = [self._sign(k, h, "receiver") for k in keys[:3]]
            resp = client.post(
                "/resolve",
                json={
                    "service_hash": h,
                    "in_favor_of": "receiver",
                    "arbiter_pubkeys": list(pubkeys[:3]),
                    "arbiter_signatures": sigs,
                },
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "resolved"
        finally:
            app.dependency_overrides.clear()

    def test_resolve_rejects_below_threshold(self, sandbox_store):
        keys, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys)
        try:
            h = _hash("resolve-too-few")
            self._open_disputed_escrow(client, h)
            sigs = [self._sign(k, h, "receiver") for k in keys[:2]]  # only 2, need 3
            resp = client.post(
                "/resolve",
                json={
                    "service_hash": h,
                    "in_favor_of": "receiver",
                    "arbiter_pubkeys": list(pubkeys[:2]),
                    "arbiter_signatures": sigs,
                },
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_resolve_rejects_forged_signatures_from_unregistered_key(self, sandbox_store):
        keys, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys)
        try:
            h = _hash("resolve-forged")
            self._open_disputed_escrow(client, h)
            outsider_keys, outsider_pubkeys = self._make_arbiters(3)
            sigs = [self._sign(k, h, "receiver") for k in outsider_keys]
            resp = client.post(
                "/resolve",
                json={
                    "service_hash": h,
                    "in_favor_of": "receiver",
                    "arbiter_pubkeys": list(outsider_pubkeys),
                    "arbiter_signatures": sigs,
                },
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_resolve_rejects_replayed_signature_for_flipped_verdict(self, sandbox_store):
        keys, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys)
        try:
            h = _hash("resolve-replay")
            self._open_disputed_escrow(client, h)
            # Sign for "receiver" but submit claiming "sender" -- must fail.
            sigs = [self._sign(k, h, "receiver") for k in keys[:3]]
            resp = client.post(
                "/resolve",
                json={
                    "service_hash": h,
                    "in_favor_of": "sender",
                    "arbiter_pubkeys": list(pubkeys[:3]),
                    "arbiter_signatures": sigs,
                },
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()


class TestReleaseCapApproval:
    """A1 hardening: /release requires arbiter-quorum cap-approval when the
    escrow amount exceeds Config.release_cap_motes (mirrors the on-chain
    require_arbiter_cap_approval check in contracts/escrow/src/main.rs)."""

    @staticmethod
    def _make_arbiters(n: int):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        keys = [Ed25519PrivateKey.generate() for _ in range(n)]
        pubkeys = tuple("01" + k.public_key().public_bytes_raw().hex() for k in keys)
        return keys, pubkeys

    @staticmethod
    def _sign(key, service_hash: str) -> str:
        message = f"release:{service_hash}:cap_approval".encode()
        return "01" + key.sign(message).hex()

    def _client_with_arbiters(self, sandbox_store, pubkeys, release_cap_motes=1000):
        cfg = Config(
            sandbox=True,
            arbiter_pubkeys=pubkeys,
            arbiter_threshold=3,
            release_cap_motes=release_cap_motes,
        )
        app.dependency_overrides[get_config] = lambda: cfg
        app.dependency_overrides[get_sandbox] = lambda: sandbox_store
        return TestClient(app)

    def test_below_cap_release_succeeds_without_signatures(self, sandbox_store):
        _, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys, release_cap_motes=1000)
        try:
            h = _hash("cap-below")
            client.post(
                "/escrow",
                json={"receiver": RECEIVER_HEX, "amount": 100, "service_hash": h},
                params={"sender": "payer"},
            )
            resp = client.post("/release", json={"service_hash": h}, params={"sender": "payer"})
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "released"
        finally:
            app.dependency_overrides.clear()

    def test_above_cap_release_without_signatures_rejected(self, sandbox_store):
        _, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys, release_cap_motes=100)
        try:
            h = _hash("cap-above-no-sig")
            client.post(
                "/escrow",
                json={"receiver": RECEIVER_HEX, "amount": 1000, "service_hash": h},
                params={"sender": "payer"},
            )
            resp = client.post("/release", json={"service_hash": h}, params={"sender": "payer"})
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_above_cap_release_with_valid_quorum_succeeds(self, sandbox_store):
        keys, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys, release_cap_motes=100)
        try:
            h = _hash("cap-above-ok")
            client.post(
                "/escrow",
                json={"receiver": RECEIVER_HEX, "amount": 1000, "service_hash": h},
                params={"sender": "payer"},
            )
            sigs = [self._sign(k, h) for k in keys[:3]]
            resp = client.post(
                "/release",
                json={
                    "service_hash": h,
                    "arbiter_pubkeys": list(pubkeys[:3]),
                    "arbiter_signatures": sigs,
                },
                params={"sender": "payer"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "released"
        finally:
            app.dependency_overrides.clear()

    def test_above_cap_release_below_threshold_rejected(self, sandbox_store):
        keys, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys, release_cap_motes=100)
        try:
            h = _hash("cap-above-too-few")
            client.post(
                "/escrow",
                json={"receiver": RECEIVER_HEX, "amount": 1000, "service_hash": h},
                params={"sender": "payer"},
            )
            sigs = [self._sign(k, h) for k in keys[:2]]  # only 2, need 3
            resp = client.post(
                "/release",
                json={
                    "service_hash": h,
                    "arbiter_pubkeys": list(pubkeys[:2]),
                    "arbiter_signatures": sigs,
                },
                params={"sender": "payer"},
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()


class TestAdminRoutes:
    """Installer-only admin endpoints (server/admin_api.py). Sandbox/no-key
    combinations are exercised here; live on-chain submission is covered by
    the CasperClient unit tests, not here (no real chain in CI)."""

    def _client(self, admin_api_key="", sandbox=True):
        from server.config import get_config as admin_get_config

        cfg = Config(sandbox=sandbox, admin_api_key=admin_api_key)
        app.dependency_overrides[get_config] = lambda: cfg
        app.dependency_overrides[admin_get_config] = lambda: cfg
        return TestClient(app)

    def test_disabled_without_admin_api_key(self):
        client = self._client(admin_api_key="")
        try:
            resp = client.post("/admin/configure-fee", json={"new_fee_bps": 300})
            assert resp.status_code == 503
        finally:
            app.dependency_overrides.clear()

    def test_rejects_missing_header(self):
        client = self._client(admin_api_key="secret123")
        try:
            resp = client.post("/admin/configure-fee", json={"new_fee_bps": 300})
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_rejects_wrong_header(self):
        client = self._client(admin_api_key="secret123")
        try:
            resp = client.post(
                "/admin/configure-fee",
                json={"new_fee_bps": 300},
                headers={"X-Admin-Key": "wrong"},
            )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_accepted_key_but_sandbox_mode_rejected(self):
        # Right key, but admin ops require live mode (a real Casper client) --
        # sandbox mode has nothing on-chain to configure.
        client = self._client(admin_api_key="secret123", sandbox=True)
        try:
            resp = client.post(
                "/admin/configure-fee",
                json={"new_fee_bps": 300},
                headers={"X-Admin-Key": "secret123"},
            )
            assert resp.status_code == 409
        finally:
            app.dependency_overrides.clear()

    def test_configure_fee_validates_bps_range(self):
        client = self._client(admin_api_key="secret123", sandbox=True)
        try:
            resp = client.post(
                "/admin/configure-fee",
                json={"new_fee_bps": 5000},  # > 1000 max
                headers={"X-Admin-Key": "secret123"},
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_set_arbiters_rejects_empty_list(self):
        client = self._client(admin_api_key="secret123", sandbox=True)
        try:
            resp = client.post(
                "/admin/set-arbiters",
                json={"arbiters": []},
                headers={"X-Admin-Key": "secret123"},
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_emergency_freeze_endpoint_reachable(self):
        client = self._client(admin_api_key="secret123", sandbox=True)
        try:
            resp = client.post(
                "/admin/emergency-freeze",
                headers={"X-Admin-Key": "secret123"},
            )
            # Sandbox mode => 409 (no live Casper client), not 404/403 --
            # confirms the route + auth gate are wired correctly.
            assert resp.status_code == 409
        finally:
            app.dependency_overrides.clear()

    def test_set_release_cap_sandbox_mode_rejected(self):
        client = self._client(admin_api_key="secret123", sandbox=True)
        try:
            resp = client.post(
                "/admin/set-release-cap",
                json={"new_cap_motes": 1_000_000_000_000},
                headers={"X-Admin-Key": "secret123"},
            )
            assert resp.status_code == 409
        finally:
            app.dependency_overrides.clear()

    def _client_with_mock_casper(self, admin_api_key="secret123"):
        """Live (non-sandbox) mode with a fake CasperClient so the
        on-chain-submission success path (deploy_hash return) is exercised
        without needing a real testnet connection."""
        from server import admin_api
        from server.config import get_config as admin_get_config

        cfg = Config(sandbox=False, admin_api_key=admin_api_key)

        class _FakeCasper:
            async def configure_fee(self, new_fee_bps):
                return "deadbeef" * 8

            async def set_release_cap(self, new_cap_motes):
                return "cafebabe" * 8

            async def set_arbiters(self, arbiters):
                return "12345678" * 8

            async def emergency_freeze(self):
                return "87654321" * 8

        app.dependency_overrides[get_config] = lambda: cfg
        app.dependency_overrides[admin_get_config] = lambda: cfg
        app.dependency_overrides[admin_api._get_casper] = lambda: _FakeCasper()
        return TestClient(app)

    def test_configure_fee_success(self):
        client = self._client_with_mock_casper()
        try:
            resp = client.post(
                "/admin/configure-fee",
                json={"new_fee_bps": 300},
                headers={"X-Admin-Key": "secret123"},
            )
            assert resp.status_code == 200
            assert resp.json()["deploy_hash"] == "deadbeef" * 8
        finally:
            app.dependency_overrides.clear()

    def test_set_release_cap_success(self):
        client = self._client_with_mock_casper()
        try:
            resp = client.post(
                "/admin/set-release-cap",
                json={"new_cap_motes": 1_000_000_000_000},
                headers={"X-Admin-Key": "secret123"},
            )
            assert resp.status_code == 200
            assert resp.json()["deploy_hash"] == "cafebabe" * 8
        finally:
            app.dependency_overrides.clear()

    def test_set_arbiters_success(self):
        client = self._client_with_mock_casper()
        try:
            resp = client.post(
                "/admin/set-arbiters",
                json={"arbiters": [RECEIVER_HEX] * 5},
                headers={"X-Admin-Key": "secret123"},
            )
            assert resp.status_code == 200
            assert resp.json()["deploy_hash"] == "12345678" * 8
        finally:
            app.dependency_overrides.clear()

    def test_emergency_freeze_success(self):
        client = self._client_with_mock_casper()
        try:
            resp = client.post(
                "/admin/emergency-freeze",
                headers={"X-Admin-Key": "secret123"},
            )
            assert resp.status_code == 200
            assert resp.json()["deploy_hash"] == "87654321" * 8
        finally:
            app.dependency_overrides.clear()

    def test_configure_fee_upstream_failure_returns_502(self):
        from server import admin_api
        from server.config import get_config as admin_get_config

        cfg = Config(sandbox=False, admin_api_key="secret123")

        class _FailingCasper:
            async def configure_fee(self, new_fee_bps):
                raise RuntimeError("rpc timeout")

        app.dependency_overrides[get_config] = lambda: cfg
        app.dependency_overrides[admin_get_config] = lambda: cfg
        app.dependency_overrides[admin_api._get_casper] = lambda: _FailingCasper()
        try:
            client = TestClient(app)
            resp = client.post(
                "/admin/configure-fee",
                json={"new_fee_bps": 300},
                headers={"X-Admin-Key": "secret123"},
            )
            assert resp.status_code == 502
        finally:
            app.dependency_overrides.clear()


class TestComputeHashEndpoint:
    def test_compute_hash(self, client):
        resp = client.post(
            "/compute-hash",
            params={"sender": "s", "receiver": RECEIVER_HEX, "amount": 100, "nonce": "n"},
        )
        assert resp.status_code == 200
        assert "service_hash" in resp.json()
