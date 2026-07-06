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
from server.models import EscrowRecord, EscrowStatus


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


class TestRunNodeScript:
    """`_run_node_script` shells out to a Node.js casper-js-sdk script for
    every real on-chain write (create_escrow, release, refund, dispute,
    resolve, set_arbiters, ...). These error branches (timeout, malformed
    output, script-reported failure) previously had zero test coverage even
    though they're exactly what runs against production."""

    @pytest.mark.asyncio
    async def test_timeout_raises_runtime_error(self, monkeypatch):
        import asyncio as _asyncio

        client = make_client()

        class _FakeProc:
            async def communicate(self):
                await _asyncio.sleep(999)

            def kill(self):
                self.killed = True

        fake_proc = _FakeProc()

        async def _fake_exec(*args, **kwargs):
            return fake_proc

        async def _fake_wait_for(coro, timeout):
            coro.close()
            raise _asyncio.TimeoutError()

        monkeypatch.setattr(_asyncio, "create_subprocess_exec", _fake_exec)
        monkeypatch.setattr(_asyncio, "wait_for", _fake_wait_for)

        with pytest.raises(RuntimeError, match="timed out"):
            await client._run_node_script(pathlib_dummy_script(), {})

    @pytest.mark.asyncio
    async def test_malformed_json_output_raises(self, monkeypatch):
        client = make_client()
        _patch_subprocess(monkeypatch, stdout=b"not json at all", stderr=b"")
        with pytest.raises(RuntimeError, match="Unexpected script output"):
            await client._run_node_script(pathlib_dummy_script(), {})

    @pytest.mark.asyncio
    async def test_script_reported_failure_raises(self, monkeypatch):
        client = make_client()
        _patch_subprocess(
            monkeypatch,
            stdout=b'{"success": false, "error": "insufficient funds"}',
            stderr=b"",
        )
        with pytest.raises(RuntimeError, match="insufficient funds"):
            await client._run_node_script(pathlib_dummy_script(), {})

    @pytest.mark.asyncio
    async def test_success_returns_hash(self, monkeypatch):
        client = make_client()
        _patch_subprocess(
            monkeypatch,
            stdout=b'{"success": true, "hash": "deploy-abc123"}',
            stderr=b"",
        )
        result = await client._run_node_script(pathlib_dummy_script(), {})
        assert result == "deploy-abc123"


def pathlib_dummy_script():
    import pathlib

    return pathlib.Path("/tmp/dummy_script.js")


def _patch_subprocess(monkeypatch, stdout: bytes, stderr: bytes):
    import asyncio as _asyncio

    class _FakeProc:
        async def communicate(self):
            return stdout, stderr

        def kill(self):
            pass

    async def _fake_exec(*args, **kwargs):
        return _FakeProc()

    async def _fake_wait_for(coro, timeout):
        return await coro

    monkeypatch.setattr(_asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(_asyncio, "wait_for", _fake_wait_for)


class TestLifecycleValidation:
    """release/refund/dispute all go through the shared `_lifecycle`
    helper, and resolve/commit_swap/reveal_swap have their own explicit
    guards -- none of these were exercised before (only create_escrow's
    validation had test coverage)."""

    @pytest.mark.asyncio
    async def test_release_requires_contract_hash(self):
        client = make_client()
        client._contract_hash = None
        with pytest.raises(RuntimeError, match="contract_hash"):
            await client.release("svc-1")

    @pytest.mark.asyncio
    async def test_release_requires_key_path(self):
        client = make_client()
        client._contract_hash = "contract-hash"
        client._key_path = None
        with pytest.raises(RuntimeError, match="private key"):
            await client.release("svc-1")

    @pytest.mark.asyncio
    async def test_release_success_passes_arbiter_lists(self):
        client = make_client()
        client._contract_hash = "contract-hash"
        client._key_path = "/tmp/key.pem"
        client._run_node_script = AsyncMock(return_value="deploy-release-1")
        result = await client.release("svc-1", arbiter_pubkeys=["01" + "aa" * 32], arbiter_signatures=["01" + "bb" * 64])
        assert result == "deploy-release-1"

    @pytest.mark.asyncio
    async def test_refund_requires_contract_hash(self):
        client = make_client()
        client._contract_hash = None
        with pytest.raises(RuntimeError, match="contract_hash"):
            await client.refund("svc-1")

    @pytest.mark.asyncio
    async def test_refund_success(self):
        client = make_client()
        client._contract_hash = "contract-hash"
        client._key_path = "/tmp/key.pem"
        client._run_node_script = AsyncMock(return_value="deploy-refund-1")
        assert await client.refund("svc-1") == "deploy-refund-1"

    @pytest.mark.asyncio
    async def test_dispute_requires_contract_hash(self):
        client = make_client()
        client._contract_hash = None
        with pytest.raises(RuntimeError, match="contract_hash"):
            await client.dispute("svc-1")

    @pytest.mark.asyncio
    async def test_dispute_success(self):
        client = make_client()
        client._contract_hash = "contract-hash"
        client._key_path = "/tmp/key.pem"
        client._run_node_script = AsyncMock(return_value="deploy-dispute-1")
        assert await client.dispute("svc-1") == "deploy-dispute-1"


class TestResolveValidation:
    @pytest.mark.asyncio
    async def test_requires_contract_hash(self):
        client = make_client()
        client._contract_hash = None
        with pytest.raises(RuntimeError, match="contract_hash"):
            await client.resolve("svc-1", "sender", ["pk"], ["sig"])

    @pytest.mark.asyncio
    async def test_requires_key_path(self):
        client = make_client()
        client._contract_hash = "contract-hash"
        client._key_path = None
        with pytest.raises(RuntimeError, match="private key"):
            await client.resolve("svc-1", "sender", ["pk"], ["sig"])

    @pytest.mark.asyncio
    async def test_rejects_invalid_in_favor_of(self):
        client = make_client()
        client._contract_hash = "contract-hash"
        client._key_path = "/tmp/key.pem"
        with pytest.raises(ValueError, match="in_favor_of"):
            await client.resolve("svc-1", "nobody", ["pk"], ["sig"])

    @pytest.mark.asyncio
    async def test_rejects_empty_arbiter_pubkeys(self):
        client = make_client()
        client._contract_hash = "contract-hash"
        client._key_path = "/tmp/key.pem"
        with pytest.raises(ValueError, match="non-empty"):
            await client.resolve("svc-1", "sender", [], [])

    @pytest.mark.asyncio
    async def test_rejects_mismatched_pubkey_signature_lengths(self):
        client = make_client()
        client._contract_hash = "contract-hash"
        client._key_path = "/tmp/key.pem"
        with pytest.raises(ValueError, match="same length"):
            await client.resolve("svc-1", "sender", ["pk1", "pk2"], ["sig1"])

    @pytest.mark.asyncio
    async def test_success(self):
        client = make_client()
        client._contract_hash = "contract-hash"
        client._key_path = "/tmp/key.pem"
        client._run_node_script = AsyncMock(return_value="deploy-resolve-1")
        result = await client.resolve("svc-1", "receiver", ["pk1"], ["sig1"])
        assert result == "deploy-resolve-1"


class TestAtomicSwapValidation:
    @pytest.mark.asyncio
    async def test_commit_swap_requires_contract_hash(self):
        client = make_client()
        client._contract_hash = None
        with pytest.raises(RuntimeError, match="contract_hash"):
            await client.commit_swap("svc-1", "commit-hash-abc")

    @pytest.mark.asyncio
    async def test_commit_swap_success(self):
        client = make_client()
        client._contract_hash = "contract-hash"
        client._key_path = "/tmp/key.pem"
        client._run_node_script = AsyncMock(return_value="deploy-commit-1")
        assert await client.commit_swap("svc-1", "commit-hash-abc") == "deploy-commit-1"

    @pytest.mark.asyncio
    async def test_reveal_swap_requires_contract_hash(self):
        client = make_client()
        client._contract_hash = None
        with pytest.raises(RuntimeError, match="contract_hash"):
            await client.reveal_swap("svc-1", "preimage-xyz")

    @pytest.mark.asyncio
    async def test_reveal_swap_success(self):
        client = make_client()
        client._contract_hash = "contract-hash"
        client._key_path = "/tmp/key.pem"
        client._run_node_script = AsyncMock(return_value="deploy-reveal-1")
        assert await client.reveal_swap("svc-1", "preimage-xyz") == "deploy-reveal-1"


def _fake_escrow_record(status: EscrowStatus = EscrowStatus.PENDING) -> EscrowRecord:
    return EscrowRecord(
        sender="sender-hash",
        receiver="receiver-hash",
        amount=1_000_000_000,
        service_hash="svc-wallet-1",
        status=status,
        created_at=1_700_000_000,
        ttl=3600,
    )


class TestGetDeployError:
    @pytest.mark.asyncio
    async def test_returns_none_on_rpc_error(self):
        client = make_client()
        client._rpc = AsyncMock(side_effect=RuntimeError("rpc down"))
        assert await client.get_deploy_error("deploy-1") is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_execution_results_yet(self):
        client = make_client()

        async def fake_rpc(method, params):
            if method == "info_get_transaction":
                raise RuntimeError("No such transaction")
            return {"execution_results": []}

        client._rpc = AsyncMock(side_effect=fake_rpc)
        assert await client.get_deploy_error("deploy-1") is None

    @pytest.mark.asyncio
    async def test_returns_none_on_success(self):
        client = make_client()

        async def fake_rpc(method, params):
            if method == "info_get_transaction":
                raise RuntimeError("No such transaction")
            return {"execution_results": [{"result": {"Success": {}}}]}

        client._rpc = AsyncMock(side_effect=fake_rpc)
        assert await client.get_deploy_error("deploy-1") is None

    @pytest.mark.asyncio
    async def test_returns_error_message_on_failure(self):
        client = make_client()

        async def fake_rpc(method, params):
            if method == "info_get_transaction":
                raise RuntimeError("No such transaction")
            return {
                "execution_results": [
                    {"result": {"Failure": {"error_message": "User error: 5"}}}
                ]
            }

        client._rpc = AsyncMock(side_effect=fake_rpc)
        assert await client.get_deploy_error("deploy-1") == "User error: 5"

    @pytest.mark.asyncio
    async def test_transaction_v1_not_yet_included_returns_none(self):
        client = make_client()
        client._rpc = AsyncMock(return_value={"execution_info": None})
        assert await client.get_deploy_error("tx-1") is None

    @pytest.mark.asyncio
    async def test_transaction_v1_returns_none_on_success(self):
        client = make_client()
        client._rpc = AsyncMock(
            return_value={
                "execution_info": {
                    "execution_result": {"Version2": {"error_message": None}}
                }
            }
        )
        assert await client.get_deploy_error("tx-1") is None

    @pytest.mark.asyncio
    async def test_transaction_v1_returns_error_message_on_failure(self):
        client = make_client()
        client._rpc = AsyncMock(
            return_value={
                "execution_info": {
                    "execution_result": {
                        "Version2": {"error_message": "User error: 8"}
                    }
                }
            }
        )
        assert await client.get_deploy_error("tx-1") == "User error: 8"


class TestConfirmWalletLifecycleTx:
    @pytest.mark.asyncio
    async def test_confirms_on_first_matching_status(self):
        client = make_client()
        client.get_escrow = AsyncMock(return_value=_fake_escrow_record(EscrowStatus.RELEASED))
        confirmed, reason = await client.confirm_wallet_lifecycle_tx(
            "svc-wallet-1", "released", attempts=3, delay_seconds=0
        )
        assert confirmed is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_times_out_and_reports_revert_reason(self):
        client = make_client()
        client.get_escrow = AsyncMock(return_value=_fake_escrow_record(EscrowStatus.PENDING))
        client.get_deploy_error = AsyncMock(return_value="User error: 7")
        confirmed, reason = await client.confirm_wallet_lifecycle_tx(
            "svc-wallet-1", "released", deploy_hash="deploy-abc", attempts=2, delay_seconds=0
        )
        assert confirmed is False
        assert reason == "User error: 7"

    @pytest.mark.asyncio
    async def test_times_out_without_deploy_hash_gives_no_reason(self):
        client = make_client()
        client.get_escrow = AsyncMock(return_value=None)
        confirmed, reason = await client.confirm_wallet_lifecycle_tx(
            "svc-wallet-1", "released", attempts=2, delay_seconds=0
        )
        assert confirmed is False
        assert reason is None


class TestConfirmWalletCreatedEscrow:
    @pytest.mark.asyncio
    async def test_confirms_once_record_exists_on_chain(self):
        client = make_client()
        client.get_escrow = AsyncMock(return_value=_fake_escrow_record())
        confirmed, reason = await client.confirm_wallet_created_escrow(
            "svc-wallet-1", attempts=3, delay_seconds=0
        )
        assert confirmed is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_times_out_and_reports_revert_reason(self):
        client = make_client()
        client.get_escrow = AsyncMock(return_value=None)
        client.get_deploy_error = AsyncMock(return_value="Mint error: 4 (InvalidAccessRights)")
        confirmed, reason = await client.confirm_wallet_created_escrow(
            "svc-wallet-1", deploy_hash="deploy-xyz", attempts=2, delay_seconds=0
        )
        assert confirmed is False
        assert reason == "Mint error: 4 (InvalidAccessRights)"

    @pytest.mark.asyncio
    async def test_times_out_without_deploy_hash_gives_no_reason(self):
        client = make_client()
        client.get_escrow = AsyncMock(return_value=None)
        confirmed, reason = await client.confirm_wallet_created_escrow(
            "svc-wallet-1", attempts=2, delay_seconds=0
        )
        assert confirmed is False
        assert reason is None


class TestDepositToInsurancePool:
    @pytest.mark.asyncio
    async def test_requires_package_hash(self):
        client = make_client()
        client._insurance_package_hash = ""
        client._key_path = "/tmp/key.pem"
        with pytest.raises(RuntimeError, match="insurance_package_hash"):
            await client.deposit_to_insurance_pool(1000)

    @pytest.mark.asyncio
    async def test_requires_key_path(self):
        client = make_client()
        client._insurance_package_hash = "pkg" * 20
        client._key_path = None
        with pytest.raises(RuntimeError, match="private key"):
            await client.deposit_to_insurance_pool(1000)

    @pytest.mark.asyncio
    async def test_requires_wasm_present(self, monkeypatch):
        import pathlib

        client = make_client()
        client._insurance_package_hash = "pkg" * 20
        client._key_path = "/tmp/key.pem"
        monkeypatch.setattr(pathlib.Path, "exists", lambda self: False)
        with pytest.raises(RuntimeError, match="pool-funder wasm"):
            await client.deposit_to_insurance_pool(1000)

    @pytest.mark.asyncio
    async def test_success_returns_hash(self, monkeypatch):
        import pathlib

        client = make_client()
        client._insurance_package_hash = "pkg" * 20
        client._key_path = "/tmp/key.pem"
        monkeypatch.setattr(pathlib.Path, "exists", lambda self: True)
        client._run_node_script = AsyncMock(return_value="deploy-pool-deposit-1")
        result = await client.deposit_to_insurance_pool(500_000_000)
        assert result == "deploy-pool-deposit-1"


class TestClaimFromInsurancePool:
    @pytest.mark.asyncio
    async def test_requires_contract_hash(self):
        client = make_client()
        client._insurance_contract_hash = ""
        client._key_path = "/tmp/key.pem"
        with pytest.raises(RuntimeError, match="insurance_contract_hash"):
            await client.claim_from_insurance_pool("e1", 1000, ["pk1"], ["sig1"])

    @pytest.mark.asyncio
    async def test_requires_key_path(self):
        client = make_client()
        client._insurance_contract_hash = "contract-hash"
        client._key_path = None
        with pytest.raises(RuntimeError, match="private key"):
            await client.claim_from_insurance_pool("e1", 1000, ["pk1"], ["sig1"])

    @pytest.mark.asyncio
    async def test_rejects_empty_or_mismatched_arbiter_lists(self):
        client = make_client()
        client._insurance_contract_hash = "contract-hash"
        client._key_path = "/tmp/key.pem"
        with pytest.raises(ValueError, match="arbiter_pubkeys"):
            await client.claim_from_insurance_pool("e1", 1000, [], [])
        with pytest.raises(ValueError, match="arbiter_pubkeys"):
            await client.claim_from_insurance_pool("e1", 1000, ["pk1", "pk2"], ["sig1"])

    @pytest.mark.asyncio
    async def test_success_returns_hash(self):
        client = make_client()
        client._insurance_contract_hash = "contract-hash"
        client._key_path = "/tmp/key.pem"
        client._run_node_script = AsyncMock(return_value="deploy-pool-claim-1")
        result = await client.claim_from_insurance_pool(
            "e1", 1000, ["pk1", "pk2", "pk3"], ["sig1", "sig2", "sig3"], evidence="proof"
        )
        assert result == "deploy-pool-claim-1"


class TestConfirmWalletInsuranceClaim:
    @pytest.mark.asyncio
    async def test_requires_insurance_contract_hash(self):
        client = make_client()
        client._insurance_contract_hash = ""
        confirmed, reason = await client.confirm_wallet_insurance_claim("aa" * 32, "e1")
        assert confirmed is False
        assert reason == "insurance contract hash not configured"

    @pytest.mark.asyncio
    async def test_strips_account_hash_prefix_before_querying(self):
        client = make_client()
        client._insurance_contract_hash = "contract-hash"
        seen_keys = []

        async def _fake_query(dict_name, key, contract_hash=None):
            seen_keys.append(key)
            return {"parsed": ["x", 0, "e1"]}

        client.query_contract_dict = _fake_query
        confirmed, reason = await client.confirm_wallet_insurance_claim(
            "account-hash-" + "aa" * 32, "e1", attempts=1, delay_seconds=0
        )
        assert confirmed is True
        assert reason is None
        assert seen_keys == ["aa" * 32]  # prefix stripped, not passed through raw

    @pytest.mark.asyncio
    async def test_times_out_and_reports_revert_reason(self):
        client = make_client()
        client._insurance_contract_hash = "contract-hash"
        client.query_contract_dict = AsyncMock(return_value=None)
        client.get_deploy_error = AsyncMock(return_value="User error: 8")
        confirmed, reason = await client.confirm_wallet_insurance_claim(
            "aa" * 32, "e1", deploy_hash="deploy-xyz", attempts=1, delay_seconds=0
        )
        assert confirmed is False
        assert reason == "User error: 8"
