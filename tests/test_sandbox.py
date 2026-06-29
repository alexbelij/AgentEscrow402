"""Tests for sandbox escrow store."""

from __future__ import annotations

import hashlib
import pytest

from server.sandbox import SandboxStore


def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


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

    def test_release_wrong_caller_raises(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        with pytest.raises(PermissionError):
            sandbox.release_escrow(service_hash, "imposter")

    def test_refund_by_sender(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        rec = sandbox.refund_escrow(service_hash, sender)
        assert rec.status.value == "refunded"

    def test_dispute_escrow(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        rec = sandbox.dispute_escrow(service_hash)
        assert rec.status.value == "disputed"

    def test_dispute_released_raises(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        sandbox.release_escrow(service_hash, sender)
        with pytest.raises(ValueError, match="Cannot dispute"):
            sandbox.dispute_escrow(service_hash)

    def test_get_escrow_not_found(self, sandbox):
        result = sandbox.get_escrow("nonexistent")
        assert result is None

    def test_multiple_independent_escrows(self, sandbox, sender, receiver):
        h1 = _hash("escrow-1")
        h2 = _hash("escrow-2")
        sandbox.create_escrow(sender, receiver, 500, h1, 120)
        sandbox.create_escrow(sender, receiver, 800, h2, 600)
        assert sandbox.get_escrow(h1).amount == 500
        assert sandbox.get_escrow(h2).amount == 800


class TestSandboxReputation:
    def test_default_reputation(self, sandbox):
        rep = sandbox.get_reputation("unknown-agent")
        assert rep.completed == 0
        assert rep.score == 50

    def test_reputation_after_release(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        sandbox.release_escrow(service_hash, sender)
        rep = sandbox.get_reputation(receiver)
        assert rep.completed == 1
        assert rep.score > 50

    def test_reputation_after_dispute(self, sandbox, sender, receiver, service_hash):
        sandbox.create_escrow(sender, receiver, 1000, service_hash, 300)
        sandbox.dispute_escrow(service_hash)
        rep = sandbox.get_reputation(sender)
        assert rep.disputed == 1
        assert rep.score < 50
