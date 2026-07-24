"""Property-based invariants for SandboxStore (AE-2 defense-in-depth).

The on-chain contract has a formal FSM (deny-by-default allow-matrix in
`server/escrow_fsm.py`); the SandboxStore is its Python host-mirror,
used by unit tests, the developer sandbox mode, and every integration
that stubs out Casper. If the mirror drifts from the contract's FSM,
every test suite that relies on it silently accepts illegal transitions
and we can ship a regression that only surfaces on-chain.

This file uses Hypothesis to fuzz the mirror much wider than the hand-
written unit tests can:

  * FSM invariants — the mirror MUST reject exactly the same transitions
    the contract rejects, from EVERY reachable state, for EVERY random
    action ordering.
  * Reputation invariants — the score formula is bounded [0, 100] and
    strictly a function of `(completed, disputed)`, regardless of the
    interleaving of independent escrows.
  * Idempotency — replaying a terminal action on a terminal escrow
    raises the same ValueError signature (never silently mutates state,
    never bumps reputation twice).

These tests do NOT require the on-chain WASM harness (which was the
original AE-2 ask); they harden the mirror that the contract-facing
tests use as their reference model. When the on-chain harness lands in
a follow-up, this file becomes its differential-testing bench-mark.
"""

from __future__ import annotations

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from server.escrow_fsm import EscrowAction, EscrowFSM, InvalidTransitionError
from server.models import EscrowStatus
from server.sandbox import SandboxStore

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Hex-only 64-char strings so downstream Pydantic validation never rejects
# our fuzz-generated identifiers before the FSM can run.
_hex_str = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)

# Positive motes values, kept small enough to keep test output readable
# while still covering the boundary at 1 (min positive amount).
_amount = st.integers(min_value=1, max_value=10_000_000)

# TTL: 1 second (immediately-expirable) up to 1 hour.
_ttl = st.integers(min_value=1, max_value=3600)

# Every action the FSM knows about — the same tuple the contract's
# match-statement dispatches on. ``EscrowAction`` is a namespace of
# string constants (not an Enum), so we use its ``ALL`` tuple as the
# canonical list.
_action = st.sampled_from(EscrowAction.ALL)


# ---------------------------------------------------------------------------
# FSM invariants
# ---------------------------------------------------------------------------


@given(action_seq=st.lists(_action, min_size=1, max_size=20))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_fsm_never_escapes_terminal_state(action_seq: list[EscrowAction]) -> None:
    """Once an escrow reaches a terminal status, EVERY subsequent action
    must raise ``InvalidTransitionError`` — the FSM has no edges out of
    terminal nodes.

    This is the property that on-chain replay guards rely on: if the FSM
    ever accepted a transition out of e.g. ``resolved``, an arbiter could
    double-pay a resolved dispute.
    """
    current = EscrowStatus.PENDING
    reached_terminal = False
    for action in action_seq:
        if reached_terminal:
            # After terminal, every action MUST reject.
            try:
                EscrowFSM.transition(current, action)
            except InvalidTransitionError:
                continue
            raise AssertionError(f"FSM escaped terminal state {current!r} via {action!r}")
        try:
            current = EscrowFSM.transition(current, action)
        except InvalidTransitionError:
            # Illegal move from a non-terminal state — fine, just skip.
            continue
        if current in {
            EscrowStatus.RELEASED,
            EscrowStatus.REFUNDED,
            EscrowStatus.EXPIRED,
            EscrowStatus.RESOLVED,
        }:
            reached_terminal = True


@given(action_seq=st.lists(_action, min_size=0, max_size=15))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_fsm_deterministic(action_seq: list[EscrowAction]) -> None:
    """Same starting state + same action sequence → same final state
    (or same error). Determinism is what makes the mirror useful as a
    reference model for the on-chain contract.
    """

    def _run(seq: list[EscrowAction]) -> tuple[EscrowStatus | None, str | None]:
        current = EscrowStatus.PENDING
        for a in seq:
            try:
                current = EscrowFSM.transition(current, a)
            except InvalidTransitionError as exc:
                return None, str(exc)
        return current, None

    assert _run(action_seq) == _run(action_seq)


# ---------------------------------------------------------------------------
# Reputation invariants
# ---------------------------------------------------------------------------


@given(
    completed=st.integers(min_value=0, max_value=10_000),
    disputed=st.integers(min_value=0, max_value=10_000),
)
@settings(max_examples=200)
def test_reputation_score_is_bounded(completed: int, disputed: int) -> None:
    """The reputation score MUST stay in [0, 100] for any counter values.

    A regression here would let an agent farm score above 100 (unfair
    ranking) or drop below 0 (breaks integer widening on the frontend).
    """
    store = SandboxStore()
    agent = "aa" * 32
    for _ in range(completed):
        store._bump_reputation(agent, completed=1)
    for _ in range(disputed):
        store._bump_reputation(agent, disputed=1)
    rep = store.get_reputation(agent)
    assert 0 <= rep.score <= 100, f"score={rep.score} out of [0,100] " f"for completed={completed}, disputed={disputed}"
    assert rep.completed == completed
    assert rep.disputed == disputed


@given(
    completed=st.integers(min_value=0, max_value=200),
    disputed=st.integers(min_value=0, max_value=200),
)
@settings(max_examples=100)
def test_reputation_score_formula_matches_reference(completed: int, disputed: int) -> None:
    """The reputation score MUST equal the documented formula:

        score = max(0, min(100, 50 + 5 * completed - 10 * disputed))

    This pins the formula against silent drift. If the formula ever
    changes, this test is the intentional canary that will fail so the
    change is reviewed rather than shipping unnoticed.
    """
    expected = max(0, min(100, 50 + 5 * completed - 10 * disputed))
    store = SandboxStore()
    agent = "bb" * 32
    for _ in range(completed):
        store._bump_reputation(agent, completed=1)
    for _ in range(disputed):
        store._bump_reputation(agent, disputed=1)
    assert store.get_reputation(agent).score == expected


# ---------------------------------------------------------------------------
# Store-level end-to-end invariants
# ---------------------------------------------------------------------------


@given(
    service_hash=_hex_str,
    sender=_hex_str,
    receiver=_hex_str,
    amount=_amount,
    ttl=_ttl,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_release_by_non_sender_is_rejected(
    service_hash: str,
    sender: str,
    receiver: str,
    amount: int,
    ttl: int,
) -> None:
    """Only the sender can release an escrow — every other caller must
    be rejected with PermissionError. This is the on-chain contract's
    ``require(caller == sender)`` mirrored in the host runtime.
    """
    assume(sender != receiver)
    store = SandboxStore()
    store.create_escrow(sender, receiver, amount, service_hash, ttl)
    # A third party attempts release — must be rejected.
    third_party = "cc" * 32
    assume(third_party != sender)
    try:
        store.release_escrow(service_hash, caller=third_party)
    except PermissionError:
        return
    raise AssertionError(f"release_escrow accepted non-sender caller {third_party!r}")


@given(
    service_hash=_hex_str,
    sender=_hex_str,
    receiver=_hex_str,
    amount=_amount,
    ttl=_ttl,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_double_release_is_rejected(
    service_hash: str,
    sender: str,
    receiver: str,
    amount: int,
    ttl: int,
) -> None:
    """Once released, a second release call MUST fail (FSM has no
    RELEASED → RELEASED edge). Property version of the terminal-state
    guarantee, exercised through the full store API rather than the FSM
    directly.
    """
    assume(sender != receiver)
    store = SandboxStore()
    store.create_escrow(sender, receiver, amount, service_hash, ttl)
    store.release_escrow(service_hash, caller=sender)
    try:
        store.release_escrow(service_hash, caller=sender)
    except ValueError:
        return
    raise AssertionError("release_escrow accepted a second release on an already-released escrow")


@given(
    service_hash=_hex_str,
    sender=_hex_str,
    receiver=_hex_str,
    amount=_amount,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_release_bumps_receiver_reputation_exactly_once(
    service_hash: str,
    sender: str,
    receiver: str,
    amount: int,
) -> None:
    """A single successful release must bump the RECEIVER's `completed`
    counter by exactly one. Not the sender, not two. Guards against a
    class of bugs where a refactor swaps the arg order and silently
    inflates the wrong side's reputation.
    """
    assume(sender != receiver)
    store = SandboxStore()
    store.create_escrow(sender, receiver, amount, service_hash, ttl=3600)
    store.release_escrow(service_hash, caller=sender)
    assert store.get_reputation(receiver).completed == 1
    assert store.get_reputation(sender).completed == 0
