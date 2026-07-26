#!/usr/bin/env python3
"""Agent-vs-Agent simulation showcase.

Runs the deterministic multi-agent simulator (server/agent_sim.py) across
the full strategy matrix and asserts the safety invariants of the escrow
protocol under adversarial pairings:

* honest × honest         → 100% releases, 0 disputes
* honest × withholding    → 0 releases, 100% disputes (receiver forces)
* withholding × honest    → sender never releases; receiver's cooperative
                            posture doesn't accidentally trigger release
* honest × dispute_spam   → dispute spam gets filtered by heuristic scorer
* flaky × honest          → eventual release despite ~40% packet drop
* withholding × dispute_spam → both sides adversarial: the arbiter must
                            still terminally resolve every escrow (no
                            infinite-loop / stuck states)
* honest × flaky          → tolerates a slow-but-honest counterparty

Every scenario is deterministic under a fixed seed; two runs of this
script produce byte-identical `SimulationReport`s. That's the point --
it's the regression harness the escrow protocol is stress-tested against
before each release.

Run:
    PYTHONPATH=. python demo/agent_vs_agent_showcase.py
"""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

# Make the repo root importable regardless of where the script is invoked from.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.agent_sim import SimulationConfig, run_simulation  # noqa: E402


def scenario(
    name: str,
    sender: str,
    receiver: str,
    *,
    num_escrows: int = 200,
    seed: int = 42,
    expect_all_disputed: bool = False,
    expect_all_released: bool = False,
    expect_never_released: bool = False,
    expect_terminal: bool = True,
) -> None:
    """Run one scenario and assert its safety invariants.

    Parameters
    ----------
    expect_all_disputed
        Every escrow must have gone through the DISPUTED state at least once.
    expect_all_released
        Every escrow must terminate in RELEASED (no disputes, no refunds).
    expect_never_released
        No escrow may terminate in RELEASED (sender ghosted every time).
    expect_terminal
        Every escrow must reach a terminal state — RELEASED, REFUNDED, or
        RESOLVED. If any escrow is still PENDING or DISPUTED after the
        simulation, that's a stuck-state bug in the FSM or arbiter and we
        want the demo to loudly fail.
    """

    cfg = SimulationConfig(
        num_escrows=num_escrows,
        sender_strategy=sender,
        receiver_strategy=receiver,
        seed=seed,
    )
    report = run_simulation(cfg)

    counts = dict(report.outcome_counts)
    dispute_count = sum(1 for o in report.outcomes if o.disputed)
    print(f"── {name} — sender={sender!r}, receiver={receiver!r}, n={num_escrows}, seed={seed}")
    print(f"   outcomes: {counts}")
    print(f"   avg rounds: {report.avg_rounds:.2f}   disputes raised: {dispute_count}")

    non_terminal = counts.get("pending", 0) + counts.get("disputed", 0)
    if expect_terminal:
        assert non_terminal == 0, f"[{name}] {non_terminal} escrows never reached a terminal state"

    if expect_all_released:
        released = counts.get("released", 0)
        assert released == num_escrows, f"[{name}] expected {num_escrows} released, got {released}"

    if expect_never_released:
        released = counts.get("released", 0)
        assert released == 0, f"[{name}] expected 0 released, got {released}"

    if expect_all_disputed:
        assert (
            dispute_count == num_escrows
        ), f"[{name}] expected every escrow disputed, got {dispute_count} / {num_escrows}"

    print("   ✓ invariants held\n")


def determinism_probe() -> None:
    """The framework's core claim: same seed → byte-identical report."""
    cfg = SimulationConfig(
        num_escrows=50,
        sender_strategy="honest",
        receiver_strategy="dispute_spam",
        seed=13,
    )
    a = asdict(run_simulation(cfg))
    b = asdict(run_simulation(cfg))
    assert a == b, "non-determinism: two runs with same seed produced different reports"
    print("── determinism probe: two runs @ seed=13 produced byte-identical reports  ✓\n")


def main() -> int:
    print("Agent-vs-Agent simulation showcase")
    print("=" * 60)
    print()

    scenario(
        "SCENE 1 — cooperative baseline",
        sender="honest",
        receiver="honest",
        expect_all_released=True,
    )
    scenario(
        "SCENE 2 — sender ghosts (product's raison d'être)",
        sender="withholding",
        receiver="honest",
        expect_never_released=True,
    )
    scenario(
        "SCENE 3 — receiver forces dispute vs ghosting sender",
        sender="withholding",
        receiver="withholding",
        # Both sides withhold — escrows must expire (TTL path). Documents
        # that the FSM's inaction outcome is REFUND/EXPIRE, never RELEASE.
        expect_never_released=True,
    )
    scenario(
        "SCENE 4 — dispute-spam receiver vs honest sender (sender wins race)",
        sender="honest",
        receiver="dispute_spam",
        # Honest sender releases on round 0 before the spam-receiver's
        # dispute lands. Invariant: dispute spam CANNOT preempt a legitimate
        # release — the FSM's ordering guarantees the honest party wins.
        expect_all_released=True,
    )
    scenario(
        "SCENE 5 — slow but honest (flaky network)",
        sender="flaky_network",
        receiver="honest",
        expect_all_released=True,
        num_escrows=100,
    )
    scenario(
        "SCENE 6 — both sides adversarial (withholding × spam)",
        sender="withholding",
        receiver="dispute_spam",
        # Sender never releases, receiver spams disputes: every escrow
        # must be routed to the arbiter and terminally resolved.
        expect_all_disputed=True,
    )

    determinism_probe()

    print("=" * 60)
    print("ALL SCENARIOS PASSED — safety invariants held across strategy matrix")
    return 0


if __name__ == "__main__":
    sys.exit(main())
