"""AE-1: unit-contract tests for the `amount` / `amount_motes` wire alias.

The canonical wire field for value transfer is `amount_motes`. Existing
callers that still send `amount` must continue to work for one release
cycle. This module locks that contract in for every touched request
model.
"""

from __future__ import annotations

import time

import pytest

from server.app import app
from server.insurance import InsuranceDepositRequest
from server.models import BatchEscrowItem, EscrowRequest
from server.multi_asset import MultiAssetEscrowRequest, StreamEscrowRequest


class TestPydanticAlias:
    """Direct model construction must accept both wire names."""

    def test_escrow_request_amount_motes(self):
        r = EscrowRequest(receiver="a" * 64, amount_motes=1_000_000_000, service_hash="b" * 64)
        assert r.amount == 1_000_000_000

    def test_escrow_request_legacy_amount(self):
        r = EscrowRequest(receiver="a" * 64, amount=500_000, service_hash="b" * 64)
        assert r.amount == 500_000

    def test_batch_escrow_item_amount_motes(self):
        b = BatchEscrowItem(receiver="a" * 64, amount_motes=42, service_hash="b" * 64)
        assert b.amount == 42

    def test_batch_escrow_item_legacy_amount(self):
        b = BatchEscrowItem(receiver="a" * 64, amount=42, service_hash="b" * 64)
        assert b.amount == 42

    def test_insurance_deposit_amount_motes(self):
        d = InsuranceDepositRequest(amount_motes=1234)
        assert d.amount == 1234

    def test_insurance_deposit_legacy_amount(self):
        d = InsuranceDepositRequest(amount=5678)
        assert d.amount == 5678

    def test_multi_asset_amount_motes(self):
        r = MultiAssetEscrowRequest(
            receiver="a" * 64,
            amount_motes=999,
            token={"token_type": "cspr"},
            service_hash="b" * 64,
        )
        assert r.amount == 999

    def test_multi_asset_legacy_amount(self):
        r = MultiAssetEscrowRequest(
            receiver="a" * 64,
            amount=999,
            token={"token_type": "cspr"},
            service_hash="b" * 64,
        )
        assert r.amount == 999

    def test_stream_amount_motes(self):
        now = int(time.time())
        r = StreamEscrowRequest(
            receiver="a" * 64,
            amount_motes=10_000,
            token={"token_type": "cspr"},
            service_hash="b" * 64,
            start_time=now,
            end_time=now + 60,
        )
        assert r.amount == 10_000

    def test_stream_legacy_amount(self):
        now = int(time.time())
        r = StreamEscrowRequest(
            receiver="a" * 64,
            amount=10_000,
            token={"token_type": "cspr"},
            service_hash="b" * 64,
            start_time=now,
            end_time=now + 60,
        )
        assert r.amount == 10_000


class TestOpenAPICanonicalName:
    """OpenAPI must advertise `amount_motes` as the wire name, not `amount`."""

    def test_escrow_request_uses_amount_motes(self):
        spec = app.openapi()
        props = spec["components"]["schemas"]["EscrowRequest"]["properties"]
        assert "amount_motes" in props
        assert "amount" not in props  # only the aliased name is public
        desc = props["amount_motes"]["description"]
        assert "motes" in desc.lower()
        assert "amount_motes" in desc  # canonical name flagged
        assert "legacy" in desc.lower() or "alias" in desc.lower()

    def test_batch_item_uses_amount_motes(self):
        spec = app.openapi()
        props = spec["components"]["schemas"]["BatchEscrowItem"]["properties"]
        assert "amount_motes" in props
        assert "amount" not in props

    def test_insurance_deposit_uses_amount_motes(self):
        spec = app.openapi()
        props = spec["components"]["schemas"]["InsuranceDepositRequest"]["properties"]
        assert "amount_motes" in props
        assert "amount" not in props

    def test_multi_asset_uses_amount_motes(self):
        spec = app.openapi()
        props = spec["components"]["schemas"]["MultiAssetEscrowRequest"]["properties"]
        assert "amount_motes" in props
        assert "amount" not in props

    def test_stream_uses_amount_motes(self):
        spec = app.openapi()
        props = spec["components"]["schemas"]["StreamEscrowRequest"]["properties"]
        assert "amount_motes" in props
        assert "amount" not in props


class TestUnitInvariant:
    """`amount_motes` must always be a positive integer motes value."""

    def test_zero_rejected(self):
        with pytest.raises(ValueError):
            EscrowRequest(receiver="a" * 64, amount_motes=0, service_hash="b" * 64)

    def test_negative_rejected(self):
        with pytest.raises(ValueError):
            EscrowRequest(receiver="a" * 64, amount_motes=-1, service_hash="b" * 64)

    def test_one_cspr_is_1e9_motes(self):
        r = EscrowRequest(receiver="a" * 64, amount_motes=1_000_000_000, service_hash="b" * 64)
        assert r.amount == 1_000_000_000  # 1 CSPR

    def test_both_names_produce_same_value(self):
        r1 = EscrowRequest(receiver="a" * 64, amount_motes=777, service_hash="b" * 64)
        r2 = EscrowRequest(receiver="a" * 64, amount=777, service_hash="b" * 64)
        assert r1.amount == r2.amount == 777
