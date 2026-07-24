"""HTTP router that wraps every admin action into the timelock lifecycle.

Routes:
    POST   /timelock/queue                {action_type, params}
    POST   /timelock/execute/{action_id}
    POST   /timelock/cancel/{action_id}   {reason?}
    GET    /timelock/actions              -> list all (pending + settled)
    GET    /timelock/actions/{id}
    GET    /timelock/status               -> renounced flag, delay, count
    POST   /timelock/renounce             (terminal, one-way)

Auth: same `X-Admin-Key` gate as `server/admin_api.py`. When the timelock
is deployed, operators SHOULD retire the raw `/admin/*` router (see
`docs/TIMELOCK_ADMIN.md`); the timelock router then becomes the sole
entry point and every mutating action gets `min_delay_seconds` of public
visibility.

Supported action types (whitelist):
- `configure_fee`      params={"new_fee_bps": int}
- `set_release_cap`    params={"new_cap_motes": int}
- `set_arbiters`       params={"arbiters": [str]}
- `emergency_freeze`   params={}  (delay=0 allowed via governance-set 0 delay)
- `unfreeze`           params={}
- `set_delay`          params={"new_delay_seconds": int}  (bumps registry delay)

Unknown action_type is rejected at queue() time.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from sdk.admin_timelock import (
    AlreadySettledError,
    InvalidDelayError,
    RenouncedError,
    TimelockRegistry,
    UnknownActionError,
)
from server.casper_client import CasperClient
from server.config import Config, get_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/timelock", tags=["timelock"])


# Whitelist of action types + their param validators.
_ALLOWED_ACTIONS: dict[str, set[str]] = {
    "configure_fee": {"new_fee_bps"},
    "set_release_cap": {"new_cap_motes"},
    "set_arbiters": {"arbiters"},
    "emergency_freeze": set(),
    "unfreeze": set(),
    "set_delay": {"new_delay_seconds"},
}


def _require_admin_key(
    cfg: Config = Depends(get_config),
    x_admin_key: str | None = Header(default=None),
) -> None:
    if not cfg.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Timelock routes are disabled: ADMIN_API_KEY is not configured",
        )
    if not x_admin_key or x_admin_key != cfg.admin_api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or missing X-Admin-Key")


class QueueRequest(BaseModel):
    action_type: str = Field(..., description="One of the whitelisted admin action types")
    params: dict[str, Any] = Field(default_factory=dict)


class CancelRequest(BaseModel):
    reason: str | None = None


def _validate_params(action_type: str, params: dict[str, Any]) -> None:
    if action_type not in _ALLOWED_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown action_type={action_type!r}; allowed: {sorted(_ALLOWED_ACTIONS)}",
        )
    required = _ALLOWED_ACTIONS[action_type]
    missing = required - params.keys()
    extra = params.keys() - required
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"missing params for {action_type}: {sorted(missing)}",
        )
    if extra:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unexpected params for {action_type}: {sorted(extra)}",
        )


def _make_executor(cfg: Config, casper: CasperClient | None):
    """Build the callback that maps action_type -> Casper call."""

    async def _exec_async(action_type: str, params: dict[str, Any]) -> Any:
        if action_type == "set_delay":
            # Handled below in execute() via registry.set_delay (no on-chain call).
            return {"note": "set_delay handled in-process"}
        if cfg.sandbox or casper is None:
            return {"sandbox": True, "action_type": action_type, "params": params}
        if action_type == "configure_fee":
            return {"deploy_hash": await casper.configure_fee(params["new_fee_bps"])}
        if action_type == "set_release_cap":
            return {"deploy_hash": await casper.set_release_cap(params["new_cap_motes"])}
        if action_type == "set_arbiters":
            return {"deploy_hash": await casper.set_arbiters(params["arbiters"])}
        if action_type == "emergency_freeze":
            return {"deploy_hash": await casper.emergency_freeze()}
        if action_type == "unfreeze":
            return {"deploy_hash": await casper.unfreeze()}
        raise RuntimeError(f"unreachable action_type={action_type}")

    # TimelockRegistry.executor is sync; we wrap async via a small helper
    # invoked by the route (which is async and awaits it).
    def _sync_executor(action_type: str, params: dict[str, Any]) -> Any:
        # This synchronous path is only used by non-async unit tests that
        # stub Casper out. In production the route directly awaits
        # _exec_async, not this shim.
        raise RuntimeError("sync executor path not used in production")

    return _sync_executor, _exec_async


# Registry is process-global. Persistence layer (redis / db) can wrap
# this later without changing the API surface.
_REGISTRY: TimelockRegistry | None = None


def _get_registry() -> TimelockRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        # sync executor is a stub; the route does async execution itself
        # and just calls _mark_executed manually.
        _REGISTRY = TimelockRegistry(
            min_delay_seconds=_default_delay(),
            executor=lambda t, p: {"error": "should not be called; use route-level executor"},
        )
    return _REGISTRY


def _default_delay() -> int:
    """Read from env at boot; default 24h."""
    import os

    val = os.getenv("TIMELOCK_DELAY_SECONDS", "86400")
    try:
        d = int(val)
        return max(0, d)
    except ValueError:
        return 86400


def reset_registry_for_testing(min_delay_seconds: int = 0, now_fn=None) -> TimelockRegistry:
    """Test hook: rebuild the process-global registry with a controlled clock."""
    global _REGISTRY
    _REGISTRY = TimelockRegistry(
        min_delay_seconds=min_delay_seconds,
        executor=lambda t, p: {"stub": True, "action_type": t, "params": p},
        now_fn=now_fn,
    )
    return _REGISTRY


def _get_casper() -> CasperClient | None:
    from server import app as app_module

    return app_module.get_casper()


def _action_to_dict(a) -> dict[str, Any]:
    return {
        "action_id": a.action_id,
        "action_type": a.action_type,
        "params": a.params,
        "queued_at": a.queued_at,
        "ready_at": a.ready_at,
        "state": a.state.value,
        "executed_at": a.executed_at,
        "cancelled_at": a.cancelled_at,
        "cancel_reason": a.cancel_reason,
        "result": a.result,
    }


@router.post("/queue", dependencies=[Depends(_require_admin_key)])
async def queue_action(req: QueueRequest) -> dict[str, Any]:
    _validate_params(req.action_type, req.params)
    reg = _get_registry()
    try:
        action = reg.queue(req.action_type, req.params)
    except RenouncedError as e:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(e))
    return _action_to_dict(action)


@router.post("/execute/{action_id}", dependencies=[Depends(_require_admin_key)])
async def execute_action(
    action_id: int,
    cfg: Config = Depends(get_config),
    casper: CasperClient | None = Depends(_get_casper),
) -> dict[str, Any]:
    reg = _get_registry()
    try:
        action = reg.get(action_id)
    except UnknownActionError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Manually enforce the state-machine invariants here so we can await
    # the async on-chain call and then update the registry entry.
    if reg.renounced:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="admin renounced")
    if action.state.value != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"already {action.state.value}")
    now = int(reg.now_fn())
    if now < action.ready_at:
        raise HTTPException(
            status_code=status.HTTP_425_TOO_EARLY,
            detail=f"not ready: wait {action.ready_at - now}s",
        )

    # Perform action.
    try:
        if action.action_type == "set_delay":
            new_delay = int(action.params["new_delay_seconds"])
            try:
                reg.set_delay(new_delay)
            except InvalidDelayError as e:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
            result: Any = {"new_min_delay_seconds": new_delay}
        else:
            _sync_exec, async_exec = _make_executor(cfg, casper)
            result = await async_exec(action.action_type, action.params)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("timelock execute %s failed: %s", action_id, exc)
        raise HTTPException(status_code=502, detail=f"on-chain execution failed: {exc}")

    # Mark as executed by swapping the entry.
    from sdk.admin_timelock import Action, ActionState

    reg._actions[action_id] = Action(
        action_id=action.action_id,
        action_type=action.action_type,
        params=action.params,
        queued_at=action.queued_at,
        ready_at=action.ready_at,
        state=ActionState.Executed,
        executed_at=now,
        result=result,
    )
    return _action_to_dict(reg._actions[action_id])


@router.post("/cancel/{action_id}", dependencies=[Depends(_require_admin_key)])
async def cancel_action(action_id: int, req: CancelRequest | None = None) -> dict[str, Any]:
    reg = _get_registry()
    reason = req.reason if req else None
    try:
        action = reg.cancel(action_id, reason=reason)
    except UnknownActionError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AlreadySettledError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return _action_to_dict(action)


@router.get("/actions", dependencies=[Depends(_require_admin_key)])
async def list_actions() -> dict[str, Any]:
    reg = _get_registry()
    return {"actions": [_action_to_dict(a) for a in reg.list_all()]}


@router.get("/actions/{action_id}", dependencies=[Depends(_require_admin_key)])
async def get_action(action_id: int) -> dict[str, Any]:
    reg = _get_registry()
    try:
        return _action_to_dict(reg.get(action_id))
    except UnknownActionError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/status", dependencies=[Depends(_require_admin_key)])
async def get_status() -> dict[str, Any]:
    reg = _get_registry()
    return {
        "min_delay_seconds": reg.min_delay_seconds,
        "renounced": reg.renounced,
        "renounced_at": reg.renounced_at,
        "action_count": len(reg._actions),
        "pending_count": len(reg.list_pending()),
    }


@router.post("/renounce", dependencies=[Depends(_require_admin_key)])
async def renounce_admin() -> dict[str, Any]:
    """Terminal, one-way. All pending actions are cancelled with
    reason='renounce'. After this the timelock router refuses every
    mutating call."""
    reg = _get_registry()
    reg.renounce()
    return {
        "renounced": True,
        "renounced_at": reg.renounced_at,
        "cancelled_pending": [
            _action_to_dict(a) for a in reg.list_all() if a.state.value == "cancelled" and a.cancel_reason == "renounce"
        ],
    }
