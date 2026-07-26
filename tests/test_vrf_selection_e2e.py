"""End-to-end contract test for the VRF arbiter-selection flow.

Covers the full path a real dispute exercises when the AI arbitrator abstains
or returns a low-confidence 'escalate', wiring three previously-independent
layers together through the public SDK surface:

    sdk.EscrowClient.elect_arbiter          (VRF election over registered arbiters)
      → server.vrf_election.elect_arbiter    (local CSPRNG or on-chain VRF)
      → escalation from /arbitration/analyze (auto-populate panel_election)
      → panel arbiter signs release vote     (sdk.arbiter_signing.sign_arbiter_vote)
      → sdk.EscrowClient.resolve            (with elected arbiter's signed vote)
      → POST /resolve
      → server.arbiter_crypto.count_valid_votes
      → FSM escrow.status: disputed → resolved
      → _broadcast_event: escrow_resolved + arbitration_complete (A5 alias)

Each layer already has direct unit coverage (elect endpoint / election helpers
in `tests/test_insurance_and_arbiter_routes.py`, escalation branching in
`tests/test_arbitration_escalation.py`, signing primitives in
`tests/test_arbiter_signing_e2e.py`), but none tested them wired together
through the SDK.  In particular, the *identity binding* — that an arbiter
elected by VRF (by Casper account_hash) can, when their Ed25519 pubkey is on
the allowlist, produce a signed vote that resolves the escrow — was not
exercised anywhere.  This module locks that end-to-end contract.

INVARIANT 5 (dispute-party exclusion), idempotent re-election, and the
abstain→panel escalation path are also exercised through the SDK, filling
the SDK-driven gap next to the raw-HTTP coverage that already existed.
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from fastapi.testclient import TestClient

from sdk.arbiter_signing import sign_arbiter_vote
from sdk.client import EscrowClient
from server import app as app_module
from server import vrf_election as vrf_mod
from server.app import app, get_casper, get_config, get_sandbox
from server.config import Config
from server.sandbox import SandboxStore

RECEIVER_HEX = "cd" * 32


# ─── PEM helpers ────────────────────────────────────────────────────────────


def _write_pem(private_key: Ed25519PrivateKey) -> str:
    pem = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    f = tempfile.NamedTemporaryFile(mode="wb", suffix=".pem", delete=False)
    f.write(pem)
    f.close()
    return f.name


def _make_arbiter(idx: int) -> tuple[str, str, Ed25519PrivateKey]:
    """Generate a fresh arbiter identity: returns (pem_path, pubkey_hex, sk).

    pubkey_hex is the tag-prefixed hex used both in `cfg.arbiter_pubkeys`
    and in `/resolve` request payloads. `sk` is retained so tests can
    directly assert who signed what if needed (unused by default).
    """
    sk = Ed25519PrivateKey.generate()
    pem_path = _write_pem(sk)
    pubkey_hex = "01" + sk.public_key().public_bytes_raw().hex()
    return pem_path, pubkey_hex, sk


def _sdk_with_asgi(base_url: str = "http://ae402.test") -> tuple[EscrowClient, httpx.AsyncClient]:
    """Build an EscrowClient that talks to the in-process FastAPI app via
    ASGITransport (no TCP), so the test exercises the exact code path a
    real integration takes.

    EscrowClient.__init__ owns its own httpx.AsyncClient and does not
    expose it as a constructor parameter, so we swap `._http` after init.
    """
    transport = httpx.ASGITransport(app=app)
    http = httpx.AsyncClient(transport=transport, base_url=base_url, timeout=10.0)
    sdk = EscrowClient(base_url=base_url, sandbox=True)
    sdk._http = http  # noqa: SLF001 — deliberate transport injection
    return sdk, http


# ─── App fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def sandbox() -> SandboxStore:
    return SandboxStore()


@pytest.fixture
def cfg_factory():
    """Factory that yields a Config seeded with the given arbiter pubkey
    allowlist.  Threshold is set to 1 so a single elected arbiter's vote
    is enough to resolve.
    """

    def _make(arbiter_pubkeys: tuple[str, ...]) -> Config:
        return Config(
            sandbox=True,
            arbiter_pubkeys=arbiter_pubkeys,
            arbiter_threshold=1,
        )

    return _make


@pytest.fixture
def client_factory(sandbox, cfg_factory):
    """Wire dependency overrides so the app uses the same sandbox and
    config instances the test manipulates.  Also clears the VRF election
    module state so each test starts from a clean slate."""

    def _make(arbiter_pubkeys: tuple[str, ...]) -> TestClient:
        cfg = cfg_factory(arbiter_pubkeys)
        app.dependency_overrides[get_config] = lambda: cfg
        app.dependency_overrides[get_sandbox] = lambda: sandbox
        app.dependency_overrides[get_casper] = lambda: None
        vrf_mod._registered_arbiters.clear()
        vrf_mod._election_results.clear()
        # also reset the module-level singletons the app uses
        app_module._sandbox = sandbox
        app_module._casper = None
        return TestClient(app)

    yield _make

    app.dependency_overrides.clear()
    vrf_mod._registered_arbiters.clear()
    vrf_mod._election_results.clear()


def _seed_disputed_escrow(store: SandboxStore, service_hash: str, sender_hex: str) -> None:
    """Directly seed the sandbox with a disputed escrow.  Bypasses the
    normal create→dispute state-machine walk because this test focuses on
    the VRF → resolve leg, not escrow creation."""
    store._escrows[service_hash] = {
        "sender": sender_hex,
        "receiver": RECEIVER_HEX,
        "amount": 1000,
        "service_hash": service_hash,
        "status": "disputed",
        "created_at": 0,
        "ttl": 3600,
    }


# ─── Broadcast capture ─────────────────────────────────────────────────────


class _BroadcastSpy:
    """Subscribes to app_module._event_subscribers and records every
    event dispatched during a test.  Cleaned up via `close`."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.events: list[dict[str, Any]] = []
        app_module._event_subscribers.append(self.queue)

    async def drain(self, expected_min: int = 1, timeout: float = 1.0) -> None:
        loop_deadline = asyncio.get_event_loop().time() + timeout
        while len(self.events) < expected_min:
            remaining = loop_deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return
            try:
                evt = await asyncio.wait_for(self.queue.get(), timeout=remaining)
                self.events.append(evt)
            except asyncio.TimeoutError:
                return

    def close(self) -> None:
        try:
            app_module._event_subscribers.remove(self.queue)
        except ValueError:
            pass


# ═══════════════════════════════════════════════════════════════════════════
#  Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestVrfSelectionE2E:
    """Full SDK-driven flow: VRF election → arbiter signs → /resolve."""

    def test_elected_arbiter_can_sign_and_resolve_via_sdk(self, client_factory, sandbox):
        """The identity-binding invariant: an arbiter elected by VRF
        (matched by account_hash) whose Ed25519 pubkey is on the allowlist
        can, without any additional wiring, produce a signed vote that
        `/resolve` accepts and drives the FSM disputed → resolved.

        This is the *only* test that exercises both identity domains
        (Casper account_hash for election, Ed25519 pubkey for signing)
        in the same flow.  Everything else covers one or the other.
        """
        pem_path, pubkey_hex, _sk = _make_arbiter(0)
        # In real deployments the account_hash and pubkey come from the
        # same wallet.  We fake that binding here: register the arbiter
        # under an id that is stable and unique, and put its pubkey on
        # the allowlist.  The point is that once VRF picks that id, the
        # server accepts a vote signed by the same pubkey — no extra
        # coordination needed at the /resolve layer.
        arbiter_account_hash = "arbiter-" + "0" * 56  # 64 chars total
        client = client_factory((pubkey_hex,))

        # Step 1: register arbiter in the VRF pool via SDK-style HTTP.
        # (elect_arbiter's underlying router calls _registered_arbiters
        # directly, so we register through the public endpoint.)
        reg = client.post(
            "/vrf/arbiters/register",
            json={
                "agent": arbiter_account_hash,
                "score": 90,
                "completed": 5,
                "disputed": 0,
            },
        )
        assert reg.status_code == 201, reg.text

        # Step 2: seed a disputed escrow so /resolve has something to act on.
        sender_hex = "ab" * 32
        service_hash = "e2e" + "0" * 61
        _seed_disputed_escrow(sandbox, service_hash, sender_hex)

        # Step 3: run VRF election through the SDK.
        async def _run() -> dict[str, Any]:
            sdk, http = _sdk_with_asgi()
            spy = _BroadcastSpy()
            try:
                election = await sdk.elect_arbiter(
                    dispute_id=service_hash,
                    sender=sender_hex,
                    receiver=RECEIVER_HEX,
                    seed_hash="ff" * 32,
                )
                assert election["method"] in ("local_csprng", "onchain_vrf"), election
                elected_id = election["elected_arbiter"]["arbiter_id"]
                assert elected_id == arbiter_account_hash, (
                    f"VRF must pick the only registered arbiter, got {elected_id}"
                )

                # Step 4: elected arbiter signs the release vote off-chain.
                # sign_arbiter_vote returns (pubkey_hex, signature_hex) tuple.
                # `in_favor_of` matches the /resolve enum: sender|receiver.
                signed_pubkey, signed_sig = sign_arbiter_vote(
                    pem_path, service_hash, "receiver"
                )
                assert signed_pubkey == pubkey_hex

                # Step 5: SDK-driven /resolve with the signed vote.
                resolve = await sdk.resolve(
                    service_hash=service_hash,
                    in_favor_of="receiver",
                    arbiter_pubkeys=[signed_pubkey],
                    arbiter_signatures=[signed_sig],
                )
                await spy.drain(expected_min=2, timeout=1.5)
                return {"election": election, "resolve": resolve, "events": spy.events}
            finally:
                spy.close()
                await http.aclose()

        result = asyncio.run(_run())

        # FSM transition landed
        assert sandbox._escrows[service_hash]["status"] == "resolved"

        # Broadcast: A5 alias contract — both events fire on /resolve
        event_types = {e["type"] for e in result["events"]}
        assert "escrow_resolved" in event_types, event_types
        assert "arbitration_complete" in event_types, event_types

    def test_dispute_party_never_elected_via_sdk(self, client_factory, sandbox):
        """INVARIANT 5: even if the dispute sender is the only registered
        arbiter, the election must fail with a 4xx (no eligible arbiter)
        rather than pick a dispute party.

        This is the SDK-driven counterpart to the raw-HTTP test in
        `test_insurance_and_arbiter_routes.py::test_elect_arbiter_excludes_dispute_parties`.
        Duplicating it here catches drift specifically in the SDK path
        (e.g. if `sdk.elect_arbiter` ever added client-side filtering
        that hid a server violation).
        """
        pem_path, pubkey_hex, _sk = _make_arbiter(0)
        client = client_factory((pubkey_hex,))
        sender_hex = "ab" * 32

        # Register only the sender itself as arbiter — nobody else eligible.
        reg = client.post(
            "/vrf/arbiters/register",
            json={"agent": sender_hex, "score": 90, "completed": 5, "disputed": 0},
        )
        assert reg.status_code == 201

        async def _run() -> httpx.Response:
            sdk, http = _sdk_with_asgi()
            try:
                # httpx.HTTPStatusError is raised by resp.raise_for_status()
                # inside sdk.elect_arbiter.  Catch it and return the resp.
                with pytest.raises(httpx.HTTPStatusError) as exc_info:
                    await sdk.elect_arbiter(
                        dispute_id="dispute-only-party-registered",
                        sender=sender_hex,
                        receiver=RECEIVER_HEX,
                        seed_hash="aa" * 32,
                    )
                return exc_info.value.response
            finally:
                await http.aclose()

        resp = asyncio.run(_run())
        # /vrf/elect signals "no eligible arbiters" as 503 (Service Unavailable)
        # -- the pool exists but everyone in it is a dispute party. Any non-2xx
        # would satisfy INVARIANT 5; we lock the current server behaviour.
        assert resp.status_code in (404, 422, 503), (
            f"Election with dispute party as only candidate must 4xx/503, got {resp.status_code}: {resp.text}"
        )

    def test_reelection_is_idempotent_via_sdk(self, client_factory, sandbox):
        """Second /vrf/elect for the same dispute_id must NOT allocate a
        fresh election — it should either 409 or return the prior result.
        Exercised via SDK to lock the surface a real integration hits.
        """
        pem_path, pubkey_hex, _sk = _make_arbiter(0)
        client = client_factory((pubkey_hex,))
        sender_hex = "ab" * 32

        arbiter_id = "arbiter-idempotent-" + "0" * 46  # 64 chars
        client.post(
            "/vrf/arbiters/register",
            json={"agent": arbiter_id, "score": 80, "completed": 4, "disputed": 0},
        )

        async def _run() -> tuple[dict, Any]:
            sdk, http = _sdk_with_asgi()
            try:
                first = await sdk.elect_arbiter(
                    dispute_id="dispute-idem",
                    sender=sender_hex,
                    receiver=RECEIVER_HEX,
                    seed_hash="12" * 32,
                )
                # Second attempt — sdk.elect_arbiter raises on non-2xx via
                # raise_for_status.  Capture the 409 vs. success behaviour.
                try:
                    second = await sdk.elect_arbiter(
                        dispute_id="dispute-idem",
                        sender=sender_hex,
                        receiver=RECEIVER_HEX,
                        seed_hash="12" * 32,
                    )
                    return first, ("success", second)
                except httpx.HTTPStatusError as exc:
                    return first, ("conflict", exc.response.status_code)
            finally:
                await http.aclose()

        first, second = asyncio.run(_run())
        kind, payload = second
        # Two valid behaviours: idempotent read-back (200 with same id) OR
        # explicit conflict (409).  Both preserve the invariant "one
        # election per dispute_id".
        if kind == "success":
            assert payload["elected_arbiter"]["arbiter_id"] == first["elected_arbiter"]["arbiter_id"]
        else:
            assert payload == 409, f"expected 200 or 409, got {payload}"

    def test_escalation_from_abstain_verdict_triggers_vrf_via_analyze(
        self, client_factory, sandbox
    ):
        """POST /arbitration/analyze with sender_account+receiver_account,
        when the LLM (mocked) returns 'abstain', must:
          1. mark escalated_to_panel = True
          2. attach panel_election with an arbiter picked by VRF
          3. that arbiter must NOT be a dispute party (INVARIANT 5)

        This wires the ai_arbitration → vrf_election escalation edge into
        one assertion instead of relying on the caller to compose them
        (which is what real /arbitration/analyze callers do — they trust
        the escalation to happen transparently).
        """
        pem_path, pubkey_hex, _sk = _make_arbiter(0)
        client = client_factory((pubkey_hex,))
        sender_hex = "ab" * 32

        # Register a fresh, non-party arbiter.
        neutral_arbiter_id = "neutral-arb-" + "0" * 52  # 64 chars
        reg = client.post(
            "/vrf/arbiters/register",
            json={
                "agent": neutral_arbiter_id,
                "score": 85,
                "completed": 4,
                "disputed": 0,
            },
        )
        assert reg.status_code == 201

        # Mock every LLM provider to return None so the heuristic path
        # is forced.  Then force the heuristic to return 'abstain' by
        # patching it directly — this is the cleanest way to trigger
        # the escalation branch deterministically.
        from server import ai_arbitration as arb_mod

        async def _fake_none(_prompt: str) -> None:
            return None

        abstain_result = arb_mod.ArbitrationRecommendation(
            dispute_id="dispute-abstain",
            recommendation="abstain",
            confidence=0.5,
            reasoning="conflict of interest",
            risk_factors=[],
            suggested_split_pct=50.0,
            analysis_hash="ab" * 32,
            provider="mock",
            evidence_root="",
        )

        with (
            patch.object(arb_mod, "_try_groq", _fake_none),
            patch.object(arb_mod, "_try_nvidia", _fake_none),
            patch.object(arb_mod, "_try_zai", _fake_none),
            patch.object(arb_mod, "_try_openrouter", _fake_none),
            patch.object(
                arb_mod._heuristic,
                "analyze",
                lambda *a, **kw: {
                    "recommendation": "abstain",
                    "confidence": 0.5,
                    "reasoning": "conflict",
                    "risk_factors": [],
                    "suggested_split_pct": 50.0,
                    "_provider": "heuristic",
                },
            ),
        ):
            res = client.post(
                "/arbitration/analyze",
                json={
                    "dispute_id": "dispute-abstain",
                    "sender_evidence": [
                        {
                            "escrow_id": "dispute-abstain",
                            "claimant": sender_hex,
                            "description": "sender view of the dispute",
                            "content_hash": "aa" * 32,
                            "evidence_type": "text",
                            "timestamp": 1_700_000_000,
                        }
                    ],
                    "receiver_evidence": [
                        {
                            "escrow_id": "dispute-abstain",
                            "claimant": RECEIVER_HEX,
                            "description": "receiver view of the dispute",
                            "content_hash": "bb" * 32,
                            "evidence_type": "text",
                            "timestamp": 1_700_000_001,
                        }
                    ],
                    "escrow_amount": 1000,
                    "sender_account": sender_hex,
                    "receiver_account": RECEIVER_HEX,
                },
            )

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["recommendation"] == "abstain"
        assert body["escalated_to_panel"] is True, (
            f"abstain verdict with party accounts must escalate; got {body}"
        )
        assert body["panel_election"] is not None
        picked = body["panel_election"]["elected_arbiter"]["arbiter_id"]
        # INVARIANT 5 through the escalation edge — critical because the
        # /arbitration/analyze layer builds the ElectArbiterRequest itself
        # (not the caller), so any bug there would silently violate.
        assert picked != sender_hex
        assert picked != RECEIVER_HEX
        assert picked == neutral_arbiter_id

    def test_missing_party_accounts_records_reason_not_escalation(self, client_factory):
        """If the caller does NOT provide sender_account+receiver_account,
        the abstain verdict must be returned with escalation_reason set
        (`missing_party_accounts:...`) and escalated_to_panel = False.
        Guards against a silent regression where the escalation code path
        tries to elect an arbiter with empty party fields (which would
        either 422 in vrf_election or, worse, elect a party by identity
        collision with empty strings).
        """
        pem_path, pubkey_hex, _sk = _make_arbiter(0)
        client = client_factory((pubkey_hex,))
        sender_hex = "ab" * 32

        from server import ai_arbitration as arb_mod

        async def _fake_none(_prompt: str) -> None:
            return None

        with (
            patch.object(arb_mod, "_try_groq", _fake_none),
            patch.object(arb_mod, "_try_nvidia", _fake_none),
            patch.object(arb_mod, "_try_zai", _fake_none),
            patch.object(arb_mod, "_try_openrouter", _fake_none),
            patch.object(
                arb_mod._heuristic,
                "analyze",
                lambda *a, **kw: {
                    "recommendation": "abstain",
                    "confidence": 0.5,
                    "reasoning": "conflict",
                    "risk_factors": [],
                    "suggested_split_pct": 50.0,
                    "_provider": "heuristic",
                },
            ),
        ):
            res = client.post(
                "/arbitration/analyze",
                json={
                    "dispute_id": "dispute-abstain-no-parties",
                    "sender_evidence": [
                        {
                            "escrow_id": "dispute-abstain-no-parties",
                            "claimant": sender_hex,
                            "description": "sender view",
                            "content_hash": "aa" * 32,
                            "evidence_type": "text",
                            "timestamp": 1_700_000_000,
                        }
                    ],
                    "receiver_evidence": [
                        {
                            "escrow_id": "dispute-abstain-no-parties",
                            "claimant": RECEIVER_HEX,
                            "description": "receiver view",
                            "content_hash": "bb" * 32,
                            "evidence_type": "text",
                            "timestamp": 1_700_000_001,
                        }
                    ],
                    "escrow_amount": 1000,
                    # no sender_account/receiver_account
                },
            )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["recommendation"] == "abstain"
        assert body["escalated_to_panel"] is False
        assert (body.get("escalation_reason") or "").startswith("missing_party_accounts"), body
