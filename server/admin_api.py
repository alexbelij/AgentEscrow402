"""Installer-only administrative routes for the escrow contract.

Covers the remaining contract entry points that aren't part of the normal
escrow lifecycle (escrow/release/refund/dispute/resolve/commit_swap/
reveal_swap, all wired elsewhere): `configure_fee`, `set_release_cap`
(new, A1 hardening), `set_arbiters`, `emergency_freeze`, `unfreeze`.

All five only succeed on-chain if the backend's configured deployer key IS
the contract's installer account (the contract itself reverts with
ERR_UNAUTHORIZED otherwise) -- this router adds a second, API-level gate
on top of that: every route requires a matching `X-Admin-Key` header
against `Config.admin_api_key`. If that key is not configured (empty),
every route in this file responds 503 rather than silently allowing
unauthenticated calls through to a possibly-still-authorized deployer key.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status

from server.casper_client import CasperClient
from server.config import Config, get_config
from server.models import ConfigureFeeRequest, SetArbitersRequest, SetReleaseCapRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# NOTE on testing: this router depends on `server.config.get_config`
# (uncached, reads env fresh every call) rather than `server.app`'s own
# `@lru_cache`'d get_config. Tests override it directly:
#   from server.config import get_config as admin_get_config
#   app.dependency_overrides[admin_get_config] = lambda: cfg


def _get_casper() -> CasperClient | None:
    # Deferred import to avoid a circular import with server.app (which
    # constructs the shared CasperClient instance at startup).
    from server import app as app_module

    return app_module.get_casper()


def _require_admin_key(
    cfg: Config = Depends(get_config),
    x_admin_key: str | None = Header(default=None),
) -> None:
    if not cfg.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin routes are disabled: ADMIN_API_KEY is not configured on this deployment",
        )
    if not x_admin_key or x_admin_key != cfg.admin_api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or missing X-Admin-Key")


@router.post("/configure-fee", dependencies=[Depends(_require_admin_key)])
async def configure_fee(
    req: ConfigureFeeRequest,
    cfg: Config = Depends(get_config),
    casper: CasperClient | None = Depends(_get_casper),
) -> dict[str, str]:
    """Update the insurance fee (basis points, contract max 1000 = 10%)."""
    if cfg.sandbox or casper is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="configure_fee requires live (non-sandbox) mode with a configured Casper client",
        )
    try:
        deploy_hash = await casper.configure_fee(req.new_fee_bps)
    except Exception as exc:
        logger.error("configure_fee failed: %s", exc)
        raise HTTPException(status_code=502, detail="On-chain configure_fee transaction failed")
    return {"message": "configure_fee submitted", "deploy_hash": deploy_hash}


@router.post("/set-release-cap", dependencies=[Depends(_require_admin_key)])
async def set_release_cap(
    req: SetReleaseCapRequest,
    cfg: Config = Depends(get_config),
    casper: CasperClient | None = Depends(_get_casper),
) -> dict[str, str]:
    """Update the A1 release cap (motes). Remember to also update the
    RELEASE_CAP_MOTES env var (server/config.py's local fast-fail mirror) to
    match, or /release and /escrow/atomic-swap/reveal will fast-fail against
    a stale cap even though the on-chain value already changed."""
    if cfg.sandbox or casper is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="set_release_cap requires live (non-sandbox) mode with a configured Casper client",
        )
    try:
        deploy_hash = await casper.set_release_cap(req.new_cap_motes)
    except Exception as exc:
        logger.error("set_release_cap failed: %s", exc)
        raise HTTPException(status_code=502, detail="On-chain set_release_cap transaction failed")
    return {"message": "set_release_cap submitted", "deploy_hash": deploy_hash}


@router.post("/set-arbiters", dependencies=[Depends(_require_admin_key)])
async def set_arbiters(
    req: SetArbitersRequest,
    cfg: Config = Depends(get_config),
    casper: CasperClient | None = Depends(_get_casper),
) -> dict[str, str]:
    """Replace the whole on-chain arbiter_list used by resolve() and the A1
    cap-approval quorum. Remember to also update ARBITER_PUBKEYS env var to
    match, or the backend's local fast-fail checks will use a stale list."""
    if cfg.sandbox or casper is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="set_arbiters requires live (non-sandbox) mode with a configured Casper client",
        )
    try:
        deploy_hash = await casper.set_arbiters(req.arbiters)
    except Exception as exc:
        logger.error("set_arbiters failed: %s", exc)
        raise HTTPException(status_code=502, detail="On-chain set_arbiters transaction failed")
    return {"message": "set_arbiters submitted", "deploy_hash": deploy_hash}


@router.post("/emergency-freeze", dependencies=[Depends(_require_admin_key)])
async def emergency_freeze(
    cfg: Config = Depends(get_config),
    casper: CasperClient | None = Depends(_get_casper),
) -> dict[str, str]:
    """Freeze escrow-contract state changes (release/refund/dispute/resolve/
    commit_swap/reveal_swap). Reversible -- see `POST /admin/unfreeze`.
    Use as a last resort (e.g. a discovered exploit) while investigating."""
    if cfg.sandbox or casper is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="emergency_freeze requires live (non-sandbox) mode with a configured Casper client",
        )
    try:
        deploy_hash = await casper.emergency_freeze()
    except Exception as exc:
        logger.error("emergency_freeze failed: %s", exc)
        raise HTTPException(status_code=502, detail="On-chain emergency_freeze transaction failed")
    return {"message": "emergency_freeze submitted", "deploy_hash": deploy_hash}


@router.post("/unfreeze", dependencies=[Depends(_require_admin_key)])
async def unfreeze(
    cfg: Config = Depends(get_config),
    casper: CasperClient | None = Depends(_get_casper),
) -> dict[str, str]:
    """Resume operations after `emergency_freeze` (installer-only on-chain
    check, plus the same X-Admin-Key gate as every other route in this
    file)."""
    if cfg.sandbox or casper is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="unfreeze requires live (non-sandbox) mode with a configured Casper client",
        )
    try:
        deploy_hash = await casper.unfreeze()
    except Exception as exc:
        logger.error("unfreeze failed: %s", exc)
        raise HTTPException(status_code=502, detail="On-chain unfreeze transaction failed")
    return {"message": "unfreeze submitted", "deploy_hash": deploy_hash}
