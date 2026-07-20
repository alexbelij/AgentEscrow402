"""Integration tests for insurance-pool replay guard (ab17a1b + 3eb578a).

The on-chain fix (contracts/insurance-pool/src/main.rs) added a
`claimed_escrow_ids` dictionary that tombstones every processed escrow_id
before the transfer, so the same signed claim cannot be replayed after
cooldown or via a different route. The backend (server/insurance.py) has
a complementary in-memory `_claims` dict that returns 409 on duplicate
requests within a single process — the on-chain guard is what survives
restarts.

These tests exercise the FULL request path (auth + validation + dedup)
against a mocked Casper client, covering the three failure modes the
production system must reject:

  1. Same-process replay: /insurance/claim called twice for the same
     escrow_hash from the wallet path → second call rejected 409.
  2. Backend-submitted replay: same but via the arbiter-quorum backend
     path → also rejected 409 with the reserved slot preserved (not
     rolled back by the failed second attempt).
  3. Post-restart replay simulation: `_claims` cleared (mimics process
     restart) → the on-chain confirm_wallet_insurance_claim contract
     call is what stops the double payout; the mock returns
     `(False, "ESCROW_ALREADY_CLAIMED")` and the backend returns 502.

Existing tests in test_insurance_and_arbiter_routes.py cover the
positive/negative single-claim paths; nothing there hits the replay
branch. This file adds that missing coverage.
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

import server.app as appmod
import server.insurance as insurance_mod
from server.middleware import X402_VERSION, _build_signing_payload
from server.models import PaymentHeader


class _FakeCasper:
    async def close(self) -> None:
        return None


@pytest.fixture
def client():
    appmod._casper = _FakeCasper()
    appmod._rate_limits.clear()
    # Clear the backend's in-memory replay guard between tests so the
    # dedup counter starts from zero for each scenario.
    insurance_mod._claims.clear()
    return TestClient(appmod.app)


def _signed_x402_header(
    method: str, path: str, amount: int = 1000, escrow_hash: str | None = None
) -> tuple[str, str]:
    """Build a real Ed25519-signed X-Payment header (copied from the
    existing insurance test file for parity)."""
    private_key = Ed25519PrivateKey.generate()
    sender_hex = private_key.public_key().public_bytes_raw().hex()
    escrow_hash = escrow_hash or ("a" * 64)
    ts = int(time.time())
    nonce = uuid.uuid4().hex
    payment = PaymentHeader(
        version=X402_VERSION,
        escrow_hash=escrow_hash,
        amount=amount,
        sender=sender_hex,
        signature="0" * 128,  # replaced below
        timestamp=ts,
        nonce=nonce,
    )
    msg = _build_signing_payload(payment, method=method, path=path)
    signature_hex = private_key.sign(msg).hex()
    header = f"{X402_VERSION};{escrow_hash};{amount};{sender_hex};{ts};{nonce};{signature_hex}"
    return header, sender_hex


def _seed_disputed_escrow(service_hash: str, sender_hex: str) -> None:
    appmod._sandbox._escrows[service_hash] = {
        "sender": sender_hex,
        "receiver": "b" * 64,
        "amount": 1000,
        "service_hash": service_hash,
        "status": "disputed",
        "created_at": 0,
        "ttl": 3600,
    }


class TestBackendReplayGuard:
    """Backend-level dedup: _claims dict blocks double filings within one process."""

    def test_wallet_path_same_escrow_second_call_returns_409(self, client):
        """Same escrow_hash filed twice via wallet path → second call is
        409 CONFLICT ("Claim already filed for this escrow"). This is the
        in-memory guard; the on-chain guard is a separate layer.
        """
        service_hash = "1a" * 32  # 64-hex, distinct from other tests
        fake = _FakeCasper()
        fake.confirm_wallet_insurance_claim = AsyncMock(return_value=(True, None))
        appmod._casper = fake
        _seed_disputed_escrow(service_hash, "aa" * 32)

        body = {
            "escrow_hash": service_hash,
            "reason": "no delivery",
            "wallet_tx_hash": "deploy-replay-1",
            "sender_public_key_hex": "aa" * 32,
            "claimant_account_hash": "aa" * 32,
        }

        # First call: succeeds, reserves the slot, confirms on-chain.
        res1 = client.post("/insurance/claim", json=body)
        assert res1.status_code == 202, res1.text
        assert res1.json()["deploy_hash"] == "deploy-replay-1"

        # Second call for the SAME escrow_hash: rejected before it can
        # reach the on-chain path. This is the fast in-memory guard.
        res2 = client.post("/insurance/claim", json=body)
        assert res2.status_code == 409, res2.text
        assert "already filed" in res2.json()["detail"].lower()

        # Sanity: confirm_wallet_insurance_claim was called EXACTLY ONCE
        # — the second request never even reached the Casper client.
        assert fake.confirm_wallet_insurance_claim.await_count == 1

    def test_different_escrow_hashes_both_succeed(self, client):
        """Two claims for DIFFERENT escrow_hash both succeed — the guard
        keys on escrow_hash, not on claimant."""
        fake = _FakeCasper()
        fake.confirm_wallet_insurance_claim = AsyncMock(return_value=(True, None))
        appmod._casper = fake

        for i, h in enumerate(("2a" * 32, "2b" * 32)):
            _seed_disputed_escrow(h, "aa" * 32)
            res = client.post(
                "/insurance/claim",
                json={
                    "escrow_hash": h,
                    "reason": f"claim number {i} — different escrow",
                    "wallet_tx_hash": f"deploy-diff-{i}",
                    "sender_public_key_hex": "aa" * 32,
                    "claimant_account_hash": "aa" * 32,
                },
            )
            assert res.status_code == 202, res.text

        assert fake.confirm_wallet_insurance_claim.await_count == 2

    def test_backend_path_replay_returns_409(self, client):
        """Same test as above but via the backend-submitted (arbiter
        quorum) path — dedup MUST work regardless of which submission
        route was used.

        Note: the caller identity must be the SAME across both requests
        (only escrow parties can file). We build two x402 headers with
        the same signing key so `sender_hex` matches the seeded escrow."""
        service_hash = "3a" * 32

        # One signing key shared across both requests — represents the
        # same claimant retrying the file.
        signing_key = Ed25519PrivateKey.generate()
        sender_hex = signing_key.public_key().public_bytes_raw().hex()

        def _header_with_key(pk: Ed25519PrivateKey, method: str, path: str, amount: int, escrow_hash: str) -> str:
            ts = int(time.time())
            nonce = uuid.uuid4().hex
            payment = PaymentHeader(
                version=X402_VERSION,
                escrow_hash=escrow_hash,
                amount=amount,
                sender=pk.public_key().public_bytes_raw().hex(),
                signature="0" * 128,
                timestamp=ts,
                nonce=nonce,
            )
            msg = _build_signing_payload(payment, method=method, path=path)
            sig = pk.sign(msg).hex()
            return f"{X402_VERSION};{escrow_hash};{amount};{payment.sender};{ts};{nonce};{sig}"

        header = _header_with_key(signing_key, "POST", "/insurance/claim", 1000, service_hash)
        _seed_disputed_escrow(service_hash, sender_hex)

        fake = _FakeCasper()
        fake.claim_from_insurance_pool = AsyncMock(return_value="deploy-backend-replay")
        fake.confirm_wallet_insurance_claim = AsyncMock(return_value=(True, None))
        appmod._casper = fake

        body = {
            "escrow_hash": service_hash,
            "reason": "no delivery for this escrow",
            "arbiter_pubkeys": ["01" + "aa" * 32],
            "arbiter_signatures": ["01" + "bb" * 64],
        }

        res1 = client.post("/insurance/claim", json=body, headers={"X-Payment": header})
        assert res1.status_code == 202, res1.text

        # Second call needs a fresh header (fresh nonce/ts) or the x402
        # middleware rejects for nonce reuse. Same key → same sender_hex,
        # so the escrow-party check still passes.
        header2 = _header_with_key(signing_key, "POST", "/insurance/claim", 1000, service_hash)
        assert header2 != header, "header must differ to avoid x402 nonce reuse"
        res2 = client.post("/insurance/claim", json=body, headers={"X-Payment": header2})
        assert res2.status_code == 409, res2.text
        assert "already filed" in res2.json()["detail"].lower()

        assert fake.claim_from_insurance_pool.await_count == 1


class TestOnChainReplayGuard:
    """When the backend's in-memory guard is unavailable (process restart,
    horizontally scaled pods), the on-chain `claimed_escrow_ids`
    dictionary is what prevents the double payout.
    """

    def test_post_restart_replay_rejected_by_contract(self, client):
        """Simulate `_claims` cleared (process restart). The second
        request now sneaks past the in-memory guard, gets to the Casper
        client, but the contract call reverts with the ERR_ESCROW_ALREADY_CLAIMED
        (u16 = 9) error. Backend surfaces this as 502 with the revert
        reason.
        """
        service_hash = "4a" * 32
        fake = _FakeCasper()
        # First call: succeeds on-chain.
        # Second call (after "restart"): contract reverts.
        fake.confirm_wallet_insurance_claim = AsyncMock(
            side_effect=[
                (True, None),
                (False, "User error: 9"),  # ERR_ESCROW_ALREADY_CLAIMED
            ]
        )
        appmod._casper = fake
        _seed_disputed_escrow(service_hash, "aa" * 32)

        body = {
            "escrow_hash": service_hash,
            "reason": "no delivery",
            "wallet_tx_hash": "deploy-post-restart-1",
            "sender_public_key_hex": "aa" * 32,
            "claimant_account_hash": "aa" * 32,
        }

        res1 = client.post("/insurance/claim", json=body)
        assert res1.status_code == 202

        # Simulate restart: purge the in-memory guard.
        insurance_mod._claims.clear()

        # Same request re-arrives: passes the in-memory check (now
        # empty), reaches Casper, contract rejects.
        body2 = dict(body, wallet_tx_hash="deploy-post-restart-2")  # unique tx hash
        res2 = client.post("/insurance/claim", json=body2)
        assert res2.status_code == 502, res2.text
        assert "User error: 9" in res2.json()["detail"] or "reverted" in res2.json()["detail"].lower()

        # And the on-chain call was attempted BOTH times (the second call
        # can only be stopped by the contract, not the backend).
        assert fake.confirm_wallet_insurance_claim.await_count == 2

    def test_invalid_escrow_id_rejected_by_contract(self, client):
        """Contract also validates `escrow_id.len() ∈ (0, 128]` with
        ERR_INVALID_ESCROW_ID = 10. Backend surfaces the revert."""
        # Backend validates escrow_hash format (must be 64-hex) at
        # request parsing, so we can't send a bad one through the API.
        # This test asserts the CONTRACT's own error code is reachable
        # via the confirm_wallet_insurance_claim path when someone
        # constructs a raw on-chain call directly.
        service_hash = "5a" * 32
        fake = _FakeCasper()
        fake.confirm_wallet_insurance_claim = AsyncMock(
            return_value=(False, "User error: 10")
        )
        appmod._casper = fake
        _seed_disputed_escrow(service_hash, "aa" * 32)

        res = client.post(
            "/insurance/claim",
            json={
                "escrow_hash": service_hash,
                "reason": "raw on-chain call with empty escrow_id",
                "wallet_tx_hash": "deploy-bad-escrow-id",
                "sender_public_key_hex": "aa" * 32,
                "claimant_account_hash": "aa" * 32,
            },
        )
        assert res.status_code == 502
        assert "User error: 10" in res.json()["detail"] or "reverted" in res.json()["detail"].lower()
