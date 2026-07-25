"""End-to-end contract test for arbiter-signing driven dispute resolution.

Covers the full path a real arbiter integration exercises:

    write PKCS8 Ed25519 PEM  →  sdk.arbiter_signing.sign_arbiter_vote(pem, sh, verdict)
                             →  sdk.client.AgentEscrow402Client.resolve(sh, verdict, pubkeys, sigs)
                             →  POST /resolve
                             →  server.arbiter_crypto.count_valid_votes (fast-fail path)
                             →  FSM escrow.status: disputed → resolved
                             →  _broadcast_event: escrow_resolved AND arbitration_complete (A5 alias)

The individual layers already have unit coverage
(`tests/test_arbiter_crypto.py`, the crypto matrix in
`tests/test_api.py::TestResolveEndpoint`, and `tests/test_sdk_client.py`
for the signing primitives), but no test wired them together via the
public SDK-facing surface. That gap meant a subtle drift in any single
layer — canonical message format, tag-prefix hex, HTTP payload shape,
broadcast alias — could ship green without failing tests. This module
locks the contract end-to-end.
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from typing import Any

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
from server.app import app, get_casper, get_config, get_sandbox
from server.config import Config
from server.sandbox import SandboxStore

RECEIVER_HEX = "ab" * 32


def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


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


def _make_arbiter_panel(n: int) -> tuple[list[str], tuple[str, ...]]:
    """Generate `n` throwaway arbiters, materialize their PKCS8 PEMs on disk,
    return (list of pem paths, tuple of tag-prefixed hex pubkeys).

    Both are ordered the same way, so `pems[i]` corresponds to `pubkeys[i]`.
    """
    pems: list[str] = []
    pubkeys_list: list[str] = []
    for _ in range(n):
        sk = Ed25519PrivateKey.generate()
        pems.append(_write_pem(sk))
        pubkeys_list.append("01" + sk.public_key().public_bytes_raw().hex())
    return pems, tuple(pubkeys_list)


def _sdk_with_asgi(base_url: str = "http://ae402.test") -> tuple[EscrowClient, httpx.AsyncClient]:
    """Build an `EscrowClient` whose underlying `httpx.AsyncClient` talks
    to the in-process FastAPI app via `httpx.ASGITransport`.

    `EscrowClient.__init__` owns its own `httpx.AsyncClient` and does not
    expose it as a constructor parameter, so we swap `._http` after init.
    Both are returned so the caller can `await http.aclose()` for a clean
    shutdown (aclose'ing via `client.close()` also works — kept explicit
    for readability).

    Rationale for going through the SDK object rather than posting to
    `TestClient` directly: this is the exact code path a real arbiter
    integration takes (`await sdk.resolve(...)`), so the test surfaces
    any drift in request shape, header handling, or response parsing
    that a raw HTTP call would miss.
    """
    transport = httpx.ASGITransport(app=app)
    http = httpx.AsyncClient(transport=transport, base_url=base_url, timeout=10.0)
    sdk = EscrowClient(base_url=base_url, sandbox=True)
    sdk._http = http  # noqa: SLF001 — deliberate transport injection
    return sdk, http


@pytest.fixture
def sandbox_store() -> SandboxStore:
    return SandboxStore()


@pytest.fixture
def five_arbiter_panel_cfg(sandbox_store):
    """Wire a 5-arbiter, threshold-3 sandbox `Config` into the app, materialize
    5 PKCS8 PEMs on disk, and yield everything a test needs to sign +
    submit a real vote batch."""
    pems, pubkeys = _make_arbiter_panel(5)
    cfg = Config(sandbox=True, arbiter_pubkeys=pubkeys, arbiter_threshold=3)
    app.dependency_overrides[get_config] = lambda: cfg
    app.dependency_overrides[get_sandbox] = lambda: sandbox_store
    app.dependency_overrides[get_casper] = lambda: None
    try:
        yield {"pems": pems, "pubkeys": pubkeys, "cfg": cfg, "store": sandbox_store}
    finally:
        app.dependency_overrides.clear()


class _EventCapture:
    """Register a fresh subscriber queue on `_event_subscribers` and drain
    it into a plain list of events, so tests can assert on broadcast
    payloads without hitting the SSE endpoint."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.events: list[dict[str, Any]] = []

    def attach(self) -> None:
        app_module._event_subscribers.append(self.queue)

    def detach(self) -> None:
        try:
            app_module._event_subscribers.remove(self.queue)
        except ValueError:
            pass

    def drain(self) -> None:
        while True:
            try:
                self.events.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                return

    def types(self) -> list[str]:
        return [e.get("type") for e in self.events]


class TestArbiterSigningE2E:
    """SDK-driven, HTTP-transported, PEM-backed arbiter voting flow.

    These are the tests the *integrator* (a real arbiter running the
    published Python SDK) exercises implicitly on first call. Individual
    layers already have their own coverage; here we assert the seams.
    """

    def _seed_disputed(self, client: TestClient, service_hash: str) -> None:
        r = client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 500,
                "service_hash": service_hash,
            },
        )
        assert r.status_code == 200, r.text
        r = client.post(
            "/dispute",
            json={"service_hash": service_hash, "reason_hash": "b" * 64},
        )
        assert r.status_code == 200, r.text

    def test_sdk_signs_pem_and_resolves_disputed_escrow_end_to_end(
        self, five_arbiter_panel_cfg
    ):
        """Happy path: SDK helper signs 3 votes from PKCS8 PEMs, SDK client
        POSTs `/resolve`, escrow moves disputed → resolved.

        Uses `httpx.ASGITransport` for the async SDK call and a sync
        `TestClient` for the setup POSTs. Both hit the *same* app
        instance and share `sandbox_store` via the dependency override.
        """
        pems = five_arbiter_panel_cfg["pems"]
        pubkeys = five_arbiter_panel_cfg["pubkeys"]

        service_hash = _hash("e2e-happy")

        with TestClient(app) as sync_client:
            self._seed_disputed(sync_client, service_hash)

            async def _run():
                votes = [
                    sign_arbiter_vote(pems[i], service_hash, "receiver") for i in range(3)
                ]
                submitted_pubkeys = [pk for pk, _ in votes]
                submitted_signatures = [sig for _, sig in votes]

                # Sanity: sdk.arbiter_signing must emit the same pubkeys the
                # panel registered. Any tag-prefix or serialization drift
                # would surface here as a hard mismatch.
                assert submitted_pubkeys == list(pubkeys[:3])

                sdk, http = _sdk_with_asgi()
                try:
                    return await sdk.resolve(
                        service_hash=service_hash,
                        in_favor_of="receiver",
                        arbiter_pubkeys=submitted_pubkeys,
                        arbiter_signatures=submitted_signatures,
                    )
                finally:
                    await http.aclose()

            result = asyncio.run(_run())

        assert result["status"] == "resolved", result
        assert result["service_hash"] == service_hash

    def test_broadcast_emits_both_escrow_resolved_and_arbitration_complete(
        self, five_arbiter_panel_cfg
    ):
        """A5 spec alias: /resolve must fan out `escrow_resolved` AND
        `arbitration_complete`. Drops either name silently and older SSE
        consumers (or the AE402 Agent Spec) break — but no test would
        fail today. This locks it."""
        pems = five_arbiter_panel_cfg["pems"]
        service_hash = _hash("e2e-broadcast")

        cap = _EventCapture()
        cap.attach()
        try:
            with TestClient(app) as sync_client:
                self._seed_disputed(sync_client, service_hash)
                votes = [
                    sign_arbiter_vote(pems[i], service_hash, "receiver") for i in range(3)
                ]
                resp = sync_client.post(
                    "/resolve",
                    json={
                        "service_hash": service_hash,
                        "in_favor_of": "receiver",
                        "arbiter_pubkeys": [pk for pk, _ in votes],
                        "arbiter_signatures": [sig for _, sig in votes],
                    },
                )
                assert resp.status_code == 200, resp.text

            cap.drain()
        finally:
            cap.detach()

        types = cap.types()
        # Setup path also broadcasts escrow_created + escrow_disputed +
        # dispute_opened — we only assert the resolve-time payloads exist.
        assert "escrow_resolved" in types, types
        assert "arbitration_complete" in types, types

        # And both must be scoped to this exact escrow.
        resolved = [e for e in cap.events if e["type"] == "escrow_resolved"]
        arb_done = [e for e in cap.events if e["type"] == "arbitration_complete"]
        assert any(e["service_hash"] == service_hash for e in resolved), resolved
        assert any(e["service_hash"] == service_hash for e in arb_done), arb_done

    def test_e2e_rejects_forged_signatures_from_unregistered_panel(
        self, five_arbiter_panel_cfg
    ):
        """Full-stack forgery reject: sign with PEMs whose pubkeys are NOT
        in the on-chain arbiter list. Same tag-prefix, same message
        format, same SDK path — must still 422.

        Symmetric to the unit-level reject in
        `test_api.py::TestResolveEndpoint.test_resolve_rejects_forged_signatures_from_unregistered_key`,
        but forced through the SDK helper + client to catch any layer
        that would strip / rewrite the pubkey en route.
        """
        service_hash = _hash("e2e-forged")

        # Outsiders — never registered.
        outsider_pems, _ = _make_arbiter_panel(3)

        with TestClient(app) as sync_client:
            self._seed_disputed(sync_client, service_hash)

            async def _run():
                votes = [
                    sign_arbiter_vote(pem, service_hash, "receiver")
                    for pem in outsider_pems
                ]
                sdk, http = _sdk_with_asgi()
                try:
                    with pytest.raises(httpx.HTTPStatusError) as exc_info:
                        await sdk.resolve(
                            service_hash=service_hash,
                            in_favor_of="receiver",
                            arbiter_pubkeys=[pk for pk, _ in votes],
                            arbiter_signatures=[sig for _, sig in votes],
                        )
                    return exc_info.value.response.status_code
                finally:
                    await http.aclose()

            status = asyncio.run(_run())

        assert status == 422

    def test_e2e_rejects_verdict_flip_after_signing(self, five_arbiter_panel_cfg):
        """Full-stack replay-flip reject: sign for `"receiver"`, submit
        claiming `"sender"`. The signature covers a different canonical
        message and must not verify — no matter how the SDK helper /
        client passes it through.
        """
        pems = five_arbiter_panel_cfg["pems"]
        service_hash = _hash("e2e-flip")

        with TestClient(app) as sync_client:
            self._seed_disputed(sync_client, service_hash)

            async def _run():
                votes = [
                    sign_arbiter_vote(pems[i], service_hash, "receiver") for i in range(3)
                ]
                sdk, http = _sdk_with_asgi()
                try:
                    with pytest.raises(httpx.HTTPStatusError) as exc_info:
                        await sdk.resolve(
                            service_hash=service_hash,
                            in_favor_of="sender",  # flipped
                            arbiter_pubkeys=[pk for pk, _ in votes],
                            arbiter_signatures=[sig for _, sig in votes],
                        )
                    return exc_info.value.response.status_code
                finally:
                    await http.aclose()

            status = asyncio.run(_run())

        assert status == 422

    def test_broadcast_carries_service_hash_and_int_ts(self, five_arbiter_panel_cfg):
        """Downstream consumers (dashboards, MCP subscribers, cross-repo
        agents) rely on `service_hash: str` and `ts: int`. Lock the
        payload shape so a future refactor cannot silently rename or
        retype either field."""
        pems = five_arbiter_panel_cfg["pems"]
        service_hash = _hash("e2e-payload-shape")

        cap = _EventCapture()
        cap.attach()
        try:
            with TestClient(app) as sync_client:
                self._seed_disputed(sync_client, service_hash)
                votes = [
                    sign_arbiter_vote(pems[i], service_hash, "receiver") for i in range(3)
                ]
                r = sync_client.post(
                    "/resolve",
                    json={
                        "service_hash": service_hash,
                        "in_favor_of": "receiver",
                        "arbiter_pubkeys": [pk for pk, _ in votes],
                        "arbiter_signatures": [sig for _, sig in votes],
                    },
                )
                assert r.status_code == 200, r.text
            cap.drain()
        finally:
            cap.detach()

        arb_events = [
            e
            for e in cap.events
            if e["type"] == "arbitration_complete"
            and e.get("service_hash") == service_hash
        ]
        assert arb_events, [e for e in cap.events if e["type"] == "arbitration_complete"]
        payload = arb_events[0]
        assert set(payload.keys()) >= {"type", "service_hash", "ts"}
        assert isinstance(payload["service_hash"], str) and len(payload["service_hash"]) == 64
        assert isinstance(payload["ts"], int) and payload["ts"] > 0
