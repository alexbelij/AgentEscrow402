"""Opt-in live-testnet integration tests, gated by @pytest.mark.testnet.

These hit the real Casper testnet RPC fallback chain (see
`server/casper_client._build_rpc_endpoints`) instead of any mock/sandbox
state. They are NOT part of the default test run: `pyproject.toml` sets
`addopts = "... -m 'not testnet'"` so a normal `pytest` invocation (CI,
local dev) never depends on network access or a live node being up.

Run them explicitly with:

    pytest -m testnet tests/test_testnet_integration.py

Each test degrades to a `pytest.skip` (not a failure) when the testnet is
genuinely unreachable — a transient RPC outage shouldn't be reported the
same as a real regression in `CasperClient`. They only assert on properties
that hold regardless of which specific block/state we land on: shapes,
types, and known-deployed contract hashes staying queryable.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from server.casper_client import CasperClient
from server.config import Config

pytestmark = pytest.mark.testnet


@pytest.fixture
def live_config() -> Config:
    """Real testnet config — no private key needed, read-only RPC calls."""
    return Config(
        sandbox=False,
        casper_node_url="https://node.testnet.cspr.cloud/rpc",
        casper_chain_name="casper-test",
    )


# NOTE: async fixture generators MUST use @pytest_asyncio.fixture under
# pytest-asyncio's strict mode (see pyproject.toml -> asyncio_mode="strict").
# Plain @pytest.fixture with an async body was silently rejected at setup
# with "requested an async fixture ... with no plugin or hook that handled
# it" — the test would error before touching the network. This mistake in
# the original commit meant *none* of the four @testnet tests were actually
# runnable, defeating the purpose of the opt-in marker.
@pytest_asyncio.fixture
async def live_client(live_config: Config):
    client = CasperClient(live_config)
    yield client
    await client.close()


async def _skip_if_unreachable(coro):
    try:
        return await coro
    except RuntimeError as exc:
        pytest.skip(f"testnet RPC unreachable: {exc}")


class TestTestnetRpcFallback:
    """Exercise the real RPC fallback chain against live testnet nodes."""

    @pytest.mark.asyncio
    async def test_get_state_root_hash_returns_hex_string(self, live_client: CasperClient):
        state_root_hash = await _skip_if_unreachable(live_client._get_state_root_hash())
        assert isinstance(state_root_hash, str)
        assert len(state_root_hash) == 64
        int(state_root_hash, 16)  # raises ValueError if not valid hex

    @pytest.mark.asyncio
    async def test_chain_get_block_has_header(self, live_client: CasperClient):
        result = await _skip_if_unreachable(live_client._rpc("chain_get_block", {}))
        assert isinstance(result, dict)
        # Casper 2.x Version2 block shape (see _get_state_root_hash's own
        # primary/fallback parsing for why both shapes are checked).
        has_v2 = "block_with_signatures" in result
        has_legacy = "block" in result
        assert has_v2 or has_legacy, f"unexpected chain_get_block shape: {list(result.keys())}"


class TestTestnetInsurancePoolQuery:
    """Read-only queries against the live-deployed insurance-pool contract."""

    @pytest.mark.asyncio
    async def test_query_claims_dict_for_unknown_claimant_returns_none_or_empty(self, live_client: CasperClient):
        """A claimant with no prior claims should not blow up the query path --
        it should come back None (dictionary key absent) rather than raise."""
        raw = await _skip_if_unreachable(
            live_client.query_contract_dict(
                "claims",
                "0" * 64,  # account hash that has (almost certainly) never claimed
                contract_hash=live_client._insurance_contract_hash,
            )
        )
        assert raw is None or isinstance(raw, dict)

    @pytest.mark.asyncio
    async def test_confirm_wallet_insurance_claim_times_out_gracefully_for_unclaimed_escrow(
        self, live_client: CasperClient
    ):
        """No wallet ever claimed this synthetic escrow id -- the poll loop
        should run to completion and report not-confirmed, never raise."""
        confirmed, revert_reason = await _skip_if_unreachable(
            live_client.confirm_wallet_insurance_claim(
                "0" * 64,
                "nonexistent-escrow-id-for-testnet-integration-test",
                attempts=2,
                delay_seconds=0.1,
            )
        )
        assert confirmed is False
        assert revert_reason is None or isinstance(revert_reason, str)
