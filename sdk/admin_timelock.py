"""Timelocked admin + renounce lifecycle for AE402.

Additive layer on top of the existing installer-only admin routes
(`server/admin_api.py`). Wraps every mutating admin action into a
two-step lifecycle:

    queue(action, params)   -> action_id, ready_at = now + delay
    execute(action_id)      -> runs the queued action iff now >= ready_at
    cancel(action_id)       -> admin can drop a pending action

Plus a terminal, one-way `renounce()`:
- renounce() flips `renounced=True`
- every subsequent queue()/execute() raises RenouncedError
- every pending action is cancelled (state = Cancelled with reason=renounce)
- cancel() itself is idempotent after renounce (does nothing on already-
  cancelled actions)

Design choices:
- Framework-agnostic. Zero deps. Uses an injectable `now()` clock so tests
  and property checks are deterministic.
- The execution callback is injected: this module doesn't know about
  Casper or FastAPI, it just orchestrates the state machine. The server
  layer (server/timelock_api.py) wires the callback to the real admin
  actions.
- Action_id is a monotonically-increasing uint64 within one Registry
  instance. Restart-safe persistence is out of scope for this SDK layer;
  the server-side registry can be swapped for a durable store later
  without changing the state machine contract.
- Delay is per-Registry and cannot be shortened after construction
  (governance safety). It CAN be lengthened via `set_delay()` -- but only
  through the same queue/execute flow, treated as a normal admin action.

Threat model: this layer's guarantee is "no admin action executes with
less than `min_delay` seconds of public visibility". If a caller can
bypass the Registry and call the underlying admin routes directly, this
layer provides no protection. In deployment the underlying `/admin/*`
routes should be closed off (X-Admin-Key retired) once the timelock is
live, or gated behind an internal-only network -- the timelock router
becomes the sole entry point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

DOMAIN_TAG = "ae402:timelock:v1"


class ActionState(str, Enum):
    Pending = "pending"
    Executed = "executed"
    Cancelled = "cancelled"


class TimelockError(Exception):
    """Base error for the timelock state machine."""


class RenouncedError(TimelockError):
    """Admin authority has been renounced; the action was refused."""


class UnknownActionError(TimelockError):
    """No pending action with this id."""


class NotReadyError(TimelockError):
    """Action is still within its timelock window."""


class AlreadySettledError(TimelockError):
    """Action already executed or cancelled."""


class InvalidDelayError(TimelockError):
    """Rejected: proposed delay is smaller than the current one."""


@dataclass(frozen=True)
class Action:
    action_id: int
    action_type: str
    params: dict[str, Any]
    queued_at: int
    ready_at: int
    state: ActionState
    executed_at: int | None = None
    cancelled_at: int | None = None
    cancel_reason: str | None = None
    result: Any = None
    """Result returned by the execution callback (opaque)."""


@dataclass
class TimelockRegistry:
    """In-memory state machine. Server wraps this with persistence + HTTP.

    - `min_delay_seconds`: the timelock window applied to every queued
      action. Enforced monotonically-non-decreasing over the Registry
      lifetime (governance safety).
    - `now_fn`: clock injected for determinism; defaults to time.time().
    - `executor`: callable invoked at `execute()` with (action_type,
      params). Its return value is stored on the executed Action.
    """

    min_delay_seconds: int
    executor: Callable[[str, dict[str, Any]], Any]
    now_fn: Callable[[], int] = field(default=None)  # type: ignore[assignment]

    _actions: dict[int, Action] = field(default_factory=dict, init=False)
    _next_id: int = field(default=1, init=False)
    _renounced: bool = field(default=False, init=False)
    _renounced_at: int | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.min_delay_seconds < 0:
            raise ValueError("min_delay_seconds must be >= 0")
        if self.now_fn is None:
            import time

            self.now_fn = lambda: int(time.time())

    # ---- introspection -------------------------------------------------
    @property
    def renounced(self) -> bool:
        return self._renounced

    @property
    def renounced_at(self) -> int | None:
        return self._renounced_at

    def get(self, action_id: int) -> Action:
        if action_id not in self._actions:
            raise UnknownActionError(f"unknown action_id={action_id}")
        return self._actions[action_id]

    def list_pending(self) -> list[Action]:
        return [a for a in self._actions.values() if a.state == ActionState.Pending]

    def list_all(self) -> list[Action]:
        return sorted(self._actions.values(), key=lambda a: a.action_id)

    # ---- mutating API --------------------------------------------------
    def queue(self, action_type: str, params: dict[str, Any]) -> Action:
        if self._renounced:
            raise RenouncedError("admin renounced; queue() disabled")
        if not action_type or not isinstance(action_type, str):
            raise ValueError("action_type must be a non-empty string")
        if not isinstance(params, dict):
            raise ValueError("params must be a dict")
        now = int(self.now_fn())
        action_id = self._next_id
        self._next_id += 1
        action = Action(
            action_id=action_id,
            action_type=action_type,
            params=dict(params),  # defensive copy
            queued_at=now,
            ready_at=now + self.min_delay_seconds,
            state=ActionState.Pending,
        )
        self._actions[action_id] = action
        return action

    def execute(self, action_id: int) -> Action:
        if self._renounced:
            raise RenouncedError("admin renounced; execute() disabled")
        action = self.get(action_id)
        if action.state == ActionState.Executed:
            raise AlreadySettledError(f"action {action_id} already executed")
        if action.state == ActionState.Cancelled:
            raise AlreadySettledError(f"action {action_id} was cancelled")
        now = int(self.now_fn())
        if now < action.ready_at:
            raise NotReadyError(
                f"action {action_id} not ready: now={now} < ready_at={action.ready_at} "
                f"(wait {action.ready_at - now}s)"
            )
        # Run the injected executor -- this may raise; we surface the raw
        # exception WITHOUT flipping the state, so the caller can retry.
        result = self.executor(action.action_type, action.params)
        settled = Action(
            action_id=action.action_id,
            action_type=action.action_type,
            params=action.params,
            queued_at=action.queued_at,
            ready_at=action.ready_at,
            state=ActionState.Executed,
            executed_at=now,
            result=result,
        )
        self._actions[action_id] = settled
        return settled

    def cancel(self, action_id: int, reason: str | None = None) -> Action:
        # Cancel is allowed after renounce (idempotent no-op on already-
        # cancelled), but not on already-executed actions.
        action = self.get(action_id)
        if action.state == ActionState.Executed:
            raise AlreadySettledError(f"action {action_id} already executed; cannot cancel")
        if action.state == ActionState.Cancelled:
            return action  # idempotent
        now = int(self.now_fn())
        cancelled = Action(
            action_id=action.action_id,
            action_type=action.action_type,
            params=action.params,
            queued_at=action.queued_at,
            ready_at=action.ready_at,
            state=ActionState.Cancelled,
            cancelled_at=now,
            cancel_reason=reason,
        )
        self._actions[action_id] = cancelled
        return cancelled

    def set_delay(self, new_delay_seconds: int) -> None:
        """Governance-safe: delay can only grow, never shrink.

        Not itself timelock-gated; the server SHOULD wrap it as a queued
        action (action_type='set_delay') so the change is public before
        it takes effect. This raw setter is exposed for the wrapper's use.
        """
        if self._renounced:
            raise RenouncedError("admin renounced; set_delay() disabled")
        if new_delay_seconds < 0:
            raise ValueError("delay must be >= 0")
        if new_delay_seconds < self.min_delay_seconds:
            raise InvalidDelayError(f"delay is monotonic: new={new_delay_seconds} < current={self.min_delay_seconds}")
        self.min_delay_seconds = new_delay_seconds

    def renounce(self) -> None:
        """Terminal, one-way. All pending actions are cancelled with
        reason='renounce'."""
        if self._renounced:
            return  # idempotent
        now = int(self.now_fn())
        self._renounced = True
        self._renounced_at = now
        # Cancel every pending action.
        for aid, action in list(self._actions.items()):
            if action.state == ActionState.Pending:
                self._actions[aid] = Action(
                    action_id=action.action_id,
                    action_type=action.action_type,
                    params=action.params,
                    queued_at=action.queued_at,
                    ready_at=action.ready_at,
                    state=ActionState.Cancelled,
                    cancelled_at=now,
                    cancel_reason="renounce",
                )
