"""Tests for data models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.models import EscrowRequest, EscrowStatus, HealthResponse


class TestEscrowRequest:
    def test_valid_request(self):
        h = "a" * 64
        req = EscrowRequest(receiver="rcv", amount=1000, service_hash=h)
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

    def test_ttl_below_min_rejected(self):
        h = "a" * 64
        with pytest.raises(ValidationError):
            EscrowRequest(receiver="rcv", amount=100, service_hash=h, ttl=10)

    def test_ttl_above_max_rejected(self):
        h = "a" * 64
        with pytest.raises(ValidationError):
            EscrowRequest(receiver="rcv", amount=100, service_hash=h, ttl=100_000)


class TestEscrowStatus:
    def test_all_statuses(self):
        expected = {"pending", "released", "refunded", "expired", "disputed", "resolved"}
        actual = {s.value for s in EscrowStatus}
        assert actual == expected


class TestHealthResponse:
    def test_defaults(self):
        resp = HealthResponse()
        assert resp.status == "ok"
        assert resp.sandbox is True
