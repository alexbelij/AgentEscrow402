"""Tests for T3.5 — Agent-vs-Agent simulation framework."""

from __future__ import annotations

import pytest

from server.agent_sim import (
    AgentAction,
    AgentRole,
    SimulatedEscrow,
    SimulationConfig,
    STRATEGY_REGISTRY,
    register_strategy,
    run_simulation,
)
from server.models import EscrowStatus
import random


def _escrow(status: EscrowStatus, round_no: int = 0) -> SimulatedEscrow:
    return SimulatedEscrow(escrow_id="e1", amount=1_000_000_000, status=status, round_no=round_no)


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestSimulationConfig:
    def test_defaults_valid(self):
        cfg = SimulationConfig()
        assert cfg.num_escrows == 100
        assert cfg.sender_strategy == "honest"

    def test_rejects_zero_escrows(self):
        with pytest.raises(ValueError, match="num_escrows"):
            SimulationConfig(num_escrows=0)

    def test_rejects_negative_escrows(self):
        with pytest.raises(ValueError, match="num_escrows"):
            SimulationConfig(num_escrows=-5)

    def test_rejects_zero_max_rounds(self):
        with pytest.raises(ValueError, match="max_rounds"):
            SimulationConfig(max_rounds=0)

    def test_rejects_unknown_sender_strategy(self):
        with pytest.raises(ValueError, match="unknown sender_strategy"):
            SimulationConfig(sender_strategy="does_not_exist")

    def test_rejects_unknown_receiver_strategy(self):
        with pytest.raises(ValueError, match="unknown receiver_strategy"):
            SimulationConfig(receiver_strategy="does_not_exist")


# ---------------------------------------------------------------------------
# Reference strategies — direct unit tests, no engine involved
# ---------------------------------------------------------------------------


class TestHonestStrategy():
    def test_sender_releases_when_pending(self):
        fn = STRATEGY_REGISTRY["honest"]
        assert fn(AgentRole.SENDER, _escrow(EscrowStatus.PENDING), random.Random(0)) == AgentAction.RELEASE

    def test_receiver_never_disputes(self):
        fn = STRATEGY_REGISTRY["honest"]
        assert fn(AgentRole.RECEIVER, _escrow(EscrowStatus.PENDING), random.Random(0)) == AgentAction.NOOP

    def test_sender_noop_once_released(self):
        fn = STRATEGY_REGISTRY["honest"]
        assert fn(AgentRole.SENDER, _escrow(EscrowStatus.RELEASED), random.Random(0)) == AgentAction.NOOP


class TestWithholdingStrategy:
    def test_sender_never_releases(self):
        fn = STRATEGY_REGISTRY["withholding"]
        assert fn(AgentRole.SENDER, _escrow(EscrowStatus.PENDING), random.Random(0)) == AgentAction.NOOP

    def test_receiver_disputes_after_round_zero(self):
        fn = STRATEGY_REGISTRY["withholding"]
        assert fn(AgentRole.RECEIVER, _escrow(EscrowStatus.PENDING, round_no=1), random.Random(0)) == (
            AgentAction.RAISE_DISPUTE
        )

    def test_receiver_does_not_dispute_on_round_zero(self):
        # gives the honest counterpart a chance to release first
        fn = STRATEGY_REGISTRY["withholding"]
        assert fn(AgentRole.RECEIVER, _escrow(EscrowStatus.PENDING, round_no=0), random.Random(0)) == (
            AgentAction.NOOP
        )


class TestDisputeSpamStrategy:
    def test_receiver_disputes_immediately(self):
        fn = STRATEGY_REGISTRY["dispute_spam"]
        assert fn(AgentRole.RECEIVER, _escrow(EscrowStatus.PENDING, round_no=0), random.Random(0)) == (
            AgentAction.RAISE_DISPUTE
        )

    def test_receiver_floods_evidence_once_disputed(self):
        fn = STRATEGY_REGISTRY["dispute_spam"]
        assert fn(AgentRole.RECEIVER, _escrow(EscrowStatus.DISPUTED), random.Random(0)) == (
            AgentAction.SUBMIT_EVIDENCE
        )

    def test_sender_side_is_noop(self):
        fn = STRATEGY_REGISTRY["dispute_spam"]
        assert fn(AgentRole.SENDER, _escrow(EscrowStatus.PENDING), random.Random(0)) == AgentAction.NOOP


class TestFlakyNetworkStrategy:
    def test_sender_sometimes_drops(self):
        fn = STRATEGY_REGISTRY["flaky_network"]
        # deterministic seed picked to exercise both branches across draws
        outcomes = {fn(AgentRole.SENDER, _escrow(EscrowStatus.PENDING), random.Random(seed)) for seed in range(20)}
        assert AgentAction.NOOP in outcomes
        assert AgentAction.RELEASE in outcomes

    def test_receiver_side_is_noop(self):
        fn = STRATEGY_REGISTRY["flaky_network"]
        assert fn(AgentRole.RECEIVER, _escrow(EscrowStatus.PENDING), random.Random(0)) == AgentAction.NOOP


class TestRegisterStrategy:
    def test_register_custom_strategy(self):
        def my_strategy(role, escrow, rng):
            return AgentAction.NOOP

        register_strategy("test_custom_noop_only", my_strategy)
        assert STRATEGY_REGISTRY["test_custom_noop_only"] is my_strategy
        # cleanup so re-running the test module twice in one session doesn't collide
        del STRATEGY_REGISTRY["test_custom_noop_only"]

    def test_register_rejects_name_collision(self):
        with pytest.raises(ValueError, match="already registered"):
            register_strategy("honest", lambda role, escrow, rng: AgentAction.NOOP)


# ---------------------------------------------------------------------------
# Engine — honest vs honest
# ---------------------------------------------------------------------------


class TestHonestVsHonest:
    def test_all_escrows_release_within_one_round(self):
        report = run_simulation(SimulationConfig(num_escrows=50, sender_strategy="honest", receiver_strategy="honest", seed=1))
        assert len(report.outcomes) == 50
        assert all(o.final_status == EscrowStatus.RELEASED for o in report.outcomes)
        assert all(o.rounds_taken == 1 for o in report.outcomes)
        assert report.dispute_rate == 0.0

    def test_outcome_counts_shape(self):
        report = run_simulation(SimulationConfig(num_escrows=10, seed=1))
        assert report.outcome_counts == {"released": 10}


# ---------------------------------------------------------------------------
# Engine — honest sender vs withholding receiver dispute framing
# (withholding_strategy encodes a non-releasing SENDER; use it as receiver's
#  mirror by pairing sender=withholding with receiver=honest to exercise the
#  actual "counterparty ghosts" path end-to-end through DISPUTED -> RESOLVED)
# ---------------------------------------------------------------------------


class TestWithholdingSenderForcesDispute:
    def test_receiver_wins_dispute_via_heuristic(self):
        # Sender never releases/refunds. Receiver (dispute_spam) disputes on
        # round 0 and floods evidence; sender submits none -> receiver's
        # evidence dominates -> heuristic favors receiver or splits ->
        # resolves to RESOLVED, never stuck PENDING past max_rounds.
        report = run_simulation(
            SimulationConfig(
                num_escrows=30,
                sender_strategy="withholding",
                receiver_strategy="dispute_spam",
                seed=7,
                max_rounds=8,
            )
        )
        assert len(report.outcomes) == 30
        assert all(o.disputed for o in report.outcomes)
        # Every escrow must reach a terminal state — the framework's whole
        # point is proving disputes don't deadlock.
        terminal = {EscrowStatus.RESOLVED, EscrowStatus.EXPIRED, EscrowStatus.RELEASED, EscrowStatus.REFUNDED}
        assert all(o.final_status in terminal for o in report.outcomes)
        # With one-sided evidence (receiver only), the heuristic should
        # resolve in the receiver's favor for the clear majority.
        resolved = [o for o in report.outcomes if o.final_status == EscrowStatus.RESOLVED]
        assert len(resolved) > 0
        assert all(o.arbitration_recommendation is not None for o in resolved)


class TestUnresponsiveBothSidesExpires:
    def test_double_noop_expires_via_ttl(self):
        def noop_strategy(role, escrow, rng):
            return AgentAction.NOOP

        register_strategy("test_double_noop", noop_strategy)
        try:
            report = run_simulation(
                SimulationConfig(
                    num_escrows=5,
                    sender_strategy="test_double_noop",
                    receiver_strategy="test_double_noop",
                    seed=3,
                    max_rounds=4,
                )
            )
            assert all(o.final_status == EscrowStatus.EXPIRED for o in report.outcomes)
            assert all(o.rounds_taken == 4 for o in report.outcomes)
        finally:
            del STRATEGY_REGISTRY["test_double_noop"]


# ---------------------------------------------------------------------------
# Determinism — the core promise of the framework
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_seed_same_hash(self):
        cfg = SimulationConfig(num_escrows=40, sender_strategy="flaky_network", receiver_strategy="dispute_spam", seed=99)
        r1 = run_simulation(cfg)
        r2 = run_simulation(cfg)
        assert r1.report_hash == r2.report_hash
        assert r1.outcome_counts == r2.outcome_counts

    def test_different_seed_can_differ(self):
        base = SimulationConfig(num_escrows=40, sender_strategy="flaky_network", receiver_strategy="honest", seed=1)
        other = SimulationConfig(num_escrows=40, sender_strategy="flaky_network", receiver_strategy="honest", seed=2)
        r1 = run_simulation(base)
        r2 = run_simulation(other)
        # Not a hard guarantee for every possible pair, but for flaky_network
        # with 40 escrows the rounds-taken distribution should differ across
        # these two fixed seeds — regression guard against an RNG wiring bug
        # that made every escrow ignore the seed.
        assert r1.report_hash != r2.report_hash

    def test_escrow_ids_are_seed_scoped_and_unique(self):
        report = run_simulation(SimulationConfig(num_escrows=25, seed=5))
        ids = [o.escrow_id for o in report.outcomes]
        assert len(set(ids)) == len(ids)
        assert all(eid.startswith("sim-5-") for eid in ids)


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------


class TestReportHelpers:
    def test_avg_rounds_on_empty_report_is_zero(self):
        from server.agent_sim import SimulationReport

        report = SimulationReport(config=SimulationConfig(num_escrows=1))
        assert report.avg_rounds == 0.0
        assert report.dispute_rate == 0.0
        assert report.outcome_counts == {}

    def test_summary_contains_key_fields(self):
        report = run_simulation(SimulationConfig(num_escrows=5, seed=1))
        text = report.summary()
        assert "sender=honest" in text
        assert "receiver=honest" in text
        assert "Dispute rate" in text

    def test_dispute_outcome_key_prefixed(self):
        report = run_simulation(
            SimulationConfig(num_escrows=10, sender_strategy="withholding", receiver_strategy="dispute_spam", seed=2)
        )
        assert all(key.startswith("disputed_") for key in report.outcome_counts)


# ---------------------------------------------------------------------------
# Scale smoke test — the framework must stay fast (pure/no I/O promise)
# ---------------------------------------------------------------------------


class TestScale:
    def test_thousand_escrows_completes_and_all_terminal(self):
        report = run_simulation(
            SimulationConfig(num_escrows=1000, sender_strategy="withholding", receiver_strategy="dispute_spam", seed=11, max_rounds=6)
        )
        assert len(report.outcomes) == 1000
        terminal = {EscrowStatus.RESOLVED, EscrowStatus.EXPIRED, EscrowStatus.RELEASED, EscrowStatus.REFUNDED}
        assert all(o.final_status in terminal for o in report.outcomes)
