"""Unit tests for `server/intent_chain.py` (AE-M1 — multi-hop A2A
choreography, pure core logic, no HTTP/FastAPI involved)."""

from __future__ import annotations

import pytest

from server.intent_chain import IntentChainError, IntentChainStore

SH0 = "a1" * 32
SH1 = "b2" * 32
SH2 = "c3" * 32


@pytest.fixture
def store():
    return IntentChainStore()


def test_declare_intent_basic(store):
    intent = store.declare_intent("i1", ["A", "B", "C"])
    assert intent.intent_id == "i1"
    assert intent.planned_hop_count == 2
    assert intent.attested_hop_count == 0
    assert intent.is_complete is False
    assert intent.declared_event_id is not None


def test_declare_intent_rejects_duplicate_id(store):
    store.declare_intent("i1", ["A", "B"])
    with pytest.raises(IntentChainError, match="already declared"):
        store.declare_intent("i1", ["A", "B"])


def test_declare_intent_rejects_single_agent_path(store):
    with pytest.raises(IntentChainError, match="at least 2 agents"):
        store.declare_intent("i1", ["A"])


def test_declare_intent_rejects_repeated_agent(store):
    with pytest.raises(IntentChainError, match="not repeat"):
        store.declare_intent("i1", ["A", "B", "A"])


def test_declare_intent_empty_id_rejected(store):
    with pytest.raises(IntentChainError, match="non-empty"):
        store.declare_intent("", ["A", "B"])


def test_get_intent_not_found(store):
    with pytest.raises(IntentChainError, match="not found"):
        store.get_intent("nope")


def test_chain_escrow_registers_hop_with_correct_agents(store):
    store.declare_intent("i1", ["A", "B", "C"])
    hop = store.chain_escrow("i1", SH0, 0)
    assert hop.from_agent == "A"
    assert hop.to_agent == "B"
    assert hop.attested is False


def test_chain_escrow_out_of_range_hop_index(store):
    store.declare_intent("i1", ["A", "B", "C"])  # 2 planned hops: 0, 1
    with pytest.raises(IntentChainError, match="out of range"):
        store.chain_escrow("i1", SH0, 2)
    with pytest.raises(IntentChainError, match="out of range"):
        store.chain_escrow("i1", SH0, -1)


def test_chain_escrow_rejects_out_of_order(store):
    store.declare_intent("i1", ["A", "B", "C"])
    with pytest.raises(IntentChainError, match="out of order"):
        store.chain_escrow("i1", SH1, 1)  # hop 0 not chained yet


def test_chain_escrow_rejects_double_chain_same_hop(store):
    store.declare_intent("i1", ["A", "B", "C"])
    store.chain_escrow("i1", SH0, 0)
    with pytest.raises(IntentChainError, match="already chained"):
        store.chain_escrow("i1", SH1, 0)


def test_chain_escrow_rejects_reused_service_hash_across_hops(store):
    store.declare_intent("i1", ["A", "B", "C"])
    store.chain_escrow("i1", SH0, 0)
    with pytest.raises(IntentChainError, match="already chained to intent"):
        store.chain_escrow("i1", SH0, 1)


def test_chain_escrow_unknown_intent(store):
    with pytest.raises(IntentChainError, match="not found"):
        store.chain_escrow("nope", SH0, 0)


def test_attest_hop_requires_chain_first(store):
    store.declare_intent("i1", ["A", "B"])
    with pytest.raises(IntentChainError, match="not chained yet"):
        store.attest_hop("i1", SH0, 0)


def test_attest_hop_rejects_service_hash_mismatch(store):
    store.declare_intent("i1", ["A", "B"])
    store.chain_escrow("i1", SH0, 0)
    with pytest.raises(IntentChainError, match="mismatch"):
        store.attest_hop("i1", SH1, 0)


def test_attest_hop_rejects_double_attest(store):
    store.declare_intent("i1", ["A", "B"])
    store.chain_escrow("i1", SH0, 0)
    store.attest_hop("i1", SH0, 0)
    with pytest.raises(IntentChainError, match="already attested"):
        store.attest_hop("i1", SH0, 0)


def test_full_three_agent_choreography_happy_path(store):
    """intent(A->B->C) -> escrow#1 create+release -> attestation#1 ->
    escrow#2 create+release -> attestation#2 -> chain_root_hash changes
    predictably at each attestation and the final root is independently
    reproducible from the returned event_ids."""
    intent = store.declare_intent("choreo-1", ["A", "B", "C"])
    assert intent.planned_hop_count == 2

    # Root is well-defined even before any hop is attested (genesis root).
    root_0 = store.get_intent("choreo-1").chain_root_hash

    hop0 = store.chain_escrow("choreo-1", SH0, 0)  # A -> B, escrow#1
    hop1 = store.chain_escrow("choreo-1", SH1, 1)  # B -> C, escrow#2
    assert hop0.from_agent == "A" and hop0.to_agent == "B"
    assert hop1.from_agent == "B" and hop1.to_agent == "C"

    # -- simulate escrow#1 being created+released elsewhere, then attest --
    store.attest_hop("choreo-1", SH0, 0)
    root_1 = store.get_intent("choreo-1").chain_root_hash
    assert root_1 != root_0
    assert store.get_intent("choreo-1").attested_hop_count == 1
    assert store.get_intent("choreo-1").is_complete is False

    # -- simulate escrow#2 being created+released elsewhere, then attest --
    store.attest_hop("choreo-1", SH1, 1)
    root_2 = store.get_intent("choreo-1").chain_root_hash
    assert root_2 != root_1
    final = store.get_intent("choreo-1")
    assert final.attested_hop_count == 2
    assert final.is_complete is True

    # Independent verification: recompute the root from the exposed
    # event_ids using the same primitive the module uses internally.
    from server import audit_trace

    event_ids = final.ordered_attestation_event_ids()
    assert len(event_ids) == 2
    assert audit_trace.compute_chain_root(event_ids) == root_2


def test_chain_root_hash_is_prefix_only_skips_gap(store):
    """If hop 0 is attested but hop 1 is not, the chain root only covers
    hop 0 -- a later, out-of-order attestation of hop 1 does not get
    silently folded in ahead of a still-missing predecessor."""
    store.declare_intent("i1", ["A", "B", "C"])
    store.chain_escrow("i1", SH0, 0)
    store.chain_escrow("i1", SH1, 1)

    store.attest_hop("i1", SH1, 1)  # attest hop 1 first (allowed -- only
    # *chaining* is order-enforced, not attestation, since releases can
    # legitimately complete out of order in a real multi-agent system)
    intent = store.get_intent("i1")
    # hop 0 not attested yet -> the ordered prefix is empty, so hop 1's
    # attestation is NOT reflected in chain_root_hash yet.
    assert intent.ordered_attestation_event_ids() == []

    store.attest_hop("i1", SH0, 0)
    intent = store.get_intent("i1")
    # Now hop 0 is attested, so the prefix includes it -- but hop 1's
    # attestation still isn't reachable until nothing is missing before it.
    assert len(intent.ordered_attestation_event_ids()) == 2


def test_single_hop_intent(store):
    """Minimal choreography: 2 agents, 1 hop."""
    intent = store.declare_intent("i1", ["A", "B"])
    assert intent.planned_hop_count == 1
    store.chain_escrow("i1", SH0, 0)
    store.attest_hop("i1", SH0, 0)
    assert store.get_intent("i1").is_complete is True


def test_four_agent_three_hop_choreography(store):
    """Longer chain: A -> B -> C -> D."""
    intent = store.declare_intent("i1", ["A", "B", "C", "D"])
    assert intent.planned_hop_count == 3
    store.chain_escrow("i1", SH0, 0)
    store.chain_escrow("i1", SH1, 1)
    store.chain_escrow("i1", SH2, 2)
    store.attest_hop("i1", SH0, 0)
    store.attest_hop("i1", SH1, 1)
    store.attest_hop("i1", SH2, 2)
    final = store.get_intent("i1")
    assert final.is_complete is True
    assert len(final.ordered_attestation_event_ids()) == 3


# ── record_on_chain_link ──────────────────────────────────────────────────


def test_record_on_chain_link_stores_tx_hash(store):
    store.declare_intent("i1", ["A", "B", "C"])
    store.chain_escrow("i1", SH0, 0)
    store.chain_escrow("i1", SH1, 1)

    tx = "d" * 64
    hop = store.record_on_chain_link("i1", 1, tx)
    assert hop.on_chain_link_tx_hash == tx
    # Round-trip via get_intent
    assert store.get_intent("i1").hops[1].on_chain_link_tx_hash == tx
    # Hop 0 never gets an on-chain link (no parent)
    assert store.get_intent("i1").hops[0].on_chain_link_tx_hash is None


def test_record_on_chain_link_rejects_hop_zero(store):
    store.declare_intent("i1", ["A", "B"])
    store.chain_escrow("i1", SH0, 0)
    with pytest.raises(IntentChainError, match="hop 0 has no parent"):
        store.record_on_chain_link("i1", 0, "d" * 64)


def test_record_on_chain_link_rejects_double_record(store):
    store.declare_intent("i1", ["A", "B", "C"])
    store.chain_escrow("i1", SH0, 0)
    store.chain_escrow("i1", SH1, 1)
    store.record_on_chain_link("i1", 1, "d" * 64)
    with pytest.raises(IntentChainError, match="already anchored on-chain"):
        store.record_on_chain_link("i1", 1, "e" * 64)


def test_record_on_chain_link_rejects_unchained_hop(store):
    store.declare_intent("i1", ["A", "B", "C"])
    store.chain_escrow("i1", SH0, 0)
    # hop 1 not yet chained
    with pytest.raises(IntentChainError, match="not chained"):
        store.record_on_chain_link("i1", 1, "d" * 64)


def test_record_on_chain_link_rejects_empty_tx_hash(store):
    store.declare_intent("i1", ["A", "B", "C"])
    store.chain_escrow("i1", SH0, 0)
    store.chain_escrow("i1", SH1, 1)
    with pytest.raises(IntentChainError, match="tx_hash must be non-empty"):
        store.record_on_chain_link("i1", 1, "")


def test_record_on_chain_link_unknown_intent(store):
    with pytest.raises(IntentChainError, match="not found"):
        store.record_on_chain_link("nope", 1, "d" * 64)
