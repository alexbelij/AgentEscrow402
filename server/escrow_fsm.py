"""Deny-by-default finite state machine for escrow lifecycle (AE-14).

Every hosted transition MUST go through :class:`EscrowFSM`. The matrix of
allowed `(state, action) -> next_state` is the single source of truth;
anything not in the matrix is denied outright (never "unknown, allow").

Design rules
------------

1. **Central matrix** — one dict literal, easy to audit and diff.
2. **Deny by default** — attempting an action that is not explicitly
   allowed from the current state raises :class:`InvalidTransitionError`.
3. **Pure state logic** — the FSM only decides *whether* the state can
   change and *what* the next state is. Permission checks (only-sender,
   only-arbiter), timing checks (TTL expiry), and on-chain checks (cap
   approval multisig) still live in their call sites; they run *before*
   :func:`EscrowFSM.transition` so an unauthorised or misused call
   never even reaches the FSM.
4. **Machine-readable errors** — :class:`InvalidTransitionError` exposes
   ``current_state``, ``action``, ``allowed_actions`` so an API layer can
   surface a 409 with a stable JSON payload.
5. **No I/O** — this module has zero dependency on databases, HTTP, or
   the chain, so it is trivially unit-testable and can be lifted into
   any other Casper contract that needs the same guarantees.

The matrix is intentionally *narrower* than the Rust contract's
transitions. If the on-chain contract ever accepts a state change that
the Python matrix rejects, the hosted API refuses to record it and
returns 409 — safe by construction: the on-chain truth is preserved on
the ledger, and callers can query it directly via the CSPR node RPC.
Widening the matrix is a code change and shows up on review.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from server.models import EscrowStatus


class EscrowAction:
    """Named lifecycle actions.

    Kept as string constants rather than a full Enum so we can be
    forgiving about caller-side typos in tests without pulling
    ``Enum.__members__`` in every branch.
    """

    RELEASE: Final = "release"
    REFUND: Final = "refund"
    EXPIRE: Final = "expire"
    DISPUTE: Final = "dispute"
    RESOLVE_SENDER: Final = "resolve_sender"
    RESOLVE_RECEIVER: Final = "resolve_receiver"

    ALL: Final[tuple[str, ...]] = (
        RELEASE,
        REFUND,
        EXPIRE,
        DISPUTE,
        RESOLVE_SENDER,
        RESOLVE_RECEIVER,
    )


# ---------------------------------------------------------------------------
# The one and only transition matrix.
#
# key   = (current_state, action)
# value = next_state
#
# If a (state, action) pair is not a key, the transition is DENIED.
# There is no wildcard, no "unknown -> allow", no silent state carry-over.
# ---------------------------------------------------------------------------
_TRANSITIONS: Final[dict[tuple[EscrowStatus, str], EscrowStatus]] = {
    # Happy path from PENDING.
    (EscrowStatus.PENDING, EscrowAction.RELEASE): EscrowStatus.RELEASED,
    (EscrowStatus.PENDING, EscrowAction.REFUND): EscrowStatus.REFUNDED,
    (EscrowStatus.PENDING, EscrowAction.EXPIRE): EscrowStatus.EXPIRED,
    (EscrowStatus.PENDING, EscrowAction.DISPUTE): EscrowStatus.DISPUTED,
    # From DISPUTED only arbiter resolution or expiry.
    (EscrowStatus.DISPUTED, EscrowAction.RESOLVE_SENDER): EscrowStatus.RESOLVED,
    (EscrowStatus.DISPUTED, EscrowAction.RESOLVE_RECEIVER): EscrowStatus.RESOLVED,
    # Terminal states (RELEASED, REFUNDED, EXPIRED, RESOLVED) have NO
    # outgoing edges — any action from a terminal state is denied. This
    # blocks double-release, refund-after-release, dispute-after-refund
    # and every symmetric variant without adding per-endpoint checks.
}


@dataclass(frozen=True)
class InvalidTransitionError(Exception):
    """Raised when ``(current_state, action)`` is not in the allow-matrix.

    Immutable, machine-readable payload for the API layer.
    """

    current_state: EscrowStatus
    action: str
    allowed_actions: tuple[str, ...]

    def __post_init__(self) -> None:
        # Populate the base Exception ``args`` so ``str(exc)`` is stable
        # even if the caller only logs the exception.
        Exception.__init__(self, self._message())

    def _message(self) -> str:
        if self.allowed_actions:
            allowed = ", ".join(self.allowed_actions)
            return (
                f"Cannot perform action '{self.action}' on escrow in state "
                f"'{self.current_state.value}'. Allowed actions from this "
                f"state: {allowed}."
            )
        return (
            f"Cannot perform action '{self.action}' on escrow in terminal "
            f"state '{self.current_state.value}'. No further transitions "
            f"are allowed."
        )

    def to_payload(self) -> dict[str, object]:
        """Stable JSON body for HTTP 409 responses.

        Frontends and integration tests key off ``code`` and
        ``current_state`` — do not rename either field.
        """
        return {
            "code": "invalid_transition",
            "current_state": self.current_state.value,
            "action": self.action,
            "allowed_actions": list(self.allowed_actions),
            "message": self._message(),
        }


class EscrowFSM:
    """Stateless namespace for the escrow transition matrix.

    All methods are ``@classmethod`` — the FSM holds no instance state,
    it is pure lookup over :data:`_TRANSITIONS`.
    """

    @classmethod
    def allowed_actions(cls, current: EscrowStatus) -> tuple[str, ...]:
        """Return the tuple of actions permitted from ``current`` state.

        Ordered by ``EscrowAction.ALL`` so the API response is stable
        across Python versions (dict iteration order is insertion order
        in CPython 3.7+, but we do not want to rely on the matrix
        literal's order for a public payload).
        """
        allowed = {action for (state, action) in _TRANSITIONS if state == current}
        return tuple(a for a in EscrowAction.ALL if a in allowed)

    @classmethod
    def can_transition(cls, current: EscrowStatus, action: str) -> bool:
        """Return True iff (current, action) is in the matrix."""
        return (current, action) in _TRANSITIONS

    @classmethod
    def transition(cls, current: EscrowStatus, action: str) -> EscrowStatus:
        """Return the ``next_state`` for ``(current, action)``.

        Raises
        ------
        InvalidTransitionError
            If ``action`` is not allowed from ``current``. This includes:
            - unknown action strings (not in :class:`EscrowAction`),
            - actions on terminal states (``released``, ``refunded``,
              ``expired``, ``resolved``),
            - actions the matrix simply does not list (e.g. ``release``
              on a ``disputed`` escrow — resolution must go through the
              arbiter panel first).
        """
        next_state = _TRANSITIONS.get((current, action))
        if next_state is None:
            raise InvalidTransitionError(
                current_state=current,
                action=action,
                allowed_actions=cls.allowed_actions(current),
            )
        return next_state

    @classmethod
    def is_terminal(cls, state: EscrowStatus) -> bool:
        """True if no transition leaves ``state`` — an audit helper."""
        return cls.allowed_actions(state) == ()


__all__ = [
    "EscrowAction",
    "EscrowFSM",
    "InvalidTransitionError",
]
