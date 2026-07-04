"""Tests for sandbox escrow store."""

from __future__ import annotations

import hashlib

import pytest


def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


@pytest.fixture
def receiver():
    return "account-hash-receiver-001"


class TestSandboxEscrow:
    def test_create_escrow(self, sandbox, sender, receiver, service_hash):
        rec = sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        assert rec.sender == sender
        assert rec.receiver == receiver
        assert rec.amount == 1000
        assert rec.status.value == "pending"

    def test_duplicate_escrow_raises(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        with pytest.raises(ValueError, match="already exists"):
            sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)

    def test_release_escrow(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        rec = sandbox.release_escrow(service_hash, sender)
        assert rec.status.value == "released"

    def test_release_by_non_sender_raises(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        with pytest.raises(PermissionError, match="Only sender"):
            sandbox.release_escrow(service_hash, "some-other-account")

    def test_release_records_its_own_deploy_hash(self, sandbox, sender, receiver, service_hash):
        """Regression test: previously `release_escrow` (and refund/dispute)
        silently kept whatever `deploy_hash` `create_escrow` had set, so a
        live (non-sandbox) release against the real API would report the
        *create* transaction's hash instead of the actual release
        transaction's hash. Discovered live against production while
        building examples/escrow_agent.py."""
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        rec = sandbox.release_escrow(service_hash, sender, deploy_hash="release-deploy-hash-abc")
        assert rec.deploy_hash == "release-deploy-hash-abc"

    def test_refund_records_its_own_deploy_hash(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        rec = sandbox.refund_escrow(service_hash, sender, deploy_hash="refund-deploy-hash-abc")
        assert rec.deploy_hash == "refund-deploy-hash-abc"

    def test_dispute_records_its_own_deploy_hash(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        rec = sandbox.dispute_escrow(service_hash, deploy_hash="dispute-deploy-hash-abc")
        assert rec.deploy_hash == "dispute-deploy-hash-abc"

    def test_release_already_released_raises(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        sandbox.release_escrow(service_hash, sender)
        with pytest.raises(ValueError, match="Cannot release"):
            sandbox.release_escrow(service_hash, sender)

    def test_refund_by_sender(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        rec = sandbox.refund_escrow(service_hash, sender)
        assert rec.status.value == "refunded"

    def test_refund_by_non_sender_not_expired(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        with pytest.raises(PermissionError):
            sandbox.refund_escrow(service_hash, "stranger")

    def test_dispute_escrow(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        rec = sandbox.dispute_escrow(service_hash)
        assert rec.status.value == "disputed"

    def test_dispute_already_released_raises(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        sandbox.release_escrow(service_hash, sender)
        with pytest.raises(ValueError, match="Cannot dispute"):
            sandbox.dispute_escrow(service_hash)

    def test_get_nonexistent_returns_none(self, sandbox):
        result = sandbox.get_escrow("missing-hash")
        assert result is None

    def test_get_existing_escrow(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 500, service_hash, 300)
        rec = sandbox.get_escrow(service_hash)
        assert rec is not None
        assert rec.amount == 500

    def test_refund_disputed_escrow_raises(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        sandbox.dispute_escrow(service_hash)
        with pytest.raises(ValueError, match="Cannot refund"):
            sandbox.refund_escrow(service_hash, sender)

    def test_multiple_escrows(self, sandbox, sender, receiver):
        h1 = _hash("escrow-001")
        h2 = _hash("escrow-002")
        sandbox.create_escrow(sender, receiver, 100, h1, 300)
        sandbox.create_escrow(sender, receiver, 200, h2, 600)
        assert sandbox.get_escrow(h1).amount == 100
        assert sandbox.get_escrow(h2).amount == 200


class TestReputation:
    def test_default_reputation(self, sandbox):
        rep = sandbox.get_reputation("new-agent")
        assert rep.completed == 0
        assert rep.disputed == 0
        assert rep.score == 50

    def test_reputation_after_release(self, sandbox, sender, service_hash):
        receiver = "agent-rcv-001"
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        sandbox.release_escrow(service_hash, sender)
        rep = sandbox.get_reputation(receiver)
        assert rep.completed == 1
        assert rep.score == 55

    def test_reputation_after_dispute(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        sandbox.dispute_escrow(service_hash)
        rep = sandbox.get_reputation(sender)
        assert rep.disputed == 1
        assert rep.score == 40

    def test_reputation_multiple_completions(self, sandbox, sender):
        receiver = "reliable-agent"
        for i in range(3):
            h = _hash(f"task-{i}")
            sandbox.create_escrow(sender, receiver, 100, h, 300)
            sandbox.release_escrow(h, sender)
        rep = sandbox.get_reputation(receiver)
        assert rep.completed == 3
        assert rep.score == 65

    def test_reputation_capped_at_100(self, sandbox, sender):
        receiver = "super-agent"
        for i in range(20):
            h = _hash(f"task-{i}")
            sandbox.create_escrow(sender, receiver, 100, h, 300)
            sandbox.release_escrow(h, sender)
        rep = sandbox.get_reputation(receiver)
        assert rep.score <= 100
