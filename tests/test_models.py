"""Tests for data models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.models import (
    DisputeRequest,
    EscrowRequest,
    EscrowStatus,
    HealthResponse,
    PaymentHeader,
    ReputationRecord,
    ResolveRequest,
)


class TestEscrowRequest:
    def test_valid_request(self):
        h = "a" * 64
        req = EscrowRequest(receiver="ab" * 32, amount=1000, service_hash=h)
        assert req.ttl == 300
        assert req.amount == 1000

    def test_zero_amount_rejected(self):
        h = "a" * 64
        with pytest.raises(ValidationError):
            EscrowRequest(receiver="rcv", amount=0, service_hash=h)

    def test_negative_amount_rejected(self):
        h = "a" * 64
        with pytest.raises(ValidationError):
            EscrowRequest(receiver="rcv", amount=-5, service_hash=h)

    def test_short_hash_rejected(self):
        with pytest.raises(ValidationError):
            EscrowRequest(receiver="rcv", amount=100, service_hash="short")

    def test_custom_ttl(self):
        h = "b" * 64
        req = EscrowRequest(receiver="ab" * 32, amount=100, service_hash=h, ttl=600)
        assert req.ttl == 600

    def test_ttl_below_min_rejected(self):
        h = "c" * 64
        with pytest.raises(ValidationError):
            EscrowRequest(receiver="r", amount=100, service_hash=h, ttl=10)

    def test_ttl_above_max_rejected(self):
        h = "d" * 64
        with pytest.raises(ValidationError):
            EscrowRequest(receiver="r", amount=100, service_hash=h, ttl=100_000)

    def test_hash_too_long_rejected(self):
        with pytest.raises(ValidationError):
            EscrowRequest(receiver="r", amount=100, service_hash="e" * 65)


class TestEscrowStatus:
    def test_all_statuses(self):
        expected = {
            "pending",
            "released",
            "refunded",
            "expired",
            "disputed",
            "resolved",
        }
        actual = {s.value for s in EscrowStatus}
        assert actual == expected

    def test_from_string(self):
        assert EscrowStatus("pending") == EscrowStatus.PENDING
        assert EscrowStatus("released") == EscrowStatus.RELEASED


class TestDisputeRequest:
    def test_valid_dispute(self):
        d = DisputeRequest(service_hash="a" * 64, reason_hash="b" * 64)
        assert len(d.service_hash) == 64

    def test_short_reason_hash_rejected(self):
        with pytest.raises(ValidationError):
            DisputeRequest(service_hash="a" * 64, reason_hash="short")


class TestResolveRequest:
    def test_valid_resolve(self):
        r = ResolveRequest(
            service_hash="a" * 64,
            in_favor_of="sender",
            arbiter_pubkeys=["01" + "aa" * 32],
            arbiter_signatures=["01" + "bb" * 64],
        )
        assert r.in_favor_of == "sender"

    def test_invalid_in_favor_of(self):
        with pytest.raises(ValidationError):
            ResolveRequest(
                service_hash="a" * 64,
                in_favor_of="hacker",
                arbiter_pubkeys=[],
                arbiter_signatures=[],
            )


class TestReputationRecord:
    def test_defaults(self):
        rep = ReputationRecord(agent="test-agent")
        assert rep.completed == 0
        assert rep.score == 50

    def test_custom_values(self):
        rep = ReputationRecord(agent="a", completed=10, disputed=2, score=80)
        assert rep.completed == 10
        assert rep.disputed == 2
        assert rep.score == 80


class TestHealthResponse:
    def test_defaults(self):
        h = HealthResponse()
        assert h.status == "ok"
        assert h.version == "0.2.0"
        assert h.sandbox is True


class TestPaymentHeader:
    def test_defaults(self):
        ph = PaymentHeader(escrow_hash="abc", amount=100, sender="s", signature="sig")
        assert ph.version == "x402-v1"
        assert ph.timestamp == 0
        assert ph.nonce == ""

    def test_full_fields(self):
        ph = PaymentHeader(
            escrow_hash="h1",
            amount=999,
            sender="sender-x",
            signature="sig-y",
            timestamp=12345,
            nonce="n1",
        )
        assert ph.amount == 999
        assert ph.nonce == "n1"
