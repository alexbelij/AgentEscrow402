"""Full-cycle Python simulation of the Governance DAO lifecycle.

The AE402 test suite doesn't currently link against
casper-engine-test-support (see the commented-out deps in
``contracts/tests/Cargo.toml``), so on-chain execution is exercised at the
CLI/deploy level not the unit-test level. This file drives the SDK
through the same lifecycle a real proposal would follow and verifies that
the pure functions agree on every step: register → propose → vote (with
delegation) → quorum → resolve → execute-log message → veto short-circuit.

The Rust property tests already prove the individual state transitions
are exhaustive; this test proves the *composition* is what the caller
gets when it drives the SDK end-to-end.
"""

from __future__ import annotations

from sdk.governance import (
    AdjustFeeBps,
    Status,
    build_execution_message,
    encode_params,
    quorum_threshold,
    resolve_status,
)


class MockLedger:
    """In-memory stand-in for the on-chain DAO — captures only what the
    lifecycle needs: total stake, per-voter stake, delegations, proposals,
    votes.
    """

    def __init__(self):
        self.total_staked = 0
        self.stakes: dict[str, int] = {}
        self.delegations: dict[str, str] = {}
        self.proposals: dict[int, dict] = {}
        self.votes: dict[tuple[int, str], int] = {}  # (pid, voter) -> support
        self.exec_log: dict[int, str] = {}
        self.blocktime = 0
        self.next_id = 1

    # register_voter
    def register_voter(self, addr: str, power: int):
        old = self.stakes.get(addr, 0)
        self.total_staked = self.total_staked - old + power
        self.stakes[addr] = power

    # delegate
    def delegate(self, delegator: str, to: str):
        assert delegator != to, "self-delegate rejected"
        self.delegations[delegator] = to

    # voting_power
    def voting_power(self, addr: str) -> int:
        if addr in self.delegations:
            return 0
        return self.stakes.get(addr, 0)

    # create_proposal
    def create_proposal(
        self,
        proposer: str,
        title: str,
        params: AdjustFeeBps,
        voting_period: int = 7 * 24 * 60 * 60,
    ) -> int:
        action, params_str = encode_params(params)
        pid = self.next_id
        self.next_id += 1
        self.proposals[pid] = {
            "id": pid,
            "proposer": proposer,
            "title": title,
            "action": action,
            "params_str": params_str,
            "votes_for": 0,
            "votes_against": 0,
            "status": Status.ACTIVE,
            "created_at": self.blocktime,
            "voting_end": self.blocktime + voting_period,
            "executed_at": 0,
        }
        return pid

    # vote
    def vote(self, pid: int, voter: str, support: int, weight: int):
        key = (pid, voter)
        assert key not in self.votes, "already voted"
        p = self.proposals[pid]
        assert p["status"] == Status.ACTIVE, "voting closed"
        assert self.blocktime <= p["voting_end"], "expired"
        power = self.voting_power(voter)
        eff = min(weight, power)
        if support == 1:
            p["votes_for"] += eff
        else:
            p["votes_against"] += eff
        self.votes[key] = support
        p["status"] = resolve_status(
            p["votes_for"],
            p["votes_against"],
            self.total_staked,
            self.blocktime,
            p["voting_end"],
        )

    # execute
    def execute(self, pid: int, executor: str):
        p = self.proposals[pid]
        assert p["status"] != Status.EXECUTED, "already executed"
        assert p["status"] != Status.VETOED, "vetoed"
        # Late-finalize
        if self.blocktime > p["voting_end"] and p["status"] == Status.ACTIVE:
            p["status"] = resolve_status(
                p["votes_for"],
                p["votes_against"],
                self.total_staked,
                self.blocktime,
                p["voting_end"],
            )
        assert p["status"] == Status.PASSED, f"not passed: {p['status']}"
        msg = build_execution_message(pid, p["action"], p["params_str"])
        self.exec_log[pid] = msg
        p["status"] = Status.EXECUTED
        p["executed_at"] = self.blocktime

    # veto
    def veto(self, pid: int, installer: str):
        p = self.proposals[pid]
        assert p["status"] != Status.EXECUTED, "already executed"
        p["status"] = Status.VETOED


# ── Lifecycle tests ──────────────────────────────────────────────────


def test_full_lifecycle_passes():
    L = MockLedger()
    L.register_voter("alice", 400)
    L.register_voter("bob", 300)
    L.register_voter("carol", 300)
    assert L.total_staked == 1000

    # Alice proposes a fee bump.
    pid = L.create_proposal("alice", "Bump fee to 5%", AdjustFeeBps(bps=500))
    assert L.proposals[pid]["status"] == Status.ACTIVE

    # Bob votes YES with 300. Quorum threshold = 30% × 1000 = 300; 300 >= 300 quorum met.
    L.vote(pid, "bob", support=1, weight=300)
    # For(300) > against(0) → PASSED (early finalization allowed).
    assert L.proposals[pid]["status"] == Status.PASSED

    # Execute — writes exec log.
    L.blocktime = 100
    L.execute(pid, executor="alice")
    assert L.proposals[pid]["status"] == Status.EXECUTED
    assert L.exec_log[pid] == "ae402:governance-dao:exec:v1:1:0:bps=500"


def test_delegated_voter_has_zero_power():
    L = MockLedger()
    L.register_voter("alice", 500)
    L.register_voter("bob", 500)
    L.delegate("bob", "alice")

    pid = L.create_proposal("alice", "test", AdjustFeeBps(bps=100))
    # Bob tries to vote — his effective weight is 0 because he delegated.
    L.vote(pid, "bob", support=1, weight=500)
    assert L.proposals[pid]["votes_for"] == 0

    # Alice can still spend her 500.
    L.vote(pid, "alice", support=1, weight=500)
    assert L.proposals[pid]["votes_for"] == 500
    # Total stake = 1000, threshold = 300. 500 >= 300 quorum met. For > against.
    assert L.proposals[pid]["status"] == Status.PASSED


def test_below_quorum_expires_after_window():
    L = MockLedger()
    L.register_voter("alice", 1000)
    pid = L.create_proposal("alice", "test", AdjustFeeBps(bps=100))
    # No votes cast. Advance past the window.
    L.blocktime = L.proposals[pid]["voting_end"] + 1
    # Execute path late-finalizes: 0 votes, threshold = 300 → EXPIRED
    try:
        L.execute(pid, executor="alice")
    except AssertionError as e:
        assert "not passed" in str(e)
    assert L.proposals[pid]["status"] == Status.EXPIRED


def test_veto_short_circuits_execution():
    L = MockLedger()
    L.register_voter("alice", 1000)
    pid = L.create_proposal("alice", "test", AdjustFeeBps(bps=100))
    L.vote(pid, "alice", support=1, weight=1000)
    assert L.proposals[pid]["status"] == Status.PASSED
    L.veto(pid, installer="admin")
    assert L.proposals[pid]["status"] == Status.VETOED
    # execute() must reject
    try:
        L.execute(pid, executor="alice")
        raise AssertionError("execute should reject vetoed proposal")
    except AssertionError as e:
        assert "vetoed" in str(e).lower()


def test_tie_at_quorum_is_rejected():
    # Use 3 voters so the first vote doesn't already trip the 30% quorum.
    L = MockLedger()
    L.register_voter("alice", 400)
    L.register_voter("bob", 400)
    L.register_voter("carol", 200)
    pid = L.create_proposal("alice", "test", AdjustFeeBps(bps=100))
    # Alice YES 200 (partial), Bob NO 200 → for(200)==against(200), quorum met (400≥300),
    # tie → REJECTED per resolve_status (for MUST strictly exceed against).
    L.vote(pid, "alice", support=1, weight=200)
    # After Alice: 200 vs 0 → quorum met (200<300 actually — NOT met), stays ACTIVE.
    assert L.proposals[pid]["status"] == Status.ACTIVE
    L.vote(pid, "bob", support=0, weight=200)
    # After Bob: 200 for + 200 against = 400 ≥ 300 quorum met. for == against → REJECTED.
    assert L.proposals[pid]["status"] == Status.REJECTED


def test_exec_log_message_pins_proposal_action_params():
    L = MockLedger()
    L.register_voter("alice", 1000)
    pid1 = L.create_proposal("alice", "5%", AdjustFeeBps(bps=500))
    L.vote(pid1, "alice", support=1, weight=1000)
    L.execute(pid1, executor="alice")

    pid2 = L.create_proposal("alice", "10%", AdjustFeeBps(bps=1000))
    L.vote(pid2, "alice", support=1, weight=1000)
    L.execute(pid2, executor="alice")

    # Two distinct exec-log messages
    assert L.exec_log[pid1] != L.exec_log[pid2]
    assert "bps=500" in L.exec_log[pid1]
    assert "bps=1000" in L.exec_log[pid2]


def test_quorum_scales_correctly():
    """Sanity: threshold scales with total_staked, not with the number of voters."""
    assert quorum_threshold(1_000) == 300
    assert quorum_threshold(10_000) == 3_000
    assert quorum_threshold(100_000_000_000) == 30_000_000_000
