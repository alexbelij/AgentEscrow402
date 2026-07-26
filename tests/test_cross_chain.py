"""Tests for server/cross_chain.py — cross-chain escrow lifecycle (W.3)."""

from __future__ import annotations

import time

import pytest

from server import cross_chain as cc


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    """Isolate each test: reset the module-level registry singleton."""
    cc.reset_registry()
    yield
    cc.reset_registry()


# ---------------------------------------------------------------------------
# ChainId + adapter behavior
# ---------------------------------------------------------------------------


class TestMockEVMAdapter:
    def test_supported_chains(self):
        a = cc.MockEVMAdapter()
        chains = a.supported_chains()
        assert cc.ChainId.ETHEREUM in chains
        assert cc.ChainId.POLYGON in chains
        assert cc.ChainId.CASPER_TESTNET not in chains

    def test_unknown_tx_returns_unconfirmed(self):
        a = cc.MockEVMAdapter()
        r = a.verify_remote_tx(cc.ChainId.ETHEREUM, "0xdeadbeef")
        assert r.confirmed is False
        assert r.block_number == 0
        assert r.confirmations == 0

    def test_record_event_and_verify(self):
        a = cc.MockEVMAdapter(initial_height=100)
        a.record_event(
            cc.ChainId.ETHEREUM,
            "0xabc",
            topics=["0xTransfer"],
            data="0xdead",
            block_offset=5,  # mined 5 blocks ago
        )
        r = a.verify_remote_tx(cc.ChainId.ETHEREUM, "0xabc")
        assert r.confirmed
        assert r.block_number == 95
        assert r.confirmations == 5
        assert "0xTransfer" in r.topics

    def test_confirmations_grow_with_height(self):
        a = cc.MockEVMAdapter(initial_height=100)
        a.record_event(cc.ChainId.ETHEREUM, "0xabc", topics=[], block_offset=0)
        assert a.verify_remote_tx(cc.ChainId.ETHEREUM, "0xabc").confirmations == 0
        a.advance_blocks(cc.ChainId.ETHEREUM, 20)
        assert a.verify_remote_tx(cc.ChainId.ETHEREUM, "0xabc").confirmations == 20

    def test_tx_hash_normalization(self):
        a = cc.MockEVMAdapter()
        a.record_event(cc.ChainId.ETHEREUM, "0xAbCdEf", topics=[])
        # Any case, with or without 0x prefix, must match.
        assert a.verify_remote_tx(cc.ChainId.ETHEREUM, "abcdef").confirmed
        assert a.verify_remote_tx(cc.ChainId.ETHEREUM, "0xabcdef").confirmed
        assert a.verify_remote_tx(cc.ChainId.ETHEREUM, "0xABCDEF").confirmed

    def test_unsupported_chain_raises(self):
        a = cc.MockEVMAdapter()
        with pytest.raises(cc.CrossChainError, match="unsupported"):
            a.verify_remote_tx(cc.ChainId.CASPER_TESTNET, "0xdead")


class TestMockCasperAdapter:
    def test_casper_always_confirms(self):
        a = cc.MockCasperAdapter()
        r = a.verify_remote_tx(cc.ChainId.CASPER_TESTNET, "deadbeef")
        assert r.confirmed
        assert r.block_number > 0


# ---------------------------------------------------------------------------
# Registry — create / settle / cancel / expire
# ---------------------------------------------------------------------------

VALID_SVC_HASH = "a" * 64


def _make_registry(initial_height: int = 1000) -> cc.CrossChainRegistry:
    return cc.CrossChainRegistry(
        evm_adapter=cc.MockEVMAdapter(initial_height=initial_height),
        casper_adapter=cc.MockCasperAdapter(),
    )


class TestCreateCrossChainEscrow:
    def test_happy_path(self):
        reg = _make_registry()
        e = reg.create_cross_chain_escrow(
            sender="sender1",
            receiver="receiver1",
            amount_motes=1_000_000_000,
            service_hash=VALID_SVC_HASH,
            trigger_chain=cc.ChainId.ETHEREUM,
            trigger_tx_hash="0xdeadbeef",
            trigger_topic="0xTransfer",
            min_confirmations=6,
        )
        assert e.status == cc.CrossChainStatus.PENDING
        assert e.escrow_id.startswith("cc-")
        assert e.amount_motes == 1_000_000_000
        assert e.trigger_chain == cc.ChainId.ETHEREUM

    def test_rejects_zero_amount(self):
        reg = _make_registry()
        with pytest.raises(cc.CrossChainError, match="amount_motes"):
            reg.create_cross_chain_escrow(
                sender="s",
                receiver="r",
                amount_motes=0,
                service_hash=VALID_SVC_HASH,
                trigger_chain=cc.ChainId.ETHEREUM,
                trigger_tx_hash="0xdead",
                trigger_topic="0xT",
            )

    def test_rejects_unsupported_chain(self):
        reg = _make_registry()
        with pytest.raises(cc.CrossChainError, match="not supported"):
            reg.create_cross_chain_escrow(
                sender="s",
                receiver="r",
                amount_motes=1,
                service_hash=VALID_SVC_HASH,
                trigger_chain=cc.ChainId.CASPER_TESTNET,  # not EVM
                trigger_tx_hash="0xdead",
                trigger_topic="",
            )

    def test_rejects_double_binding_same_trigger(self):
        reg = _make_registry()
        reg.create_cross_chain_escrow(
            sender="s1",
            receiver="r",
            amount_motes=1,
            service_hash=VALID_SVC_HASH,
            trigger_chain=cc.ChainId.ETHEREUM,
            trigger_tx_hash="0xabc",
            trigger_topic="",
        )
        with pytest.raises(cc.CrossChainError, match="already bound"):
            reg.create_cross_chain_escrow(
                sender="s2",
                receiver="r",
                amount_motes=1,
                service_hash=VALID_SVC_HASH,
                trigger_chain=cc.ChainId.ETHEREUM,
                trigger_tx_hash="0xABC",  # same, case-insensitive
                trigger_topic="",
            )

    def test_deterministic_escrow_id(self):
        reg = _make_registry()
        e = reg.create_cross_chain_escrow(
            sender="s",
            receiver="r",
            amount_motes=1,
            service_hash=VALID_SVC_HASH,
            trigger_chain=cc.ChainId.ETHEREUM,
            trigger_tx_hash="0xabc",
            trigger_topic="",
        )
        # Same binding data → same id
        expected = cc._derive_escrow_id("s", "r", cc.ChainId.ETHEREUM, "0xabc")
        assert e.escrow_id == expected


class TestSettleOnEVMEvent:
    def test_full_happy_path(self):
        reg = _make_registry(initial_height=100)
        e = reg.create_cross_chain_escrow(
            sender="s",
            receiver="r",
            amount_motes=1000,
            service_hash=VALID_SVC_HASH,
            trigger_chain=cc.ChainId.ETHEREUM,
            trigger_tx_hash="0xdeadc0de",
            trigger_topic="0xTransfer",
            min_confirmations=6,
        )
        # Trigger event lands at head, needs 6 confirmations.
        reg.evm.record_event(
            cc.ChainId.ETHEREUM,
            "0xdeadc0de",
            topics=["0xTransfer"],
            block_offset=0,
        )
        # Not enough confirmations yet.
        with pytest.raises(cc.CrossChainError, match="insufficient"):
            reg.settle_on_evm_event(e.escrow_id)
        # Advance past threshold.
        reg.evm.advance_blocks(cc.ChainId.ETHEREUM, 10)
        settled = reg.settle_on_evm_event(e.escrow_id)
        assert settled.status == cc.CrossChainStatus.SETTLED
        assert settled.settled_at is not None
        assert settled.settled_tx and len(settled.settled_tx) == 64
        assert settled.trigger_verified.confirmations >= 6

    def test_idempotent_settle(self):
        reg = _make_registry(initial_height=100)
        e = reg.create_cross_chain_escrow(
            sender="s",
            receiver="r",
            amount_motes=1000,
            service_hash=VALID_SVC_HASH,
            trigger_chain=cc.ChainId.ETHEREUM,
            trigger_tx_hash="0xdead0001",
            trigger_topic="",
            min_confirmations=1,
        )
        reg.evm.record_event(cc.ChainId.ETHEREUM, "0xdead0001", topics=[], block_offset=10)
        first = reg.settle_on_evm_event(e.escrow_id)
        assert first.status == cc.CrossChainStatus.SETTLED
        first_tx = first.settled_tx
        first_time = first.settled_at
        # Second call: no-op, returns same record.
        second = reg.settle_on_evm_event(e.escrow_id)
        assert second.status == cc.CrossChainStatus.SETTLED
        assert second.settled_tx == first_tx
        assert second.settled_at == first_time

    def test_settle_without_event_fails(self):
        reg = _make_registry(initial_height=100)
        e = reg.create_cross_chain_escrow(
            sender="s",
            receiver="r",
            amount_motes=1000,
            service_hash=VALID_SVC_HASH,
            trigger_chain=cc.ChainId.ETHEREUM,
            trigger_tx_hash="0xdead0001",
            trigger_topic="",
            min_confirmations=1,
        )
        with pytest.raises(cc.CrossChainError, match="not yet observed"):
            reg.settle_on_evm_event(e.escrow_id)

    def test_settle_topic_mismatch(self):
        reg = _make_registry(initial_height=100)
        e = reg.create_cross_chain_escrow(
            sender="s",
            receiver="r",
            amount_motes=1000,
            service_hash=VALID_SVC_HASH,
            trigger_chain=cc.ChainId.ETHEREUM,
            trigger_tx_hash="0xdead0001",
            trigger_topic="0xExpected",
            min_confirmations=1,
        )
        reg.evm.record_event(cc.ChainId.ETHEREUM, "0xdead0001", topics=["0xOther"], block_offset=10)
        with pytest.raises(cc.CrossChainError, match="topic"):
            reg.settle_on_evm_event(e.escrow_id)

    def test_settle_unknown_escrow(self):
        reg = _make_registry()
        with pytest.raises(cc.CrossChainError, match="unknown"):
            reg.settle_on_evm_event("cc-nonexistent")


class TestCancel:
    def test_sender_can_cancel_pending(self):
        reg = _make_registry()
        e = reg.create_cross_chain_escrow(
            sender="s1",
            receiver="r",
            amount_motes=1,
            service_hash=VALID_SVC_HASH,
            trigger_chain=cc.ChainId.ETHEREUM,
            trigger_tx_hash="0xdead02",
            trigger_topic="",
        )
        cancelled = reg.cancel(e.escrow_id, caller="s1")
        assert cancelled.status == cc.CrossChainStatus.CANCELLED

    def test_non_sender_cannot_cancel(self):
        reg = _make_registry()
        e = reg.create_cross_chain_escrow(
            sender="s1",
            receiver="r",
            amount_motes=1,
            service_hash=VALID_SVC_HASH,
            trigger_chain=cc.ChainId.ETHEREUM,
            trigger_tx_hash="0xdead02",
            trigger_topic="",
        )
        with pytest.raises(cc.CrossChainError, match="only the sender"):
            reg.cancel(e.escrow_id, caller="attacker")

    def test_cannot_cancel_settled(self):
        reg = _make_registry(initial_height=100)
        e = reg.create_cross_chain_escrow(
            sender="s",
            receiver="r",
            amount_motes=1,
            service_hash=VALID_SVC_HASH,
            trigger_chain=cc.ChainId.ETHEREUM,
            trigger_tx_hash="0xdead02",
            trigger_topic="",
            min_confirmations=1,
        )
        reg.evm.record_event(cc.ChainId.ETHEREUM, "0xdead02", topics=[], block_offset=5)
        reg.settle_on_evm_event(e.escrow_id)
        with pytest.raises(cc.CrossChainError, match="settled"):
            reg.cancel(e.escrow_id, caller="s")


class TestExpire:
    def test_expire_after_ttl(self, monkeypatch):
        reg = _make_registry()
        e = reg.create_cross_chain_escrow(
            sender="s",
            receiver="r",
            amount_motes=1,
            service_hash=VALID_SVC_HASH,
            trigger_chain=cc.ChainId.ETHEREUM,
            trigger_tx_hash="0xdead02",
            trigger_topic="",
        )
        # Rewind escrow created_at.
        e.created_at = int(time.time()) - 3600
        expired = reg.expire(e.escrow_id, ttl_seconds=1800)
        assert expired.status == cc.CrossChainStatus.EXPIRED

    def test_expire_before_ttl_raises(self):
        reg = _make_registry()
        e = reg.create_cross_chain_escrow(
            sender="s",
            receiver="r",
            amount_motes=1,
            service_hash=VALID_SVC_HASH,
            trigger_chain=cc.ChainId.ETHEREUM,
            trigger_tx_hash="0xdead02",
            trigger_topic="",
        )
        with pytest.raises(cc.CrossChainError, match="not yet expired"):
            reg.expire(e.escrow_id, ttl_seconds=3600)


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


class TestAPI:
    def test_full_lifecycle_via_api(self):
        from fastapi.testclient import TestClient

        from server.app import app

        client = TestClient(app)

        cc.reset_registry()

        # 1. List chains.
        r = client.get("/crosschain/chains")
        assert r.status_code == 200
        chains = r.json()
        assert "ethereum" in chains["evm"]
        assert "casper-testnet" in chains["casper"]

        # 2. Create escrow.
        r = client.post(
            "/crosschain/escrow",
            json={
                "sender": "0xSender",
                "receiver": "0xReceiver",
                "amount_motes": 1_000_000,
                "service_hash": "b" * 64,
                "trigger_chain": "ethereum",
                "trigger_tx_hash": "0xdead0abc",
                "trigger_topic": "0xTransfer",
                "min_confirmations": 3,
            },
        )
        assert r.status_code == 201, r.text
        escrow = r.json()["escrow"]
        assert escrow["status"] == "pending"
        eid = escrow["escrow_id"]

        # 3. Settle before event → 400.
        r = client.post("/crosschain/settle", json={"escrow_id": eid})
        assert r.status_code == 400
        assert "not yet observed" in r.json()["detail"]

        # 4. Inject mock event 5 blocks ago.
        r = client.post(
            "/crosschain/mock/event",
            json={
                "chain": "ethereum",
                "tx_hash": "0xdead0abc",
                "topics": ["0xTransfer"],
                "block_offset": 5,
            },
        )
        assert r.status_code == 200

        # 5. Settle — should succeed (5 >= 3 confirmations).
        r = client.post("/crosschain/settle", json={"escrow_id": eid})
        assert r.status_code == 200, r.text
        settled = r.json()["escrow"]
        assert settled["status"] == "settled"
        assert settled["settled_tx"] is not None
        assert settled["trigger_verified"]["confirmations"] >= 3

        # 6. Idempotent second settle.
        r2 = client.post("/crosschain/settle", json={"escrow_id": eid})
        assert r2.status_code == 200
        assert r2.json()["escrow"]["settled_tx"] == settled["settled_tx"]

        # 7. Fetch by id.
        r = client.get(f"/crosschain/escrow/{eid}")
        assert r.status_code == 200
        assert r.json()["escrow"]["escrow_id"] == eid

        # 8. Cancel a settled escrow → 400.
        r = client.post("/crosschain/cancel", json={"escrow_id": eid, "caller": "0xSender"})
        assert r.status_code == 400

    def test_advance_blocks_endpoint(self):
        from fastapi.testclient import TestClient

        from server.app import app

        client = TestClient(app)
        cc.reset_registry()
        reg = cc.get_registry()

        r = client.post("/crosschain/mock/advance", json={"chain": "polygon", "blocks": 100})
        assert r.status_code == 200
        assert r.json()["escrow"]["new_height"] == reg.evm.remote_block_height(cc.ChainId.POLYGON)
