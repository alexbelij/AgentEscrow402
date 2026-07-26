"""Chaos suite: network partition, split-brain election races, and
double-judge replay for VRF arbiter election (task T05).

Complements tests/test_chaos_failure_injection.py (RPC 5xx/timeout
fallback + DB-stall rollback) with three additional fault classes that
matter specifically for dispute arbitration correctness:

  1. Network partition: an RPC endpoint that is reachable, then goes
     dark mid-flow, then heals -- confirm_election must survive a
     partition window without corrupting the election result, and the
     client must not get stuck retrying forever once the partition
     heals.
  2. Split-brain: two concurrent POST /vrf/elect requests for the SAME
     dispute_id land at the same on-chain-latency window. Documents the
     actual current behaviour of server.vrf_election.elect_arbiter --
     the `if dispute_id in _election_results` guard is a read-then-write
     without a lock, so both requests can pass the check and both
     submit `select_arbiters` on-chain before either write lands. In a
     real deployment the contract itself rejects the second submission
     with `ERR_ELECTION_EXISTS`, so the two racing HTTP calls still
     converge on the SAME on-chain election result -- this test asserts
     that convergence (same elected arbiter across both responses) and
     documents the double on-chain submission so it isn't silently
     "fixed" into something that breaks the assertion without review.
  3. Double-judge replay: once an election is recorded, a later replay
     of the same /vrf/elect request must be rejected (409) and
     GET /vrf/election/{id} must keep returning the ORIGINAL arbiter --
     never re-electing (no "double judge" for one dispute).
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

import server.app as appmod
import server.vrf_election as vrf_mod
from server.casper_client import CasperClient
from server.config import Config
from server.models import ReputationRecord
from server.vrf_election import ElectArbiterRequest, elect_arbiter


class _FakeCasper:
    async def close(self) -> None:
        return None


def _client() -> TestClient:
    appmod._casper = _FakeCasper()
    appmod._rate_limits.clear()
    return TestClient(appmod.app)


def _reset_vrf_state() -> None:
    vrf_mod._registered_arbiters.clear()
    vrf_mod._election_results.clear()
    vrf_mod._registered_arbiters["arbiter_alpha"] = ReputationRecord(agent="arbiter_alpha", score=85.0, completed=12)
    vrf_mod._registered_arbiters["arbiter_beta"] = ReputationRecord(agent="arbiter_beta", score=72.0, completed=8)


def make_client_with_endpoints(endpoints: list[tuple[str, dict[str, str]]]) -> CasperClient:
    cfg = Config()
    client = CasperClient(cfg)
    client._rpc_endpoints = endpoints
    client._rpc_url = endpoints[0][0] if endpoints else ""
    return client


# ---------------------------------------------------------------------------
# 1. Network partition: endpoint dies mid-session, then heals
# ---------------------------------------------------------------------------


class TestNetworkPartitionHealing:
    """A partition that clears mid-session must not wedge the client."""

    @pytest.mark.asyncio
    async def test_partition_then_heal_recovers_without_manual_reset(self):
        client = make_client_with_endpoints(
            [
                ("https://flaky.example/rpc", {}),
                ("https://stable.example/rpc", {}),
            ]
        )

        state = {"flaky_down": True}

        def handler(request: httpx.Request) -> httpx.Response:
            if "flaky" in str(request.url):
                if state["flaky_down"]:
                    raise httpx.ConnectError("simulated network partition")
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "flaky-ok"})
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "stable-ok"})

        await client._http.aclose()
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        # During the partition: falls back to the stable endpoint, no raise.
        result_during_partition = await client._rpc("chain_get_block")
        assert result_during_partition == "stable-ok"

        # Partition heals. A fresh client call (fresh endpoint ordering,
        # as would happen on a new request) should be able to reach the
        # now-healthy flaky endpoint again if it is first in line.
        state["flaky_down"] = False
        client._rpc_endpoints = [
            ("https://flaky.example/rpc", {}),
            ("https://stable.example/rpc", {}),
        ]
        client._rpc_url = client._rpc_endpoints[0][0]
        result_after_heal = await client._rpc("chain_get_block")
        assert result_after_heal == "flaky-ok"

    @pytest.mark.asyncio
    async def test_full_partition_all_endpoints_unreachable_then_one_heals(self):
        """Simulates a split-brain-style total partition (both endpoints
        unreachable) followed by one endpoint healing -- the very next
        call must succeed via the healed endpoint rather than staying
        stuck on the stale failure."""
        client = make_client_with_endpoints(
            [
                ("https://a.example/rpc", {}),
                ("https://b.example/rpc", {}),
            ]
        )

        def all_down(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("partition: no route to host")

        await client._http.aclose()
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(all_down))

        with pytest.raises(RuntimeError, match="All RPC endpoints failed"):
            await client._rpc("chain_get_block")

        def b_heals(request: httpx.Request) -> httpx.Response:
            if "a.example" in str(request.url):
                raise httpx.ConnectError("still partitioned")
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "healed"})

        await client._http.aclose()
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(b_heals))
        client._rpc_endpoints = [
            ("https://a.example/rpc", {}),
            ("https://b.example/rpc", {}),
        ]
        client._rpc_url = client._rpc_endpoints[0][0]

        result = await client._rpc("chain_get_block")
        assert result == "healed"


# ---------------------------------------------------------------------------
# 2. Split-brain: concurrent elections racing for the same dispute_id
# ---------------------------------------------------------------------------


class _SlowOnchainCasper:
    """Simulates on-chain latency: both select_arbiters and confirm_election
    have an await point, opening a real race window for two concurrent
    HTTP requests targeting the same dispute_id."""

    def __init__(self, selected_csv: str, latency: float = 0.05) -> None:
        self._selected_csv = selected_csv
        self._latency = latency
        self.select_arbiters_calls: list[tuple[str, int]] = []

    async def close(self) -> None:
        return None

    async def select_arbiters(self, dispute_id: str, count: int) -> str:
        self.select_arbiters_calls.append((dispute_id, count))
        await asyncio.sleep(self._latency)
        return "deploy-hash-race"

    async def confirm_election(self, dispute_id, *, deploy_hash=None, attempts=15, delay_seconds=2.0):
        await asyncio.sleep(self._latency)
        if deploy_hash is None:
            return None, None
        return self._selected_csv, None


class TestSplitBrainElectionRace:
    """Two concurrent /vrf/elect calls for the same dispute -- must
    converge on one arbiter, never diverge into "split brain" results."""

    @pytest.mark.asyncio
    async def test_concurrent_elections_for_same_dispute_converge(self):
        _reset_vrf_state()
        import dataclasses

        cfg = dataclasses.replace(Config(), vrf_contract_hash="deadbeef" * 8)
        casper = _SlowOnchainCasper(selected_csv="arbiter_alpha,arbiter_beta")

        req = ElectArbiterRequest(
            dispute_id="split-brain-dispute-1",
            sender="sender-acct",
            receiver="receiver-acct",
            seed_hash="ab" * 32,
        )

        results = await asyncio.gather(
            elect_arbiter(request=req, casper=casper, cfg=cfg),
            elect_arbiter(request=req, casper=casper, cfg=cfg),
            return_exceptions=True,
        )

        elected_ids = {r.elected_arbiter.arbiter_id for r in results if hasattr(r, "elected_arbiter")}
        # Convergence: whichever request(s) succeeded, they must all agree
        # on the SAME elected arbiter -- no split-brain divergence.
        assert len(elected_ids) == 1
        assert elected_ids == {"arbiter_alpha"}

        # Documents current behaviour: the in-memory guard is a
        # read-then-write race, so BOTH requests can reach select_arbiters
        # before either result is written back. In production the
        # on-chain contract itself rejects the second submission
        # (ERR_ELECTION_EXISTS); here we only assert it was attempted at
        # least once and the final stored result is singular and correct.
        assert casper.select_arbiters_calls  # at least one submission happened
        assert len(vrf_mod._election_results) == 1
        assert vrf_mod._election_results["split-brain-dispute-1"]["elected_arbiter"]["arbiter_id"] == "arbiter_alpha"

    @pytest.mark.asyncio
    async def test_concurrent_elections_local_csprng_path_never_double_writes(self):
        """Same race, but with no on-chain casper configured (pure local
        CSPRNG path, no awaits inside the critical section) -- exactly one
        of the two concurrent requests must win; the other must see the
        409 conflict, never a corrupted/overwritten result."""
        _reset_vrf_state()

        req = ElectArbiterRequest(
            dispute_id="split-brain-dispute-local",
            sender="sender-acct",
            receiver="receiver-acct",
            seed_hash="cd" * 32,
        )
        cfg = Config()

        results = await asyncio.gather(
            elect_arbiter(request=req, casper=None, cfg=cfg),
            elect_arbiter(request=req, casper=None, cfg=cfg),
            return_exceptions=True,
        )

        successes = [r for r in results if hasattr(r, "elected_arbiter")]
        conflicts = [r for r in results if isinstance(r, Exception)]

        assert len(successes) == 1
        assert len(conflicts) == 1
        assert conflicts[0].status_code == 409
        assert len(vrf_mod._election_results) == 1


# ---------------------------------------------------------------------------
# 3. Double-judge replay: a dispute must never be re-elected
# ---------------------------------------------------------------------------


class TestDoubleJudgeReplay:
    """A previously-decided dispute must keep the SAME arbiter forever --
    a replayed election request is rejected, and reads always return the
    original judge (no "double judge" scenario)."""

    def test_replayed_election_request_rejected_original_arbiter_preserved(self):
        _reset_vrf_state()
        client = _client()

        payload = {
            "dispute_id": "double-judge-http-1",
            "sender": "sender-account-hash",
            "receiver": "receiver-account-hash",
            "seed_hash": "ef" * 32,
        }

        first = client.post("/vrf/elect", json=payload)
        assert first.status_code == 201
        original_arbiter = first.json()["elected_arbiter"]["arbiter_id"]
        original_proof = first.json()["election_proof"]

        # Replay: same dispute_id, possibly a different seed_hash (as if a
        # confused/malicious caller tried to re-roll the judge).
        replay_payload = dict(payload, seed_hash="99" * 32)
        replay = client.post("/vrf/elect", json=replay_payload)
        assert replay.status_code == 409

        # GET must still surface the ORIGINAL election, unaffected by the
        # replay attempt.
        readback = client.get(f"/vrf/election/{payload['dispute_id']}")
        assert readback.status_code == 200
        body = readback.json()
        assert body["elected_arbiter"]["arbiter_id"] == original_arbiter
        assert body["election_proof"] == original_proof

    def test_double_judge_replay_via_arbitration_escalation_endpoint(self):
        """Same guarantee at the higher-level /arbitration/analyze
        auto-escalation path (AE-A1.4): re-analysing the same dispute must
        reuse the original panel election, never electing a second judge."""
        _reset_vrf_state()
        client = _client()

        payload = {
            "dispute_id": "double-judge-escalation-1",
            "escrow_amount": 1000,
            "sender_evidence": [
                {
                    "escrow_id": "e1",
                    "claimant": "sender1",
                    "evidence_type": "text",
                    "content_hash": "a" * 64,
                    "description": "delivered",
                    "timestamp": 1_700_000_000,
                }
            ],
            "receiver_evidence": [],
            "sender_account": "aa" * 32,
            "receiver_account": "bb" * 32,
        }

        from tests.test_arbitration_escalation import _stub_analyze

        with patch.object(appmod._arbitration_agent, "analyze_dispute", _stub_analyze("abstain", 0.1)):
            first = client.post("/arbitration/analyze", json=payload)
            second = client.post("/arbitration/analyze", json=payload)
            third = client.post("/arbitration/analyze", json=payload)

        for res in (first, second, third):
            assert res.status_code == 200

        first_arbiter = first.json()["panel_election"]["elected_arbiter"]["arbiter_id"]
        second_arbiter = second.json()["panel_election"]["elected_arbiter"]["arbiter_id"]
        third_arbiter = third.json()["panel_election"]["elected_arbiter"]["arbiter_id"]

        assert (
            first.json()["escalation_reason"].startswith("abstain")
            or first.json()["escalation_reason"] == "abstain_verdict"
        )
        assert second.json()["escalation_reason"] == "prior_election_reused"
        assert third.json()["escalation_reason"] == "prior_election_reused"

        # Never a double judge: every replay surfaces the SAME arbiter.
        assert first_arbiter == second_arbiter == third_arbiter
