"""Tests for the Casper client wrapper (server/casper_client.py).

Rewritten from scratch: the previous version of this file tested static
helpers (`_u512_bytes`, `_encode_args`, `_iso_now`) that no longer exist on
`CasperClient` — the client was refactored to shell out to Node.js
casper-js-sdk scripts for writes and use direct JSON-RPC for reads. These
tests cover the client's *current* real behavior: state-root-hash parsing
across Casper block format versions, on-chain dict parsing for escrows and
reputation, and input validation on `create_escrow`/lifecycle calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from server.casper_client import CasperClient
from server.config import Config
from server.models import EscrowStatus


def make_client() -> CasperClient:
    cfg = Config()
    return CasperClient(cfg)


class TestGetStateRootHash:
    @pytest.mark.asyncio
    async def test_version2_block_format(self):
        client = make_client()
        client._rpc = AsyncMock(
            return_value={
                "block_with_signatures": {
                    "block": {"Version2": {"header": {"state_root_hash": "abc123"}}}
                }
            }
        )
        result = await client._get_state_root_hash()
        assert result == "abc123"

    @pytest.mark.asyncio
    async def test_legacy_block_format_fallback(self):
        client = make_client()
        client._rpc = AsyncMock(
            return_value={"block": {"header": {"state_root_hash": "legacy456"}}}
        )
        result = await client._get_state_root_hash()
        assert result == "legacy456"

    @pytest.mark.asyncio
    async def test_unrecognized_format_raises(self):
        client = make_client()
        client._rpc = AsyncMock(return_value={"nonsense": True})
        with pytest.raises(RuntimeError, match="state_root_hash"):
            await client._get_state_root_hash()


class TestGetEscrow:
    @pytest.mark.asyncio
    async def test_parses_valid_dict_entry(self):
        client = make_client()
        client.query_contract_dict = AsyncMock(
            return_value={
                "parsed": [
                    ["sender-hash", "receiver-hash", "1000000000"],
                    ["svc-hash-1", 0, 1_700_000_000_000],
                    [3600, 250],
                ]
            }
        )
        record = await client.get_escrow("svc-hash-1")
        assert record is not None
        assert record.sender == "sender-hash"
        assert record.amount == 1000000000
        assert record.status == EscrowStatus.PENDING
        assert record.ttl == 3600

    @pytest.mark.asyncio
    async def test_missing_dict_entry_returns_none(self):
        client = make_client()
        client.query_contract_dict = AsyncMock(return_value=None)
        assert await client.get_escrow("missing") is None

    @pytest.mark.asyncio
    async def test_malformed_entry_returns_none(self):
        client = make_client()
        client.query_contract_dict = AsyncMock(return_value={"parsed": ["too", "short"]})
        assert await client.get_escrow("bad") is None

    @pytest.mark.asyncio
    async def test_status_int_mapping(self):
        client = make_client()
        client.query_contract_dict = AsyncMock(
            return_value={
                "parsed": [
                    ["s", "r", "1"],
                    ["svc", 4, 1000],
                    [10, 0],
                ]
            }
        )
        record = await client.get_escrow("svc")
        assert record.status == EscrowStatus.DISPUTED


class TestGetReputation:
    @pytest.mark.asyncio
    async def test_parses_valid_entry(self):
        client = make_client()
        # ReputationRecord.score is `int` — on-chain values are whole numbers.
        client.query_contract_dict = AsyncMock(
            return_value={"parsed": [5, 1, 0, 1_700_000_000, 87]}
        )
        rep = await client.get_reputation("agent-1")
        assert rep.completed == 5
        assert rep.disputed == 1
        assert rep.score == 87

    @pytest.mark.asyncio
    async def test_non_whole_score_falls_back_to_default(self):
        """Documents a real edge case: ReputationRecord.score is typed `int`,
        so a non-whole float from chain data fails pydantic validation and
        get_reputation silently falls back to the default record instead of
        raising. Worth revisiting if on-chain scores ever become fractional."""
        client = make_client()
        client.query_contract_dict = AsyncMock(
            return_value={"parsed": [5, 1, 0, 1_700_000_000, 87.5]}
        )
        rep = await client.get_reputation("agent-1")
        assert rep.completed == 0
        assert rep.score == 50

    @pytest.mark.asyncio
    async def test_missing_entry_returns_default(self):
        client = make_client()
        client.query_contract_dict = AsyncMock(return_value=None)
        rep = await client.get_reputation("agent-unknown")
        assert rep.agent == "agent-unknown"
        assert rep.completed == 0
        assert rep.score == 50


class TestCreateEscrowValidation:
    @pytest.mark.asyncio
    async def test_requires_contract_hash(self):
        client = make_client()
        client._contract_hash = None
        with pytest.raises(RuntimeError, match="contract_hash"):
            await client.create_escrow("s", "r" * 64, 1000, "svc", 3600)

    @pytest.mark.asyncio
    async def test_requires_valid_receiver_hex_length(self):
        client = make_client()
        client._contract_hash = "contract-hash"
        client._key_path = "/tmp/key.pem"
        with pytest.raises(ValueError, match="64-char hex"):
            await client.create_escrow("s", "too-short", 1000, "svc", 3600)

    @pytest.mark.asyncio
    async def test_strips_account_hash_prefix(self):
        client = make_client()
        client._contract_hash = "contract-hash"
        client._key_path = "/tmp/key.pem"
        client._run_node_script = AsyncMock(return_value="deploy-hash-xyz")
        receiver = "account-hash-" + "a" * 64
        result = await client.create_escrow("s", receiver, 1000, "svc", 3600)
        assert result == "deploy-hash-xyz"


class TestQueryContractDict:
    @pytest.mark.asyncio
    async def test_returns_none_on_rpc_error(self):
        client = make_client()
        client._get_state_root_hash = AsyncMock(side_effect=RuntimeError("rpc down"))
        result = await client.query_contract_dict("escrows", "svc-1")
        assert result is None
