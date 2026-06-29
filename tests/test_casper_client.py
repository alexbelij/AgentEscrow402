"""Tests for Casper client wrapper."""

from __future__ import annotations

import pytest

from server.casper_client import CasperClient
from server.config import Config


class TestU512Bytes:
    """CasperClient._u512_bytes encodes U512 for CLValue."""

    def test_zero(self):
        assert CasperClient._u512_bytes(0) == "0100"

    def test_small_value(self):
        result = CasperClient._u512_bytes(255)
        assert result == "01ff"

    def test_multi_byte(self):
        result = CasperClient._u512_bytes(256)
        assert result == "020001"

    def test_large_value(self):
        result = CasperClient._u512_bytes(3_000_000_000)
        # 3B = 0xB2D05E00 → LE: 00 5E D0 B2
        assert len(result) > 2

    def test_one(self):
        result = CasperClient._u512_bytes(1)
        assert result == "0101"


class TestEncodeArgs:
    """CasperClient._encode_args builds runtime arg list."""

    def test_single_arg(self):
        args = {"amount": ("U512", "1000")}
        result = CasperClient._encode_args(args)
        assert len(result) == 1
        assert result[0][0] == "amount"
        assert result[0][1]["cl_type"] == "U512"
        assert result[0][1]["parsed"] == "1000"

    def test_multiple_args(self):
        args = {
            "receiver": ("String", "hash-abc"),
            "ttl": ("U64", "300"),
        }
        result = CasperClient._encode_args(args)
        assert len(result) == 2

    def test_empty_args(self):
        result = CasperClient._encode_args({})
        assert result == []


class TestIsoNow:
    def test_format(self):
        ts = CasperClient._iso_now()
        assert ts.endswith(".000Z")
        assert "T" in ts


class TestClientInit:
    def test_sandbox_config(self):
        cfg = Config(sandbox=True)
        client = CasperClient(cfg)
        assert client._chain == "casper-test"
        assert client._contract_hash == ""

    def test_custom_config(self):
        cfg = Config(
            casper_node_url="http://localhost:7777",
            contract_hash="abc123",
            casper_chain_name="my-chain",
        )
        client = CasperClient(cfg)
        assert client._chain == "my-chain"
        assert client._contract_hash == "abc123"

    def test_deploy_without_contract_hash_raises(self):
        cfg = Config(contract_hash="")
        client = CasperClient(cfg)
        with pytest.raises(RuntimeError, match="contract_hash"):
            import asyncio

            asyncio.get_event_loop().run_until_complete(
                client.deploy_transaction("test", {})
            )

    def test_deploy_without_key_raises(self):
        cfg = Config(contract_hash="abc", casper_private_key_path="")
        client = CasperClient(cfg)
        with pytest.raises(RuntimeError, match="private key"):
            import asyncio

            asyncio.get_event_loop().run_until_complete(
                client.deploy_transaction("test", {})
            )
