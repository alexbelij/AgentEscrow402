"""T3.5 — Agent-vs-Agent simulation framework (testing tool).

Deterministic multi-agent simulator that drives the *real* production
primitives (`EscrowFSM`, `ArbitrationAgent`/`_HeuristicArbitrator`) through
scripted agent strategies, so protocol changes get a repeatable, no-mocks
stress test of the sender/receiver/arbiter interaction surface before they
ship.

Design rules
------------

1. **No new business logic.** This module never re-implements escrow rules;
   every state change goes through :class:`server.escrow_fsm.EscrowFSM`, and
   every dispute goes through the same heuristic scorer production disputes
   use (`server.ai_arbitration._HeuristicArbitrator`, reached indirectly via
   a thin synchronous wrapper here since the simulator does not need the
   async LLM fallback chain — heuristic is deterministic and sufficient for
   reproducible simulation).
2. **Deterministic given a seed.** Two runs with the same
   `SimulationConfig.seed` produce byte-identical `SimulationReport`s. This
   is what makes the framework useful as a regression tool, not just a demo.
3. **Pluggable strategies.** An `AgentStrategy` is a pure function of
   `(role, escrow, rng) -> AgentAction`. Ships with four reference
   strategies (`HonestStrategy`, `WithholdingStrategy`, `DisputeSpamStrategy`,
   `FlakyNetworkStrategy`) that stress different failure modes; callers can
   register their own via `STRATEGY_REGISTRY`.
4. **Pure / no I/O.** No network, no DB, no time.sleep — `FlakyNetworkStrategy`
   *simulates* delay/drop by returning a `NOOP` action for a scripted number
   of rounds, it never actually sleeps. Fully unit-testable, fast (thousands
   of escrows/sec).

Typical use
-----------

    from server.agent_sim import SimulationConfig, run_simulation

    report = run_simulation(SimulationConfig(
        num_escrows=200,
        sender_strategy="honest",
        receiver_strategy="withholding",
        seed=42,
    ))
    report.outcome_counts  # {"released": 0, "disputed_resolved_sender": 190, ...}
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Final

from server.ai_arbitration import DisputeEvidence, _heuristic
from server.escrow_fsm import EscrowAction, EscrowFSM
from server.models import EscrowStatus

# ---------------------------------------------------------------------------
# Agent-facing vocabulary
# ---------------------------------------------------------------------------


class AgentRole(str, Enum):
    SENDER = "sender"
    RECEIVER = "receiver"


class AgentAction(str, Enum):
    """What a simulated agent decides to do this round.

    Distinct from `EscrowAction` (the FSM's vocabulary) — a strategy emits
    an `AgentAction`; the simulator engine translates it into zero or one
    `EscrowFSM.transition` calls plus any dispute-evidence bookkeeping.
    """

    RELEASE = "release"  # sender releases funds to receiver
    REFUND = "refund"  # sender takes a refund
    RAISE_DISPUTE = "raise_dispute"
    SUBMIT_EVIDENCE = "submit_evidence"
    NOOP = "noop"  # agent does nothing this round (delay/drop)


@dataclass(frozen=True)
class SimulatedEscrow:
    """Minimal escrow view the strategies get to see — intentionally not
    the full `EscrowRecord` API model; simulation only needs state + amount
    + a stable id, keeping strategies decoupled from wire-format churn."""

    escrow_id: str
    amount: int
    status: EscrowStatus
    round_no: int


# A strategy is a pure function: given the agent's role, its current view of
# the escrow, and a seeded RNG, return the action it takes this round.
AgentStrategy = Callable[[AgentRole, SimulatedEscrow, random.Random], AgentAction]


# ---------------------------------------------------------------------------
# Reference strategies
# ---------------------------------------------------------------------------


def honest_strategy(role: AgentRole, escrow: SimulatedEscrow, rng: random.Random) -> AgentAction:
    """Cooperative baseline: sender releases immediately, receiver never
    disputes. This is the control group every other strategy is compared
    against."""
    if role is AgentRole.SENDER and escrow.status is EscrowStatus.PENDING:
        return AgentAction.RELEASE
    return AgentAction.NOOP


def withholding_strategy(role: AgentRole, escrow: SimulatedEscrow, rng: random.Random) -> AgentAction:
    """Malicious sender: never releases, never refunds voluntarily — forces
    the receiver into a dispute. Models the "counterparty ghosts after
    taking the service" failure mode the escrow product exists to prevent."""
    if role is AgentRole.RECEIVER and escrow.status is EscrowStatus.PENDING and escrow.round_no >= 1:
        return AgentAction.RAISE_DISPUTE
    return AgentAction.NOOP


def dispute_spam_strategy(role: AgentRole, escrow: SimulatedEscrow, rng: random.Random) -> AgentAction:
    """Adversarial receiver: raises a dispute on round 0 regardless of
    sender behaviour, then floods weak/duplicate evidence. Stresses the
    arbitrator's repeat-dispute risk factor and its resistance to evidence
    padding (`_HeuristicArbitrator._score` dedup + volume-bonus cap)."""
    if role is AgentRole.RECEIVER:
        if escrow.status is EscrowStatus.PENDING:
            return AgentAction.RAISE_DISPUTE
        if escrow.status is EscrowStatus.DISPUTED:
            return AgentAction.SUBMIT_EVIDENCE
    return AgentAction.NOOP


def flaky_network_strategy(role: AgentRole, escrow: SimulatedEscrow, rng: random.Random) -> AgentAction:
    """Honest sender behind an unreliable network: drops ~40% of rounds
    (NOOP) before eventually releasing. Models latency/partition, not
    malice — checks the FSM and TTL/expire path tolerate a slow-but-honest
    counterparty without misclassifying it as withholding."""
    if role is AgentRole.SENDER and escrow.status is EscrowStatus.PENDING:
        if rng.random() < 0.4:
            return AgentAction.NOOP
        return AgentAction.RELEASE
    return AgentAction.NOOP


STRATEGY_REGISTRY: Final[dict[str, AgentStrategy]] = {
    "honest": honest_strategy,
    "withholding": withholding_strategy,
    "dispute_spam": dispute_spam_strategy,
    "flaky_network": flaky_network_strategy,
}


def register_strategy(name: str, strategy: AgentStrategy) -> None:
    """Register a custom strategy so `SimulationConfig(sender_strategy=name)`
    can reference it. Raises on name collision to avoid silently shadowing
    a reference strategy."""
    if name in STRATEGY_REGISTRY:
        raise ValueError(f"strategy '{name}' already registered")
    STRATEGY_REGISTRY[name] = strategy


# ---------------------------------------------------------------------------
# Simulation config / report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimulationConfig:
    num_escrows: int = 100
    sender_strategy: str = "honest"
    receiver_strategy: str = "honest"
    seed: int = 0
    max_rounds: int = 10
    """Rounds before an unresolved PENDING escrow is force-expired — models
    TTL expiry without needing wall-clock time."""
    base_amount: int = 1_000_000_000  # 1 CSPR in motes
    min_evidence_for_verdict: int = 1

    def __post_init__(self) -> None:
        if self.num_escrows < 1:
            raise ValueError("num_escrows must be >= 1")
        if self.max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        if self.sender_strategy not in STRATEGY_REGISTRY:
            raise ValueError(f"unknown sender_strategy: {self.sender_strategy!r}")
        if self.receiver_strategy not in STRATEGY_REGISTRY:
            raise ValueError(f"unknown receiver_strategy: {self.receiver_strategy!r}")


@dataclass
class EscrowOutcome:
    escrow_id: str
    final_status: EscrowStatus
    rounds_taken: int
    disputed: bool
    arbitration_recommendation: str | None = None
    arbitration_confidence: float | None = None


@dataclass
class SimulationReport:
    config: SimulationConfig
    outcomes: list[EscrowOutcome] = field(default_factory=list)

    @property
    def outcome_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for o in self.outcomes:
            key = f"disputed_{o.final_status.value}" if o.disputed else o.final_status.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    @property
    def dispute_rate(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(1 for o in self.outcomes if o.disputed) / len(self.outcomes)

    @property
    def avg_rounds(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(o.rounds_taken for o in self.outcomes) / len(self.outcomes)

    @property
    def report_hash(self) -> str:
        """Stable hash over the outcome sequence — two runs with the same
        seed/config must produce the same hash; used by the regression test
        to assert determinism without comparing full dataclass equality."""
        payload = "|".join(f"{o.escrow_id}:{o.final_status.value}:{o.rounds_taken}:{o.disputed}" for o in self.outcomes)
        return hashlib.sha256(payload.encode()).hexdigest()

    def summary(self) -> str:
        lines = [
            f"Simulation: {self.config.num_escrows} escrows | "
            f"sender={self.config.sender_strategy} receiver={self.config.receiver_strategy} "
            f"seed={self.config.seed}",
            f"Dispute rate: {self.dispute_rate:.1%} | Avg rounds: {self.avg_rounds:.2f}",
            f"Outcomes: {self.outcome_counts}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def _run_one_escrow(
    escrow_id: str,
    config: SimulationConfig,
    sender_fn: AgentStrategy,
    receiver_fn: AgentStrategy,
    rng: random.Random,
) -> EscrowOutcome:
    status = EscrowStatus.PENDING
    disputed = False
    sender_evidence: list[DisputeEvidence] = []
    receiver_evidence: list[DisputeEvidence] = []
    recommendation: str | None = None
    confidence: float | None = None
    round_no = 0

    for round_no in range(config.max_rounds):
        if EscrowFSM.is_terminal(status):
            break

        view = SimulatedEscrow(escrow_id=escrow_id, amount=config.base_amount, status=status, round_no=round_no)
        sender_action = sender_fn(AgentRole.SENDER, view, rng)
        receiver_action = receiver_fn(AgentRole.RECEIVER, view, rng)

        if status is EscrowStatus.PENDING:
            # Sender-initiated terminal actions take priority (matches the
            # production API: release/refund are sender-only endpoints);
            # a same-round dispute from the receiver is only honoured if
            # the sender did nothing.
            if sender_action is AgentAction.RELEASE and EscrowFSM.can_transition(status, EscrowAction.RELEASE):
                status = EscrowFSM.transition(status, EscrowAction.RELEASE)
                break
            if sender_action is AgentAction.REFUND and EscrowFSM.can_transition(status, EscrowAction.REFUND):
                status = EscrowFSM.transition(status, EscrowAction.REFUND)
                break
            if receiver_action is AgentAction.RAISE_DISPUTE and EscrowFSM.can_transition(status, EscrowAction.DISPUTE):
                status = EscrowFSM.transition(status, EscrowAction.DISPUTE)
                disputed = True
                continue
            # Neither side acted decisively this round — fall through to
            # the TTL/expire check below rather than spin forever.

        elif status is EscrowStatus.DISPUTED:
            if receiver_action is AgentAction.SUBMIT_EVIDENCE:
                receiver_evidence.append(
                    DisputeEvidence(
                        escrow_id=escrow_id,
                        claimant="receiver",
                        evidence_type="text",
                        content_hash=hashlib.sha256(f"{escrow_id}:{round_no}".encode()).hexdigest(),
                        description="simulated evidence",
                        timestamp=0,
                    )
                )
            if sender_action is AgentAction.SUBMIT_EVIDENCE:
                sender_evidence.append(
                    DisputeEvidence(
                        escrow_id=escrow_id,
                        claimant="sender",
                        evidence_type="text",
                        content_hash=hashlib.sha256(f"{escrow_id}:s:{round_no}".encode()).hexdigest(),
                        description="simulated evidence",
                        timestamp=0,
                    )
                )
            # A withholding sender never submits evidence — resolve once
            # the receiver has at least the configured minimum so the
            # simulation doesn't spin for `max_rounds` on every dispute.
            if len(sender_evidence) + len(receiver_evidence) >= config.min_evidence_for_verdict:
                verdict = _heuristic.analyze(
                    dispute_id=escrow_id,
                    sender_evidence=sender_evidence,
                    receiver_evidence=receiver_evidence,
                    escrow_amount=config.base_amount,
                )
                recommendation = verdict["recommendation"]
                confidence = verdict["confidence"]
                action = (
                    EscrowAction.RESOLVE_RECEIVER
                    if verdict["recommendation"] in ("favor_receiver", "split")
                    else EscrowAction.RESOLVE_SENDER
                )
                status = EscrowFSM.transition(status, action)
                break

    if not EscrowFSM.is_terminal(status):
        # Ran out of rounds unresolved — TTL expiry, the same fallback the
        # real product uses when a counterparty never responds.
        if EscrowFSM.can_transition(status, EscrowAction.EXPIRE):
            status = EscrowFSM.transition(status, EscrowAction.EXPIRE)

    return EscrowOutcome(
        escrow_id=escrow_id,
        final_status=status,
        rounds_taken=round_no + 1,
        disputed=disputed,
        arbitration_recommendation=recommendation,
        arbitration_confidence=confidence,
    )


def run_simulation(config: SimulationConfig) -> SimulationReport:
    """Run `config.num_escrows` independent escrow simulations and return
    the aggregate report. Deterministic: same config -> same report_hash.

    Each escrow gets its own child RNG derived from the master seed so
    outcomes don't depend on iteration order artifacts (e.g. adding an
    escrow at the end never perturbs earlier escrows' randomness)."""
    sender_fn = STRATEGY_REGISTRY[config.sender_strategy]
    receiver_fn = STRATEGY_REGISTRY[config.receiver_strategy]
    master_rng = random.Random(config.seed)

    outcomes: list[EscrowOutcome] = []
    for i in range(config.num_escrows):
        escrow_id = f"sim-{config.seed}-{i:06d}"
        child_seed = master_rng.randrange(2**32)
        child_rng = random.Random(child_seed)
        outcomes.append(_run_one_escrow(escrow_id, config, sender_fn, receiver_fn, child_rng))

    return SimulationReport(config=config, outcomes=outcomes)


__all__ = [
    "AgentAction",
    "AgentRole",
    "AgentStrategy",
    "EscrowOutcome",
    "STRATEGY_REGISTRY",
    "SimulatedEscrow",
    "SimulationConfig",
    "SimulationReport",
    "register_strategy",
    "run_simulation",
]
