"""HTTP surface for the AE402 → Telegram bridge.

Endpoints:

* ``POST /telegram/subscribe`` — register a ``chat_id`` (with optional filter)
  to receive AE402 escrow events. Returns the newly created subscription id.
* ``DELETE /telegram/subscriptions/{sub_id}`` — remove a subscription. Returns
  ``204`` on success, ``404`` when the id is unknown.
* ``GET /telegram/subscriptions`` — list active subscriptions (server-side
  bookkeeping / operator visibility).
* ``POST /telegram/test`` — send a smoke-test message to a chat_id. Used to
  verify that the bot has been added to a chat before wiring subscriptions.
* ``GET /telegram/status`` — report readiness (`ready`, `configured`,
  `active_subscriptions`). Never leaks the bot token.
* ``POST /telegram/webhook/{secret}`` — optional Telegram webhook receiver for
  incoming ``/subscribe`` / ``/unsubscribe`` / ``/status`` bot commands. Only
  processes an update when ``{secret}`` matches ``TELEGRAM_WEBHOOK_SECRET``.

The bridge is *fail-closed*: without ``TELEGRAM_BOT_TOKEN`` configured, every
mutation endpoint returns ``503`` and the SSE stream is untouched. The escrow
lifecycle never depends on Telegram being reachable.

Wiring into the FastAPI app is done inside :func:`init_bridge`; the app calls
:func:`fanout_event` from :func:`_broadcast_event` so every SSE event is also
delivered to matching Telegram subscribers.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Path, Request
from pydantic import BaseModel, Field, field_validator

from sdk.telegram_bridge import (
    EventFormatter,
    SubscriptionFilter,
    SubscriptionRegistry,
    TelegramAPIError,
    TelegramBridge,
    TelegramClient,
)

__all__ = [
    "router",
    "init_bridge",
    "shutdown_bridge",
    "fanout_event",
    "bridge_status",
]

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Module-level state
# --------------------------------------------------------------------------- #

# The bridge is optional. When Telegram is not configured, ``_bridge`` stays
# ``None`` and every mutation endpoint returns 503. Reads (list/status) still
# work so operators can observe the configured/unconfigured state.
_bridge: TelegramBridge | None = None
_client: TelegramClient | None = None
_registry: SubscriptionRegistry = SubscriptionRegistry()


# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #


class FilterModel(BaseModel):
    """Filter definition mirroring :class:`SubscriptionFilter`.

    Accepts either strings (Telegram-side ergonomics) or lists of strings.
    Anything else is rejected with a 422 to keep bad input out of the SDK.
    """

    event_types: list[str] | str | None = None
    service_hashes: list[str] | str | None = None
    receivers: list[str] | str | None = None

    def to_filter(self) -> SubscriptionFilter:
        return SubscriptionFilter.from_dict(self.model_dump(exclude_none=True))


class SubscribeRequest(BaseModel):
    chat_id: int = Field(..., description="Telegram chat_id to notify")
    filter: FilterModel | None = None

    @field_validator("chat_id")
    @classmethod
    def _chat_id_nonzero(cls, value: int) -> int:
        # Telegram chat_ids are never 0. Reject early so we do not accept
        # obvious misuse (e.g. clients that default an unset int field to 0).
        if value == 0:
            raise ValueError("chat_id must be non-zero")
        return value


class SubscribeResponse(BaseModel):
    sub_id: str
    chat_id: int
    filter: dict[str, list[str]]
    created_at: float


class TestSendRequest(BaseModel):
    chat_id: int = Field(..., description="Telegram chat_id to receive the smoke test")
    text: str = Field(
        default="AE402 bridge is alive",
        max_length=1024,
        description="Message body. Escaped as MarkdownV2 before send.",
    )

    @field_validator("chat_id")
    @classmethod
    def _chat_id_nonzero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("chat_id must be non-zero")
        return value


# --------------------------------------------------------------------------- #
# Bridge lifecycle
# --------------------------------------------------------------------------- #


def init_bridge(
    *,
    token: str | None = None,
    base_url: str | None = None,
    client: TelegramClient | None = None,
) -> TelegramBridge | None:
    """Initialise the Telegram bridge from environment / arguments.

    Returns the bridge on success, ``None`` when Telegram is not configured.
    Safe to call multiple times — subsequent calls replace the client and
    reset the registry so that tests can be isolated.

    Args:
        token: Override for ``TELEGRAM_BOT_TOKEN``. Tests inject a fake token
            alongside a MockTransport-backed :class:`TelegramClient`.
        base_url: Override for ``AE402_PUBLIC_BASE_URL``. Used to embed a
            deep link in every notification.
        client: Pre-built :class:`TelegramClient`. When set, ``token`` is
            ignored — this is the injection point tests use.
    """

    global _bridge, _client, _registry

    resolved_token = token or os.environ.get("TELEGRAM_BOT_TOKEN") or ""
    resolved_base_url = base_url or os.environ.get("AE402_PUBLIC_BASE_URL") or None

    # If we are given an explicit client, honour it. Otherwise skip when the
    # token is absent — the bridge stays disabled.
    if client is None:
        if not resolved_token:
            _bridge = None
            _client = None
            _registry = SubscriptionRegistry()
            return None
        client = TelegramClient(resolved_token)

    _client = client
    _registry = SubscriptionRegistry()
    formatter = EventFormatter(base_url=resolved_base_url)
    _bridge = TelegramBridge(client, _registry, formatter)
    return _bridge


async def shutdown_bridge() -> None:
    """Close the HTTP client owned by the bridge, if any.

    Idempotent; safe to call from ``lifespan`` teardown.
    """

    global _bridge, _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception as exc:  # noqa: BLE001 - shutdown must not throw
            logger.debug("telegram client close error: %s", exc)
    _bridge = None
    _client = None


def _require_bridge() -> TelegramBridge:
    """Return the bridge or raise 503.

    Every mutation endpoint funnels through this so we always fail closed
    with the same error shape when Telegram is not configured.
    """

    if _bridge is None:
        raise HTTPException(
            status_code=503,
            detail="telegram bridge disabled: TELEGRAM_BOT_TOKEN not configured",
        )
    return _bridge


def bridge_status() -> dict[str, Any]:
    """Return a stable status dict for ``GET /telegram/status``."""

    return {
        "ready": _bridge is not None,
        "configured": _bridge is not None,
        "active_subscriptions": len(_registry),
    }


async def fanout_event(event: dict[str, Any]) -> None:
    """Deliver *event* to Telegram subscribers, if the bridge is enabled.

    Called from ``server.app._broadcast_event``. Errors never propagate — the
    SSE fan-out must complete regardless of Telegram reachability.
    """

    bridge = _bridge
    if bridge is None:
        return
    try:
        await bridge.dispatch(event)
    except Exception as exc:  # noqa: BLE001 - never block SSE
        logger.warning("telegram fanout failed: %s", exc)


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.get("/status")
async def get_status() -> dict[str, Any]:
    """Report bridge readiness without exposing the bot token."""

    return bridge_status()


@router.post("/subscribe", response_model=SubscribeResponse, status_code=201)
async def subscribe(payload: SubscribeRequest) -> SubscribeResponse:
    """Register a new Telegram subscription.

    The endpoint returns ``201 Created`` with the freshly-minted subscription
    id in the body. Callers should store that id to be able to unsubscribe.
    """

    bridge = _require_bridge()
    flt = payload.filter.to_filter() if payload.filter else SubscriptionFilter()
    sub = bridge.registry.add(payload.chat_id, flt)
    return SubscribeResponse(**sub.to_dict())


@router.delete("/subscriptions/{sub_id}", status_code=204)
async def unsubscribe(sub_id: str = Path(..., min_length=1)) -> None:
    """Remove a subscription by id."""

    bridge = _require_bridge()
    if not bridge.registry.remove(sub_id):
        raise HTTPException(status_code=404, detail="subscription not found")
    return None


@router.get("/subscriptions")
async def list_subscriptions() -> dict[str, list[dict[str, Any]]]:
    """List active subscriptions. Read-only, safe when bridge is disabled."""

    return {"subscriptions": [s.to_dict() for s in _registry.list()]}


@router.post("/test")
async def test_send(payload: TestSendRequest) -> dict[str, Any]:
    """Send a smoke-test message and return the Telegram result.

    Uses ``sendMessage`` directly (not the formatter) so the operator can
    verify that the token has been granted access to the chat.
    """

    if _client is None:
        raise HTTPException(
            status_code=503,
            detail="telegram bridge disabled: TELEGRAM_BOT_TOKEN not configured",
        )
    try:
        # The test text is user-supplied but we escape it via MarkdownV2 to
        # keep the wire safe. Callers who want raw text can use their own
        # bot; this endpoint is meant for a health-check.
        from sdk.telegram_bridge import escape_markdown_v2

        result = await _client.send_message(
            payload.chat_id,
            f"*AE402 telegram bridge*\n{escape_markdown_v2(payload.text)}",
            parse_mode="MarkdownV2",
        )
    except TelegramAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "result": result}


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #


# Supported inbound commands. Each maps to a coroutine that receives the raw
# update dict + the chat_id it originated from and returns a reply text.
_HELP_TEXT = (
    "AE402 bot commands:\n"
    "/subscribe [type] — subscribe this chat (optional event-type filter)\n"
    "/unsubscribe — remove every subscription for this chat\n"
    "/status — show current bridge status"
)


def _extract_command(text: str) -> tuple[str, list[str]]:
    """Split ``/cmd@bot arg1 arg2`` into ``(cmd, [arg1, arg2])``.

    Telegram appends ``@botname`` to commands in group chats. We strip it so
    the router matches the same handler in DMs and groups.
    """

    parts = text.strip().split()
    if not parts or not parts[0].startswith("/"):
        return "", []
    head = parts[0].lstrip("/")
    if "@" in head:
        head = head.split("@", 1)[0]
    return head.lower(), parts[1:]


async def _handle_command(cmd: str, args: list[str], chat_id: int) -> str:
    """Return the reply text for a supported command."""

    if cmd == "subscribe":
        bridge = _bridge
        if bridge is None:
            return "Bridge is disabled — the operator must configure TELEGRAM_BOT_TOKEN."
        flt = SubscriptionFilter.from_dict({"event_types": args}) if args else SubscriptionFilter()
        sub = bridge.registry.add(chat_id, flt)
        summary = (
            "You will receive every AE402 event."
            if not args
            else f"You will receive events matching: {', '.join(args)}."
        )
        return f"Subscribed. {summary}\nSubscription id: {sub.sub_id}"

    if cmd == "unsubscribe":
        removed = [s for s in _registry.list() if s.chat_id == chat_id]
        for s in removed:
            _registry.remove(s.sub_id)
        if not removed:
            return "No active subscriptions for this chat."
        return f"Removed {len(removed)} subscription(s)."

    if cmd == "status":
        status = bridge_status()
        return (
            f"ready={status['ready']} "
            f"configured={status['configured']} "
            f"active_subscriptions={status['active_subscriptions']}"
        )

    return _HELP_TEXT


@router.post("/webhook/{secret}")
async def webhook(
    request: Request,
    secret: str = Path(..., min_length=1),
    update: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Receive a Telegram update and, when supported, reply to the chat.

    Security: the URL contains a shared secret that Telegram appends to every
    call. Without an exact match on ``TELEGRAM_WEBHOOK_SECRET`` we return
    ``403``. Additionally Telegram forwards the ``X-Telegram-Bot-Api-Secret-Token``
    header when it is set in ``setWebhook``; we accept either match so that
    operators can pick their transport.
    """

    expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not expected:
        raise HTTPException(status_code=503, detail="webhook disabled: TELEGRAM_WEBHOOK_SECRET not set")
    if secret != expected and header != expected:
        raise HTTPException(status_code=403, detail="webhook secret mismatch")

    message = update.get("message") or update.get("channel_post") or {}
    text = str(message.get("text") or "")
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    if not isinstance(chat_id, int) or not text.startswith("/"):
        # Unknown/unsupported update shape — ack silently so Telegram does
        # not retry, but do not respond in the chat.
        return {"ok": True, "handled": False}

    cmd, args = _extract_command(text)
    reply = await _handle_command(cmd, args, chat_id)

    # If a client is configured, best-effort reply. If not, we still handled
    # the command (state changed), so return ok:true.
    if _client is not None:
        try:
            from sdk.telegram_bridge import escape_markdown_v2

            await _client.send_message(chat_id, escape_markdown_v2(reply))
        except TelegramAPIError as exc:
            logger.info("webhook reply failed chat=%s: %s", chat_id, exc)

    # Sleep zero so we always yield to the loop even when there is no client
    # — makes the endpoint straightforward to unit-test.
    await asyncio.sleep(0)

    return {"ok": True, "handled": True, "command": cmd}
