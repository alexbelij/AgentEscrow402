"""Full-matrix tests for :class:`server.escrow_fsm.EscrowFSM` (AE-14).

We cover **every** ``(state, action)`` pair — both allowed and denied —
so that any accidental widening or narrowing of the transition matrix
fails a test.
"""

from __future__ import annotations

import pytest

from server.escrow_fsm import EscrowAction, EscrowFSM, InvalidTransitionError
from server.models import EscrowStatus

# All non-alias statuses. EscrowStatus.COMPLETED / FAILED are backwards-
# compat aliases pointing at RELEASED / REFUNDED and would double-count.
ALL_STATES: tuple[EscrowStatus, ...] = (
    EscrowStatus.PENDING,
    EscrowStatus.RELEASED,
    EscrowStatus.REFUNDED,
    EscrowStatus.EXPIRED,
    EscrowStatus.DISPUTED,
    EscrowStatus.RESOLVED,
)


ALLOWED: tuple[tuple[EscrowStatus, str, EscrowStatus], ...] = (
    (EscrowStatus.PENDING, EscrowAction.RELEASE, EscrowStatus.RELEASED),
    (EscrowStatus.PENDING, EscrowAction.REFUND, EscrowStatus.REFUNDED),
    (EscrowStatus.PENDING, EscrowAction.EXPIRE, EscrowStatus.EXPIRED),
    (EscrowStatus.PENDING, EscrowAction.DISPUTE, EscrowStatus.DISPUTED),
    (EscrowStatus.DISPUTED, EscrowAction.RESOLVE_SENDER, EscrowStatus.RESOLVED),
    (EscrowStatus.DISPUTED, EscrowAction.RESOLVE_RECEIVER, EscrowStatus.RESOLVED),
)


@pytest.mark.parametrize("current,action,expected", ALLOWED)
def test_allowed_transitions(current: EscrowStatus, action: str, expected: EscrowStatus) -> None:
    """Every entry in the matrix produces the exact next_state."""
    assert EscrowFSM.can_transition(current, action) is True
    assert EscrowFSM.transition(current, action) == expected


def _every_denied_pair() -> list[tuple[EscrowStatus, str]]:
    allowed_pairs = {(s, a) for (s, a, _) in ALLOWED}
    return [
        (state, action) for state in ALL_STATES for action in EscrowAction.ALL if (state, action) not in allowed_pairs
    ]


@pytest.mark.parametrize("current,action", _every_denied_pair())
def test_denied_transitions_raise(current: EscrowStatus, action: str) -> None:
    """Every (state, action) NOT in the matrix must be denied."""
    assert EscrowFSM.can_transition(current, action) is False
    with pytest.raises(InvalidTransitionError) as exc_info:
        EscrowFSM.transition(current, action)
    err = exc_info.value
    assert err.current_state == current
    assert err.action == action
    # Payload must be JSON-safe.
    payload = err.to_payload()
    assert payload["code"] == "invalid_transition"
    assert payload["current_state"] == current.value
    assert payload["action"] == action
    assert isinstance(payload["allowed_actions"], list)


@pytest.mark.parametrize(
    "state",
    (
        EscrowStatus.RELEASED,
        EscrowStatus.REFUNDED,
        EscrowStatus.EXPIRED,
        EscrowStatus.RESOLVED,
    ),
)
def test_terminal_states_have_no_outgoing_edges(state: EscrowStatus) -> None:
    """Terminal states never allow further transitions."""
    assert EscrowFSM.is_terminal(state) is True
    assert EscrowFSM.allowed_actions(state) == ()


def test_pending_has_all_non_resolve_actions() -> None:
    """From PENDING the four non-resolve actions are allowed, resolve is not."""
    allowed = EscrowFSM.allowed_actions(EscrowStatus.PENDING)
    assert set(allowed) == {
        EscrowAction.RELEASE,
        EscrowAction.REFUND,
        EscrowAction.EXPIRE,
        EscrowAction.DISPUTE,
    }
    # Ordering is stable — follows EscrowAction.ALL declaration order.
    assert allowed == (
        EscrowAction.RELEASE,
        EscrowAction.REFUND,
        EscrowAction.EXPIRE,
        EscrowAction.DISPUTE,
    )


def test_disputed_only_allows_resolutions() -> None:
    """From DISPUTED only arbiter resolutions are allowed."""
    allowed = EscrowFSM.allowed_actions(EscrowStatus.DISPUTED)
    assert set(allowed) == {
        EscrowAction.RESOLVE_SENDER,
        EscrowAction.RESOLVE_RECEIVER,
    }


def test_unknown_action_string_is_denied() -> None:
    """A garbage action name must be rejected, not treated as a no-op."""
    with pytest.raises(InvalidTransitionError) as exc_info:
        EscrowFSM.transition(EscrowStatus.PENDING, "delete_everything")
    assert exc_info.value.action == "delete_everything"


def test_error_message_terminal_vs_actionable() -> None:
    """Terminal-state error message is distinct from allowed-list case."""
    # From PENDING (non-terminal) message lists allowed actions.
    with pytest.raises(InvalidTransitionError) as exc:
        EscrowFSM.transition(EscrowStatus.PENDING, EscrowAction.RESOLVE_SENDER)
    assert "Allowed actions from this state" in str(exc.value)
    assert "release" in str(exc.value)

    # From RELEASED (terminal) message says no further transitions.
    with pytest.raises(InvalidTransitionError) as exc:
        EscrowFSM.transition(EscrowStatus.RELEASED, EscrowAction.REFUND)
    assert "terminal state" in str(exc.value)
    assert "No further transitions" in str(exc.value)


def test_no_transition_ever_produces_pending() -> None:
    """PENDING is a start-only state — no transition creates it.

    Guards against a future edit that accidentally maps back to PENDING
    (which would allow zombie re-openings of terminal escrows).
    """
    from server.escrow_fsm import _TRANSITIONS  # type: ignore[attr-defined]

    for next_state in _TRANSITIONS.values():
        assert next_state != EscrowStatus.PENDING, "No transition should re-enter PENDING"


def test_error_is_frozen_dataclass() -> None:
    """InvalidTransitionError is immutable — payload cannot be tampered."""
    err = InvalidTransitionError(
        current_state=EscrowStatus.RELEASED,
        action="release",
        allowed_actions=(),
    )
    with pytest.raises(Exception):
        err.action = "refund"  # type: ignore[misc]


def test_double_release_is_denied() -> None:
    """Regression: release on already-RELEASED escrow must fail."""
    with pytest.raises(InvalidTransitionError):
        EscrowFSM.transition(EscrowStatus.RELEASED, EscrowAction.RELEASE)


def test_dispute_after_refund_is_denied() -> None:
    """Regression: sender cannot open a dispute after taking a refund."""
    with pytest.raises(InvalidTransitionError):
        EscrowFSM.transition(EscrowStatus.REFUNDED, EscrowAction.DISPUTE)


def test_resolve_on_pending_is_denied() -> None:
    """Regression: arbiters cannot resolve before a dispute is opened."""
    with pytest.raises(InvalidTransitionError):
        EscrowFSM.transition(EscrowStatus.PENDING, EscrowAction.RESOLVE_SENDER)
    with pytest.raises(InvalidTransitionError):
        EscrowFSM.transition(EscrowStatus.PENDING, EscrowAction.RESOLVE_RECEIVER)


def test_matrix_size_is_expected() -> None:
    """Sanity: matrix has exactly 6 allowed transitions.

    If someone widens the matrix without updating this test, they must
    justify it in review. Narrowing is caught by the parametrised
    allowed-transitions test above.
    """
    from server.escrow_fsm import _TRANSITIONS  # type: ignore[attr-defined]

    assert len(_TRANSITIONS) == 6
