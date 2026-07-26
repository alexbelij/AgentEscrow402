"""API tests for the `/intents` router (AE-M1 — multi-hop A2A choreography).

Covers both the router in isolation (`server/intent_chain_api.py`) and a
full integration path that drives the *real* `/escrow` + `/release`
endpoints for two hops (escrow#1: A->B, escrow#2: B->C) interleaved with
intent-chain bookkeeping — the actual judge-facing scenario:

    intent(A->B->C) -> escrow#1 create -> release -> attest#1
                     -> escrow#2 create -> release -> attest#2
                     -> chain_root_hash verified
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from server.app import app, get_config, get_sandbox
from server.config import Config
from server.intent_chain_api import IntentChainStore
from server.sandbox import SandboxStore

RECEIVER_HEX = "ab" * 32
RECEIVER_HEX_2 = "cd" * 32


def _hash(slug: str) -> str:
    return hashlib.sha256(slug.encode()).hexdigest()


@pytest.fixture(autouse=True)
def _reset_intent_store():
    """The intent-chain router keeps a process-lifetime singleton (same
    convention as identity_registry_api._registry) — reset it between
    tests so intent_id collisions across test cases can't happen and each
    test starts from a clean choreography table."""
    import server.intent_chain_api as mod

    mod._store = IntentChainStore()
    yield
    mod._store = IntentChainStore()


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


# ---------------------------------------------------------------------------
# Router-only tests (no real escrow lifecycle involved)
# ---------------------------------------------------------------------------


def test_declare_intent_returns_planned_hops(client):
    resp = client.post("/intents", json={"agent_path": ["A", "B", "C"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["planned_hop_count"] == 2
    assert body["is_complete"] is False
    assert "intent_id" in body


def test_declare_intent_with_explicit_id(client):
    resp = client.post("/intents", json={"intent_id": "my-intent", "agent_path": ["A", "B"]})
    assert resp.status_code == 200
    assert resp.json()["intent_id"] == "my-intent"


def test_declare_intent_duplicate_id_is_422(client):
    client.post("/intents", json={"intent_id": "dup", "agent_path": ["A", "B"]})
    resp = client.post("/intents", json={"intent_id": "dup", "agent_path": ["A", "B"]})
    assert resp.status_code == 422


def test_declare_intent_single_agent_rejected(client):
    resp = client.post("/intents", json={"agent_path": ["A"]})
    assert resp.status_code == 422  # pydantic min_length=2 on agent_path


def test_get_unknown_intent_is_404(client):
    resp = client.get("/intents/does-not-exist")
    assert resp.status_code == 404


def test_chain_escrow_out_of_order_is_422(client):
    resp = client.post("/intents", json={"intent_id": "i1", "agent_path": ["A", "B", "C"]})
    assert resp.status_code == 200
    resp = client.post("/intents/i1/hops", json={"service_hash": _hash("sh1"), "hop_index": 1})
    assert resp.status_code == 422


def test_attest_without_chain_is_422(client):
    client.post("/intents", json={"intent_id": "i1", "agent_path": ["A", "B"]})
    resp = client.post("/intents/i1/hops/0/attest", json={"service_hash": _hash("sh0")})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Full integration: real /escrow + /release lifecycle, two hops
# ---------------------------------------------------------------------------


def test_multi_hop_choreography_with_real_escrow_lifecycle(client):
    """The exact scenario from the AE402 defence-checklist spec:
    intent -> escrow#1 -> attestation -> escrow#2 -> attestation -> release,
    with chain_root_hash verified at each step."""
    # 1. Declare the choreography: agent A -> agent B -> agent C.
    resp = client.post("/intents", json={"intent_id": "choreo-e2e", "agent_path": ["A", "B", "C"]})
    assert resp.status_code == 200
    assert resp.json()["planned_hop_count"] == 2
    root_before_any_hop = resp.json()["chain_root_hash"]

    sh1 = _hash("choreo-e2e-hop0")
    sh2 = _hash("choreo-e2e-hop1")

    # 2. Real escrow#1 (A -> B), created via the ordinary /escrow endpoint.
    resp = client.post(
        "/escrow",
        json={"receiver": RECEIVER_HEX, "amount": 500, "service_hash": sh1},
        params={"sender": "agentA"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending"

    # 3. Register escrow#1 as hop 0 of the choreography.
    resp = client.post("/intents/choreo-e2e/hops", json={"service_hash": sh1, "hop_index": 0})
    assert resp.status_code == 200
    assert resp.json()["hops"][0]["from_agent"] == "A"
    assert resp.json()["hops"][0]["to_agent"] == "B"

    # 4. Real release of escrow#1 via the ordinary /release endpoint.
    resp = client.post("/release", json={"service_hash": sh1}, params={"sender": "agentA"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "released"

    # 5. Attest hop 0 -- folds a hop_attested audit event into the chain root.
    resp = client.post("/intents/choreo-e2e/hops/0/attest", json={"service_hash": sh1})
    assert resp.status_code == 200
    root_after_hop0 = resp.json()["chain_root_hash"]
    assert root_after_hop0 != root_before_any_hop
    assert resp.json()["is_complete"] is False

    # 6. Real escrow#2 (B -> C).
    resp = client.post(
        "/escrow",
        json={"receiver": RECEIVER_HEX_2, "amount": 300, "service_hash": sh2},
        params={"sender": "agentB"},
    )
    assert resp.status_code == 200, resp.text

    # 7. Register escrow#2 as hop 1.
    resp = client.post("/intents/choreo-e2e/hops", json={"service_hash": sh2, "hop_index": 1})
    assert resp.status_code == 200
    assert resp.json()["hops"][1]["from_agent"] == "B"
    assert resp.json()["hops"][1]["to_agent"] == "C"

    # 8. Real release of escrow#2.
    resp = client.post("/release", json={"service_hash": sh2}, params={"sender": "agentB"})
    assert resp.status_code == 200, resp.text

    # 9. Attest hop 1 -- choreography is now complete.
    resp = client.post("/intents/choreo-e2e/hops/1/attest", json={"service_hash": sh2})
    assert resp.status_code == 200
    body = resp.json()
    root_after_hop1 = body["chain_root_hash"]
    assert root_after_hop1 != root_after_hop0
    assert body["is_complete"] is True
    assert len(body["attestation_event_ids"]) == 2

    # 10. GET the intent independently and confirm identical, stable state.
    resp = client.get("/intents/choreo-e2e")
    assert resp.status_code == 200
    final = resp.json()
    assert final["chain_root_hash"] == root_after_hop1
    assert final["is_complete"] is True
    assert [h["service_hash"] for h in final["hops"]] == [sh1, sh2]

    # 11. Judge-side independent verification: recompute chain_root_hash
    # from the exposed event_ids using the public primitive directly.
    from server import audit_trace

    assert audit_trace.compute_chain_root(final["attestation_event_ids"]) == root_after_hop1


def test_hop_registered_with_wrong_parent_intent_is_rejected(client):
    """Negative test requested in the defence-checklist spec: a hop
    claiming to belong to an intent it wasn't declared under must be
    rejected outright."""
    client.post("/intents", json={"intent_id": "real-intent", "agent_path": ["A", "B"]})
    sh = _hash("orphan-hop")

    # There is no "wrong-intent" registration possible by construction --
    # chain_escrow always writes under whatever intent_id is in the URL --
    # so the meaningful negative case is: registering a hop under an
    # intent_id that was never declared at all must 404/422, not silently
    # create a dangling hop.
    resp = client.post("/intents/never-declared/hops", json={"service_hash": sh, "hop_index": 0})
    assert resp.status_code == 422

    # And attesting a hop under the wrong (but real) intent, for a
    # service_hash that was never chained there, must also be rejected.
    resp = client.post("/intents/real-intent/hops/0/attest", json={"service_hash": sh})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /escrow: parent_intent_id + hop_index integration
# ---------------------------------------------------------------------------


def test_create_escrow_with_intent_registers_hop(client):
    """POST /escrow carrying parent_intent_id + hop_index should register
    the escrow as that hop of the intent in a single call (no separate
    POST /intents/{id}/hops needed)."""
    # Declare intent A->B->C first.
    intent_resp = client.post("/intents", json={"intent_id": "int-1", "agent_path": ["A", "B", "C"]})
    assert intent_resp.status_code == 200

    # Hop 0 escrow: create with parent_intent_id + hop_index.
    sh0 = _hash("hop-0-svc")
    resp = client.post(
        "/escrow",
        json={
            "receiver": RECEIVER_HEX,
            "amount": 1_000_000_000,
            "service_hash": sh0,
            "parent_intent_id": "int-1",
            "hop_index": 0,
        },
    )
    assert resp.status_code == 200, resp.text

    # Verify hop was registered on the intent.
    intent = client.get("/intents/int-1").json()
    assert len(intent["hops"]) == 1
    assert intent["hops"][0]["hop_index"] == 0
    assert intent["hops"][0]["service_hash"] == sh0
    assert intent["hops"][0]["from_agent"] == "A"
    assert intent["hops"][0]["to_agent"] == "B"


def test_create_escrow_without_intent_metadata_is_unchanged(client):
    """Escrow creation without parent_intent_id/hop_index must behave
    exactly as before (non-regression)."""
    sh = _hash("no-intent")
    resp = client.post(
        "/escrow",
        json={
            "receiver": RECEIVER_HEX,
            "amount": 1_000_000_000,
            "service_hash": sh,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["service_hash"] == sh
    # No intents were created as a side-effect.
    got = client.get("/intents/anything")
    assert got.status_code == 404


def test_create_escrow_with_unknown_intent_still_succeeds(client):
    """If parent_intent_id refers to an intent that doesn't exist,
    escrow creation itself must NOT be rolled back -- the escrow row is
    a first-class object, chain-linkage is metadata. The caller can
    retry hop registration via POST /intents/{id}/hops later."""
    sh = _hash("orphan-hop")
    resp = client.post(
        "/escrow",
        json={
            "receiver": RECEIVER_HEX,
            "amount": 1_000_000_000,
            "service_hash": sh,
            "parent_intent_id": "does-not-exist",
            "hop_index": 0,
        },
    )
    assert resp.status_code == 200, resp.text
    # Escrow was created, but the (non-existent) intent still 404s.
    assert client.get("/intents/does-not-exist").status_code == 404


def test_create_escrow_intent_end_to_end_two_hops(client):
    """Full two-hop path via POST /escrow with intent metadata: register
    both hops implicitly through /escrow (no explicit /intents/{id}/hops
    calls), then attest each after release. chain_root_hash must fold
    the two attestations deterministically."""
    client.post("/intents", json={"intent_id": "int-e2e", "agent_path": ["A", "B", "C"]})

    sh0 = _hash("e2e-hop-0")
    sh1 = _hash("e2e-hop-1")

    # Hop 0: escrow + release + attest, all through the real endpoints.
    # `?sender=agentA` makes agentA the escrow's sender, which is the
    # identity /release checks against (see existing choreography e2e).
    r = client.post(
        "/escrow",
        json={
            "receiver": RECEIVER_HEX,
            "amount": 1_000_000_000,
            "service_hash": sh0,
            "parent_intent_id": "int-e2e",
            "hop_index": 0,
        },
        params={"sender": "agentA"},
    )
    assert r.status_code == 200, r.text
    r = client.post("/release", json={"service_hash": sh0}, params={"sender": "agentA"})
    assert r.status_code == 200, r.text
    r = client.post("/intents/int-e2e/hops/0/attest", json={"service_hash": sh0})
    assert r.status_code == 200, r.text

    # Hop 1: same pattern.
    r = client.post(
        "/escrow",
        json={
            "receiver": RECEIVER_HEX_2,
            "amount": 2_000_000_000,
            "service_hash": sh1,
            "parent_intent_id": "int-e2e",
            "hop_index": 1,
        },
        params={"sender": "agentB"},
    )
    assert r.status_code == 200, r.text
    r = client.post("/release", json={"service_hash": sh1}, params={"sender": "agentB"})
    assert r.status_code == 200, r.text
    r = client.post("/intents/int-e2e/hops/1/attest", json={"service_hash": sh1})
    assert r.status_code == 200, r.text

    # Final state: intent is complete, chain_root_hash covers both
    # attestations, and a judge can independently recompute it from
    # attestation_event_ids using audit_trace.compute_chain_root.
    intent = client.get("/intents/int-e2e").json()
    assert intent["is_complete"] is True
    assert intent["attested_hop_count"] == 2
    assert len(intent["attestation_event_ids"]) == 2
    from server import audit_trace

    assert intent["chain_root_hash"] == audit_trace.compute_chain_root(intent["attestation_event_ids"])
