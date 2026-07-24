"""Property tests for the timelocked admin + renounce lifecycle."""

from __future__ import annotations

import pytest

from sdk.admin_timelock import (
    ActionState,
    AlreadySettledError,
    InvalidDelayError,
    NotReadyError,
    RenouncedError,
    TimelockRegistry,
    UnknownActionError,
)


class Clock:
    def __init__(self, t: int = 1_000_000) -> None:
        self.t = t

    def __call__(self) -> int:
        return self.t

    def advance(self, dt: int) -> None:
        self.t += dt


def _mk(delay: int = 60) -> tuple[TimelockRegistry, Clock, list[tuple[str, dict]]]:
    clock = Clock()
    calls: list[tuple[str, dict]] = []

    def executor(action_type: str, params: dict) -> str:
        calls.append((action_type, params))
        return f"ok:{action_type}"

    reg = TimelockRegistry(min_delay_seconds=delay, executor=executor, now_fn=clock)
    return reg, clock, calls


# ---------- queue + execute happy path ----------------------------------


def test_queue_returns_pending_action():
    reg, clock, _ = _mk(delay=60)
    a = reg.queue("configure_fee", {"bps": 30})
    assert a.state == ActionState.Pending
    assert a.action_id == 1
    assert a.queued_at == clock.t
    assert a.ready_at == clock.t + 60
    assert a.params == {"bps": 30}


def test_execute_before_delay_raises():
    reg, clock, _ = _mk(delay=60)
    a = reg.queue("configure_fee", {"bps": 30})
    clock.advance(59)  # 1s short
    with pytest.raises(NotReadyError):
        reg.execute(a.action_id)


def test_execute_exactly_at_ready_at_succeeds():
    reg, clock, calls = _mk(delay=60)
    a = reg.queue("configure_fee", {"bps": 30})
    clock.advance(60)  # exactly ready_at
    settled = reg.execute(a.action_id)
    assert settled.state == ActionState.Executed
    assert settled.executed_at == clock.t
    assert settled.result == "ok:configure_fee"
    assert calls == [("configure_fee", {"bps": 30})]


def test_execute_after_delay_succeeds():
    reg, clock, calls = _mk(delay=60)
    a = reg.queue("set_arbiters", {"arbiters": ["a", "b"]})
    clock.advance(9999)
    reg.execute(a.action_id)
    assert calls == [("set_arbiters", {"arbiters": ["a", "b"]})]


def test_execute_twice_raises():
    reg, clock, _ = _mk(delay=0)
    a = reg.queue("emergency_freeze", {})
    reg.execute(a.action_id)
    with pytest.raises(AlreadySettledError):
        reg.execute(a.action_id)


def test_execute_after_cancel_raises():
    reg, clock, _ = _mk(delay=60)
    a = reg.queue("configure_fee", {"bps": 30})
    reg.cancel(a.action_id, reason="oops")
    clock.advance(60)
    with pytest.raises(AlreadySettledError):
        reg.execute(a.action_id)


def test_execute_unknown_raises():
    reg, _, _ = _mk()
    with pytest.raises(UnknownActionError):
        reg.execute(9999)


# ---------- cancel ------------------------------------------------------


def test_cancel_pending_marks_cancelled():
    reg, clock, _ = _mk(delay=60)
    a = reg.queue("configure_fee", {"bps": 30})
    cancelled = reg.cancel(a.action_id, reason="test")
    assert cancelled.state == ActionState.Cancelled
    assert cancelled.cancelled_at == clock.t
    assert cancelled.cancel_reason == "test"


def test_cancel_idempotent():
    reg, _, _ = _mk()
    a = reg.queue("configure_fee", {"bps": 30})
    c1 = reg.cancel(a.action_id, reason="first")
    c2 = reg.cancel(a.action_id, reason="second")
    # idempotent: cancel_reason from first call is preserved
    assert c1 == c2
    assert c1.cancel_reason == "first"


def test_cancel_executed_raises():
    reg, clock, _ = _mk(delay=0)
    a = reg.queue("emergency_freeze", {})
    reg.execute(a.action_id)
    with pytest.raises(AlreadySettledError):
        reg.cancel(a.action_id)


def test_cancel_unknown_raises():
    reg, _, _ = _mk()
    with pytest.raises(UnknownActionError):
        reg.cancel(9999)


# ---------- renounce ----------------------------------------------------


def test_renounce_flips_flag():
    reg, clock, _ = _mk()
    assert reg.renounced is False
    reg.renounce()
    assert reg.renounced is True
    assert reg.renounced_at == clock.t


def test_renounce_idempotent():
    reg, clock, _ = _mk()
    reg.renounce()
    first = reg.renounced_at
    clock.advance(1000)
    reg.renounce()
    # idempotent: renounced_at from first call is preserved
    assert reg.renounced_at == first


def test_renounce_cancels_pending_actions():
    reg, clock, _ = _mk(delay=60)
    a1 = reg.queue("configure_fee", {"bps": 30})
    a2 = reg.queue("set_arbiters", {"arbiters": []})
    reg.renounce()
    assert reg.get(a1.action_id).state == ActionState.Cancelled
    assert reg.get(a1.action_id).cancel_reason == "renounce"
    assert reg.get(a2.action_id).state == ActionState.Cancelled
    assert reg.get(a2.action_id).cancel_reason == "renounce"


def test_renounce_does_not_touch_executed_actions():
    reg, clock, _ = _mk(delay=0)
    a = reg.queue("emergency_freeze", {})
    settled = reg.execute(a.action_id)
    reg.renounce()
    # executed action is unchanged
    assert reg.get(a.action_id) == settled


def test_queue_after_renounce_raises():
    reg, _, _ = _mk()
    reg.renounce()
    with pytest.raises(RenouncedError):
        reg.queue("configure_fee", {"bps": 30})


def test_execute_after_renounce_raises():
    reg, clock, _ = _mk(delay=0)
    a = reg.queue("configure_fee", {"bps": 30})
    reg.renounce()
    # even a not-cancelled queued action can't execute after renounce
    # (but since renounce cancels all pending, this is doubly-covered)
    with pytest.raises(RenouncedError):
        reg.execute(a.action_id)


def test_set_delay_after_renounce_raises():
    reg, _, _ = _mk()
    reg.renounce()
    with pytest.raises(RenouncedError):
        reg.set_delay(120)


def test_cancel_after_renounce_is_noop_on_cancelled():
    reg, _, _ = _mk(delay=60)
    a = reg.queue("configure_fee", {"bps": 30})
    reg.renounce()
    # action is already cancelled by renounce; cancel() should be idempotent
    result = reg.cancel(a.action_id, reason="post-renounce")
    assert result.state == ActionState.Cancelled
    assert result.cancel_reason == "renounce"  # preserved from renounce


# ---------- set_delay monotonicity -------------------------------------


def test_set_delay_can_grow():
    reg, _, _ = _mk(delay=60)
    reg.set_delay(120)
    assert reg.min_delay_seconds == 120
    reg.set_delay(120)  # equal is fine
    assert reg.min_delay_seconds == 120


def test_set_delay_cannot_shrink():
    reg, _, _ = _mk(delay=60)
    with pytest.raises(InvalidDelayError):
        reg.set_delay(59)


def test_new_delay_only_applies_to_future_queues():
    reg, clock, _ = _mk(delay=60)
    a1 = reg.queue("configure_fee", {"bps": 30})
    assert a1.ready_at == clock.t + 60
    reg.set_delay(300)
    a2 = reg.queue("set_arbiters", {"arbiters": []})
    assert a2.ready_at == clock.t + 300
    # a1's ready_at is NOT retroactively lengthened
    assert reg.get(a1.action_id).ready_at == a1.ready_at


# ---------- action-id monotonicity -------------------------------------


def test_action_ids_monotonic():
    reg, _, _ = _mk()
    ids = [reg.queue("x", {"i": i}).action_id for i in range(10)]
    assert ids == list(range(1, 11))


def test_action_ids_continue_across_cancels():
    reg, _, _ = _mk()
    a1 = reg.queue("x", {})
    reg.cancel(a1.action_id)
    a2 = reg.queue("y", {})
    assert a2.action_id == a1.action_id + 1


# ---------- executor error handling ------------------------------------


def test_executor_error_does_not_flip_state():
    clock = Clock()

    def bad_executor(action_type: str, params: dict):
        raise RuntimeError("boom")

    reg = TimelockRegistry(min_delay_seconds=0, executor=bad_executor, now_fn=clock)
    a = reg.queue("configure_fee", {"bps": 30})
    with pytest.raises(RuntimeError, match="boom"):
        reg.execute(a.action_id)
    # state must stay Pending -- caller can retry
    assert reg.get(a.action_id).state == ActionState.Pending


# ---------- listing ----------------------------------------------------


def test_list_pending_excludes_settled():
    reg, clock, _ = _mk(delay=0)
    a1 = reg.queue("x", {})
    a2 = reg.queue("y", {})
    a3 = reg.queue("z", {})
    reg.execute(a1.action_id)
    reg.cancel(a2.action_id)
    pending = reg.list_pending()
    assert [a.action_id for a in pending] == [a3.action_id]


def test_list_all_returns_sorted():
    reg, _, _ = _mk()
    for i in range(5):
        reg.queue("x", {"i": i})
    all_actions = reg.list_all()
    assert [a.action_id for a in all_actions] == [1, 2, 3, 4, 5]


# ---------- params isolation -------------------------------------------


def test_params_defensive_copy():
    reg, _, _ = _mk()
    p = {"bps": 30}
    a = reg.queue("configure_fee", p)
    p["bps"] = 999  # mutate after queue
    assert reg.get(a.action_id).params == {"bps": 30}


# ---------- construction validation ------------------------------------


def test_negative_delay_rejected():
    with pytest.raises(ValueError):
        TimelockRegistry(min_delay_seconds=-1, executor=lambda t, p: None)


def test_queue_rejects_empty_action_type():
    reg, _, _ = _mk()
    with pytest.raises(ValueError):
        reg.queue("", {})


def test_queue_rejects_non_dict_params():
    reg, _, _ = _mk()
    with pytest.raises(ValueError):
        reg.queue("x", "not-a-dict")  # type: ignore[arg-type]
