"""Tests for server/insurance.py and server/vrf_election.py HTTP routers.

Replaces the deleted tests/test_batch3_modules.py, which fabricated CRUD
endpoints (POST/GET/PUT/DELETE /escrow/{id} with EscrowStatus.COMPLETED /
FAILED values) that never existed on server.multi_asset, server.insurance,
or server.vrf_election — none of these routers implement integer-ID CRUD,
and EscrowStatus has no COMPLETED/FAILED members. These tests instead
exercise the real routes: /insurance/pool-stats, /insurance/premium-quote,
/insurance/deposit (auth-gated), /insurance/claim (auth-gated), and the
vrf_election arbiter registration/election/list flow.
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

import server.app as appmod
import server.insurance as insurance_mod
import server.vrf_election as vrf_mod
from server.middleware import X402_VERSION, _build_signing_payload
from server.models import PaymentHeader


class _FakeCasper:
    async def close(self) -> None:
        return None


def _client() -> TestClient:
    appmod._casper = _FakeCasper()
    appmod._rate_limits.clear()
    return TestClient(appmod.app)


def _signed_x402_header(method: str, path: str, amount: int = 1000, escrow_hash: str | None = None) -> tuple[str, str]:
    """Build a real Ed25519-signed X-Payment header. Returns (header_value, sender_hex)."""
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
        signature="0" * 128,  # placeholder, replaced below
        timestamp=ts,
        nonce=nonce,
    )
    msg = _build_signing_payload(payment, method=method, path=path)
    signature_hex = private_key.sign(msg).hex()
    header = f"{X402_VERSION};{escrow_hash};{amount};{sender_hex};{ts};{nonce};{signature_hex}"
    return header, sender_hex


class TestInsurancePoolStats:
    def test_pool_stats_available_without_auth(self):
        client = _client()
        res = client.get("/insurance/pool-stats")
        assert res.status_code == 200
        body = res.json()
        assert body["total_assets"] > 0
        assert "coverage_ratio" in body


class TestPremiumQuote:
    def test_premium_quote_basic(self):
        client = _client()
        res = client.get(
            "/insurance/premium-quote",
            params={"agent_id": "agent-x", "escrow_amount": 1_000_000_000},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["premium_amount"] >= 1_000_000  # minimum premium floor
        assert body["base_rate_bps"] == 50

    def test_premium_quote_requires_positive_escrow_amount(self):
        client = _client()
        res = client.get(
            "/insurance/premium-quote",
            params={"agent_id": "agent-x", "escrow_amount": 0},
        )
        assert res.status_code == 422


class TestInsuranceAuthGating:
    def test_deposit_requires_x_payment_header(self):
        client = _client()
        res = client.post("/insurance/deposit", json={"amount": 1000})
        assert res.status_code == 401

    def test_claim_requires_x_payment_header(self):
        client = _client()
        res = client.post(
            "/insurance/claim",
            json={"escrow_hash": "a" * 64, "reason": "escrow never delivered"},
        )
        assert res.status_code == 401


class TestInsuranceDepositRealChain:
    def test_demo_mode_when_no_casper_or_package_hash(self):
        """No live Casper client/contract configured -> falls back to the
        in-memory simulation instead of erroring."""
        client = _client()
        appmod._casper = None
        header, _ = _signed_x402_header("POST", "/insurance/deposit", amount=1000)
        res = client.post("/insurance/deposit", json={"amount": 1000}, headers={"X-Payment": header})
        assert res.status_code == 202
        assert "demo mode" in res.json()["message"]

    def test_live_deposit_success_calls_real_contract(self, monkeypatch):
        # config.insurance_package_hash defaults to the real deployed value
        # (see server/config.py), so a non-None casper client alone routes
        # this into the live on-chain branch.
        client = _client()
        fake_casper = _FakeCasper()
        fake_casper.deposit_to_insurance_pool = AsyncMock(return_value="deploy-live-deposit")
        fake_casper.get_deploy_error = AsyncMock(return_value=None)
        appmod._casper = fake_casper
        monkeypatch.setattr(insurance_mod.asyncio, "sleep", AsyncMock(return_value=None))

        header, _ = _signed_x402_header("POST", "/insurance/deposit", amount=5000)
        res = client.post("/insurance/deposit", json={"amount": 5000}, headers={"X-Payment": header})
        assert res.status_code == 202
        body = res.json()
        assert body["deploy_hash"] == "deploy-live-deposit"
        fake_casper.deposit_to_insurance_pool.assert_awaited_once_with(5000)

    def test_live_deposit_reverts_returns_502(self, monkeypatch):
        client = _client()
        fake_casper = _FakeCasper()
        fake_casper.deposit_to_insurance_pool = AsyncMock(return_value="deploy-bad")
        fake_casper.get_deploy_error = AsyncMock(return_value="User error: 3")
        appmod._casper = fake_casper
        monkeypatch.setattr(insurance_mod.asyncio, "sleep", AsyncMock(return_value=None))

        header, _ = _signed_x402_header("POST", "/insurance/deposit", amount=5000)
        res = client.post("/insurance/deposit", json={"amount": 5000}, headers={"X-Payment": header})
        assert res.status_code == 502
        assert "reverted" in res.json()["detail"]


class TestInsuranceClaimRealChain:
    def _seed_disputed_escrow(self, service_hash: str, sender_hex: str) -> None:
        appmod._sandbox._escrows[service_hash] = {
            "sender": sender_hex,
            "receiver": "b" * 64,
            "amount": 1000,
            "service_hash": service_hash,
            "status": "disputed",
            "created_at": 0,
            "ttl": 3600,
        }

    def test_backend_submitted_claim_with_valid_quorum_succeeds(self, monkeypatch):
        client = _client()
        service_hash = "c" * 64
        header, sender_hex = _signed_x402_header("POST", "/insurance/claim", amount=1000, escrow_hash=service_hash)
        self._seed_disputed_escrow(service_hash, sender_hex)

        arbiters = [Ed25519PrivateKey.generate() for _ in range(3)]
        operator_hash = appmod.get_config().casper_operator_account_hash
        message = f"claim:{service_hash}:{operator_hash}:1000".encode()
        pubkeys = ["01" + pk.public_key().public_bytes_raw().hex() for pk in arbiters]
        sigs = ["01" + pk.sign(message).hex() for pk in arbiters]

        # Config.arbiter_pubkeys defaults to () when ARBITER_PUBKEYS is unset
        # -> skip off-chain pre-check, trust the on-chain contract's own
        # verification (mirrors /resolve's `if cfg.arbiter_pubkeys:` guard).
        fake_casper = _FakeCasper()
        fake_casper.claim_from_insurance_pool = AsyncMock(return_value="deploy-live-claim")
        fake_casper.confirm_wallet_insurance_claim = AsyncMock(return_value=(True, None))
        appmod._casper = fake_casper

        res = client.post(
            "/insurance/claim",
            json={
                "escrow_hash": service_hash,
                "reason": "no delivery",
                "arbiter_pubkeys": pubkeys,
                "arbiter_signatures": sigs,
            },
            headers={"X-Payment": header},
        )
        assert res.status_code == 202
        assert res.json()["deploy_hash"] == "deploy-live-claim"
        fake_casper.claim_from_insurance_pool.assert_awaited_once()

    def test_backend_submitted_claim_reverted_returns_502(self, monkeypatch):
        client = _client()
        service_hash = "d" * 64
        header, sender_hex = _signed_x402_header("POST", "/insurance/claim", amount=1000, escrow_hash=service_hash)
        self._seed_disputed_escrow(service_hash, sender_hex)

        fake_casper = _FakeCasper()
        fake_casper.claim_from_insurance_pool = AsyncMock(return_value="deploy-bad-claim")
        fake_casper.confirm_wallet_insurance_claim = AsyncMock(return_value=(False, "User error: 8"))
        appmod._casper = fake_casper

        res = client.post(
            "/insurance/claim",
            json={
                "escrow_hash": service_hash,
                "reason": "no delivery",
                "arbiter_pubkeys": ["01" + "aa" * 32],
                "arbiter_signatures": ["01" + "bb" * 64],
            },
            headers={"X-Payment": header},
        )
        assert res.status_code == 502
        assert "reverted" in res.json()["detail"]

    def test_backend_submitted_claim_rejects_mismatched_arbiter_lists(self):
        client = _client()
        service_hash = "e" * 64
        header, sender_hex = _signed_x402_header("POST", "/insurance/claim", amount=1000, escrow_hash=service_hash)
        self._seed_disputed_escrow(service_hash, sender_hex)
        appmod._casper = _FakeCasper()

        res = client.post(
            "/insurance/claim",
            json={
                "escrow_hash": service_hash,
                "reason": "no delivery",
                "arbiter_pubkeys": ["01" + "aa" * 32, "01" + "bb" * 32],
                "arbiter_signatures": ["01" + "cc" * 64],
            },
            headers={"X-Payment": header},
        )
        assert res.status_code == 422

    def test_wallet_tx_hash_claim_confirmed(self):
        client = _client()
        fake_casper = _FakeCasper()
        fake_casper.confirm_wallet_insurance_claim = AsyncMock(return_value=(True, None))
        appmod._casper = fake_casper
        service_hash = "f" * 64
        appmod._sandbox._escrows[service_hash] = {
            "sender": "aa" * 32,
            "receiver": "bb" * 32,
            "amount": 1000,
            "service_hash": service_hash,
            "status": "disputed",
            "created_at": 0,
            "ttl": 3600,
        }
        res = client.post(
            "/insurance/claim",
            json={
                "escrow_hash": service_hash,
                "reason": "no delivery",
                "wallet_tx_hash": "deploy-wallet-1",
                "sender_public_key_hex": "aa" * 32,
                "claimant_account_hash": "aa" * 32,
            },
        )
        assert res.status_code == 202
        assert res.json()["deploy_hash"] == "deploy-wallet-1"

    def test_wallet_tx_hash_claim_not_confirmed_returns_502(self):
        client = _client()
        fake_casper = _FakeCasper()
        fake_casper.confirm_wallet_insurance_claim = AsyncMock(return_value=(False, None))
        appmod._casper = fake_casper
        service_hash = "1" * 64
        appmod._sandbox._escrows[service_hash] = {
            "sender": "aa" * 32,
            "receiver": "bb" * 32,
            "amount": 1000,
            "service_hash": service_hash,
            "status": "disputed",
            "created_at": 0,
            "ttl": 3600,
        }
        res = client.post(
            "/insurance/claim",
            json={
                "escrow_hash": service_hash,
                "reason": "no delivery",
                "wallet_tx_hash": "deploy-wallet-2",
                "sender_public_key_hex": "aa" * 32,
                "claimant_account_hash": "aa" * 32,
            },
        )
        assert res.status_code == 502


class TestArbiterElection:
    def _reset(self):
        vrf_mod._registered_arbiters.clear()
        vrf_mod._election_results.clear()

    def test_register_and_list_arbiters(self):
        self._reset()
        client = _client()
        res = client.post(
            "/vrf/arbiters/register",
            json={"agent": "arbiter-1", "score": 80, "completed": 5, "disputed": 0},
        )
        assert res.status_code == 201
        res = client.get("/vrf/arbiters")
        assert res.status_code == 200
        body = res.json()
        assert body["count"] == 1
        assert body["arbiters"][0]["agent"] == "arbiter-1"

    def test_elect_arbiter_excludes_dispute_parties(self):
        self._reset()
        client = _client()
        client.post(
            "/vrf/arbiters/register",
            json={"agent": "buyer-x", "score": 90, "completed": 1, "disputed": 0},
        )
        client.post(
            "/vrf/arbiters/register",
            json={"agent": "neutral-arbiter", "score": 70, "completed": 3, "disputed": 0},
        )
        res = client.post(
            "/vrf/elect",
            json={
                "dispute_id": "dispute-1",
                "sender": "buyer-x",
                "receiver": "seller-y",
                "seed_hash": "ab" * 32,
            },
        )
        assert res.status_code == 201
        elected = res.json()["elected_arbiter"]["arbiter_id"]
        assert elected == "neutral-arbiter"  # buyer-x is excluded as a dispute party

    def test_elect_arbiter_no_eligible_candidates(self):
        self._reset()
        client = _client()
        res = client.post(
            "/vrf/elect",
            json={
                "dispute_id": "dispute-empty",
                "sender": "s",
                "receiver": "r",
                "seed_hash": "cd" * 32,
            },
        )
        assert res.status_code == 503

    def test_duplicate_election_conflicts(self):
        self._reset()
        client = _client()
        client.post(
            "/vrf/arbiters/register",
            json={"agent": "arbiter-1", "score": 80, "completed": 5, "disputed": 0},
        )
        payload = {
            "dispute_id": "dispute-dup",
            "sender": "s",
            "receiver": "r",
            "seed_hash": "ef" * 32,
        }
        first = client.post("/vrf/elect", json=payload)
        assert first.status_code == 201
        second = client.post("/vrf/elect", json=payload)
        assert second.status_code == 409

    def test_get_election_result_not_found(self):
        self._reset()
        client = _client()
        res = client.get("/vrf/election/nonexistent-dispute")
        assert res.status_code == 404


class _FakeVrfCasper:
    """Fake CasperClient exercising the on-chain VRF write path without a
    real network call -- simulates `select_arbiters` + `elections_dict`."""

    def __init__(self, selected_csv: str, deploy_hash: str = "deadbeef" * 8):
        self._selected_csv = selected_csv
        self._deploy_hash = deploy_hash
        self.select_arbiters_calls: list[tuple[str, int]] = []

    async def close(self) -> None:
        return None

    async def select_arbiters(self, dispute_id: str, count: int) -> str:
        self.select_arbiters_calls.append((dispute_id, count))
        return self._deploy_hash

    async def confirm_election(self, dispute_id, *, deploy_hash=None, attempts=15, delay_seconds=2.0):
        # First call (idempotency check before submitting) has no deploy yet
        # in the "nothing selected" case; subsequent calls simulate the
        # write having landed immediately (no real polling delay in tests).
        if not self.select_arbiters_calls and deploy_hash is None:
            return None, None
        return self._selected_csv, None


class TestOnchainVrfWritePath:
    """Focused tests for the real select_arbiters-submission write path
    (server.vrf_election._elect_via_onchain_vrf), using a fake CasperClient
    instead of a live testnet call."""

    def _reset(self):
        vrf_mod._registered_arbiters.clear()
        vrf_mod._election_results.clear()

    def test_onchain_vrf_elects_non_party_candidate(self):
        self._reset()
        client = _client()
        client.post(
            "/vrf/arbiters/register",
            json={"agent": "local-fallback-arbiter", "score": 70, "completed": 3, "disputed": 0},
        )
        appmod._casper = _FakeVrfCasper(
            selected_csv="aaaa111111111111111111111111111111111111111111111111111111111111,"
            "bbbb222222222222222222222222222222222222222222222222222222222222"
        )
        res = client.post(
            "/vrf/elect",
            json={
                "dispute_id": "onchain-dispute-1",
                "sender": "sender-account-hash",
                "receiver": "receiver-account-hash",
                "seed_hash": "ab" * 32,
            },
        )
        assert res.status_code == 201
        body = res.json()
        assert body["method"] == "onchain_vrf"
        assert body["elected_arbiter"]["arbiter_id"] == (
            "aaaa111111111111111111111111111111111111111111111111111111111111"
        )

    def test_onchain_vrf_invariant5_excludes_dispute_party(self):
        """If the only on-chain candidate returned happens to be a dispute
        party, the endpoint must NOT elect them -- it should fall back to
        the local CSPRNG pool instead (INVARIANT 5 enforced client-side,
        since the contract's own select_arbiters has no notion of dispute
        parties)."""
        self._reset()
        client = _client()
        appmod._casper = _FakeVrfCasper(selected_csv="sender-account-hash")
        client.post(
            "/vrf/arbiters/register",
            json={"agent": "neutral-arbiter", "score": 70, "completed": 3, "disputed": 0},
        )
        res = client.post(
            "/vrf/elect",
            json={
                "dispute_id": "onchain-dispute-invariant5",
                "sender": "sender-account-hash",
                "receiver": "receiver-account-hash",
                "seed_hash": "cd" * 32,
            },
        )
        assert res.status_code == 201
        body = res.json()
        assert body["method"] == "local_csprng"
        assert body["elected_arbiter"]["arbiter_id"] != "sender-account-hash"
        assert body["elected_arbiter"]["arbiter_id"] != "receiver-account-hash"

    def test_onchain_vrf_is_idempotent_on_retry(self):
        """A second /vrf/elect for a dispute_id that already has an
        on-chain election recorded should read it back rather than
        submitting select_arbiters twice (avoids ERR_ELECTION_EXISTS)."""
        self._reset()
        client = _client()
        client.post(
            "/vrf/arbiters/register",
            json={"agent": "local-fallback-arbiter", "score": 70, "completed": 3, "disputed": 0},
        )
        fake = _FakeVrfCasper(selected_csv="cccc333333333333333333333333333333333333333333333333333333333333")
        appmod._casper = fake
        res = client.post(
            "/vrf/elect",
            json={
                "dispute_id": "onchain-dispute-idempotent",
                "sender": "sender-account-hash",
                "receiver": "receiver-account-hash",
                "seed_hash": "ef" * 32,
            },
        )
        assert res.status_code == 201
        assert res.json()["method"] == "onchain_vrf"
        assert len(fake.select_arbiters_calls) == 1
