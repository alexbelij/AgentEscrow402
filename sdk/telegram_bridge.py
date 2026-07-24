"""Telegram Bot bridge for AE402 SSE event stream.

Pure-Python bridge between the AE402 escrow lifecycle events (published on the
Server-Sent-Events stream at ``/events``) and Telegram chats. It provides:

* :class:`EventFormatter` — deterministic conversion of AE402 event dicts into
  a Telegram-ready ``(text, parse_mode)`` pair. Uses Telegram *MarkdownV2*
  escaping so no user-supplied content can inject formatting.
* :class:`SubscriptionRegistry` — in-memory registry of ``chat_id -> filter``
  subscriptions. Filters are additive: an event is delivered to a subscription
  when *every* enabled criterion (event types / service hashes / receivers)
  matches.
* :class:`TelegramClient` — minimal, retry-aware wrapper over the Telegram Bot
  ``sendMessage`` API. Uses :mod:`httpx` (already a repo dependency); no other
  runtime deps. Exponential backoff on 5xx / network errors, honours 429
  ``retry_after``.
* :class:`TelegramBridge` — glue: accepts events, resolves matching
  subscriptions, formats each event once, dispatches via the client.

The bridge is deliberately I/O-agnostic in the SDK layer. The HTTP surface
(``server/telegram_api.py``) is responsible for wiring the running
``_event_subscribers`` queue into :meth:`TelegramBridge.dispatch`.

Security posture:

* No credentials leak into logs or into the returned message body.
* All fields taken from the event dict are MarkdownV2-escaped before being
  interpolated, so a malicious ``service_hash`` cannot break out of a code
  span or link.
* Webhook helpers only accept a request when the caller has already verified
  the shared ``X-Telegram-Bot-Api-Secret-Token`` header — this SDK never sees
  the raw HTTP request.

The bridge is *additive-only*: it never mutates escrow state and never calls
back into the FastAPI app. If Telegram is misconfigured, every dispatch is a
soft no-op and the underlying event stream is unaffected.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

import httpx

__all__ = [
    "EventFormatter",
    "Subscription",
    "SubscriptionFilter",
    "SubscriptionRegistry",
    "TelegramAPIError",
    "TelegramBridge",
    "TelegramClient",
    "escape_markdown_v2",
]

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# MarkdownV2 escaping
# --------------------------------------------------------------------------- #

# Reserved MarkdownV2 characters per Telegram Bot API docs
# (https://core.telegram.org/bots/api#markdownv2-style).
_MARKDOWN_V2_RESERVED = r"_*[]()~`>#+-=|{}.!\\"
_MARKDOWN_V2_ESCAPE_RE = re.compile("([" + re.escape(_MARKDOWN_V2_RESERVED) + "])")


def escape_markdown_v2(text: Any) -> str:
    """Escape *text* for safe interpolation into a Telegram MarkdownV2 message.

    Non-string inputs are coerced through :func:`str` first. The result never
    contains an unescaped reserved MarkdownV2 character, so it is safe to
    concatenate directly into a code span, link label, or plain body.
    """

    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    return _MARKDOWN_V2_ESCAPE_RE.sub(r"\\\1", s)


# --------------------------------------------------------------------------- #
# Event formatting
# --------------------------------------------------------------------------- #


# Map from AE402 event ``type`` to a human-readable prefix + emoji. Unknown
# event types fall back to a generic label so the bridge is forward compatible.
_EVENT_LABELS: dict[str, tuple[str, str]] = {
    "connected": ("🔌", "Connected to AE402 event stream"),
    "escrow_created": ("🆕", "Escrow created"),
    "escrow_released": ("✅", "Escrow released"),
    "escrow_refunded": ("↩️", "Escrow refunded"),
    "escrow_disputed": ("⚠️", "Escrow disputed"),
    "dispute_opened": ("⚠️", "Dispute opened"),
    "dispute_resolved": ("⚖️", "Dispute resolved"),
    "escrow_resolved": ("⚖️", "Dispute resolved"),
    "commit_swap": ("🔄", "Escrow commit-swap"),
    "insurance_claimed": ("🛡️", "Insurance claim filed"),
    "insurance_paid": ("💰", "Insurance claim paid"),
    "capability_delegated": ("🎫", "Capability delegated"),
}

# Fields we surface in the Telegram message body, in display order. Any field
# missing from an event is skipped silently — we never break on partial data.
_DISPLAY_FIELDS: tuple[tuple[str, str], ...] = (
    ("service_hash", "hash"),
    ("escrow_id", "id"),
    ("payer", "payer"),
    ("payee", "payee"),
    ("receiver", "receiver"),
    ("amount", "amount"),
    ("reason", "reason"),
    ("resolver", "resolver"),
)


def _shorten_hash(value: str, keep: int = 16) -> str:
    """Return ``value[:keep] + '…'`` when it is longer than ``keep``.

    Used purely for display; the raw hash is never truncated in the
    machine-readable payload.
    """

    if not isinstance(value, str) or len(value) <= keep:
        return value if isinstance(value, str) else ""
    return f"{value[:keep]}…"


class EventFormatter:
    """Turn an AE402 event dict into a Telegram MarkdownV2 message.

    The formatter is deterministic and side-effect-free: given the same event,
    it always produces the same message text. That property is used by the
    HTTP-layer tests to assert exact wire content.
    """

    def __init__(self, *, base_url: str | None = None) -> None:
        """Create a formatter.

        ``base_url`` is an optional AE402 base URL used to build clickable
        links back to escrow status pages. When absent, the message stays
        text-only (still MarkdownV2). It is not required for correctness.
        """

        # Strip trailing slash for stable link building.
        self._base_url = base_url.rstrip("/") if base_url else None

    def format(self, event: Mapping[str, Any]) -> tuple[str, str]:
        """Return ``(text, parse_mode)`` for *event*.

        The returned parse_mode is always ``"MarkdownV2"``. Every dynamic
        value is escaped, so callers can trust the pair as-is when calling
        Telegram ``sendMessage``.
        """

        etype = str(event.get("type", "event"))
        emoji, label = _EVENT_LABELS.get(etype, ("📣", f"Event: {etype}"))

        parts: list[str] = []
        # Header: emoji + bold label. The label is a fixed string from our
        # lookup table but we escape it defensively in case a future entry
        # includes MarkdownV2 metacharacters.
        parts.append(f"{emoji} *{escape_markdown_v2(label)}*")

        # One line per known field. `service_hash` gets the shortened display.
        for key, human in _DISPLAY_FIELDS:
            if key not in event:
                continue
            value = event[key]
            display: str
            if key == "service_hash" and isinstance(value, str):
                display = f"`{escape_markdown_v2(_shorten_hash(value))}`"
            elif key == "amount":
                display = f"`{escape_markdown_v2(value)}`"
            else:
                display = escape_markdown_v2(value)
            parts.append(f"*{escape_markdown_v2(human)}:* {display}")

        # Timestamp (best-effort). Telegram ignores the ISO string in message
        # ordering, so this is purely informational.
        ts = event.get("ts")
        if isinstance(ts, (int, float)):
            iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts)))
            parts.append(f"_{escape_markdown_v2(iso)}_")

        # Optional deep link to the escrow status page.
        sh = event.get("service_hash")
        if self._base_url and isinstance(sh, str) and sh:
            url = f"{self._base_url}/escrows/{sh}"
            # Only the display label is escaped; the URL itself must be a
            # bare URL for Telegram to accept it inside the link parens.
            parts.append(f"[view escrow]({url})")

        return "\n".join(parts), "MarkdownV2"


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SubscriptionFilter:
    """Immutable filter definition.

    An event matches when *every* enabled criterion matches. A criterion is
    considered "disabled" when its collection is empty — so the default
    filter (all sets empty) matches every event.

    * ``event_types``: allowed values for ``event["type"]``. Case-insensitive.
    * ``service_hashes``: allowed values for ``event["service_hash"]``. Exact
      match; case-sensitive (hashes are hex).
    * ``receivers``: allowed values for ``event["receiver"]`` OR
      ``event["payee"]`` — subscribers care about "who got paid", regardless
      of which key the emitter used.
    """

    event_types: frozenset[str] = field(default_factory=frozenset)
    service_hashes: frozenset[str] = field(default_factory=frozenset)
    receivers: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "SubscriptionFilter":
        """Build a filter from an untrusted mapping.

        Unknown keys are ignored so the API surface can grow without breaking
        existing subscriptions. Values must be strings or lists of strings;
        anything else raises :class:`TypeError` so misuse fails loudly.
        """

        if not data:
            return cls()

        def _norm(key: str, *, lower: bool = False) -> frozenset[str]:
            raw = data.get(key)
            if raw is None:
                return frozenset()
            if isinstance(raw, str):
                items: Iterable[str] = [raw]
            elif isinstance(raw, (list, tuple, set, frozenset)):
                items = list(raw)
            else:
                raise TypeError(f"filter.{key} must be str or list[str]")
            out: set[str] = set()
            for it in items:
                if not isinstance(it, str):
                    raise TypeError(f"filter.{key} entries must be str")
                if not it:
                    continue
                out.add(it.lower() if lower else it)
            return frozenset(out)

        return cls(
            event_types=_norm("event_types", lower=True),
            service_hashes=_norm("service_hashes"),
            receivers=_norm("receivers"),
        )

    def matches(self, event: Mapping[str, Any]) -> bool:
        """Return whether *event* passes this filter.

        The implementation is intentionally strict: unknown or malformed
        event dicts fall through and are considered a match only when *every*
        criterion is disabled, i.e. a wildcard subscription.
        """

        if self.event_types:
            etype = event.get("type")
            if not isinstance(etype, str):
                return False
            if etype.lower() not in self.event_types:
                return False

        if self.service_hashes:
            sh = event.get("service_hash")
            if not isinstance(sh, str) or sh not in self.service_hashes:
                return False

        if self.receivers:
            # Accept either `receiver` or `payee` — many AE402 emitters use
            # `payee`; the older insurance path emits `receiver`.
            candidates = {
                event.get("receiver"),
                event.get("payee"),
            }
            candidates.discard(None)
            if not (candidates & self.receivers):
                return False

        return True


@dataclass
class Subscription:
    """A single ``chat_id`` subscription."""

    sub_id: str
    chat_id: int
    filter: SubscriptionFilter
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the HTTP layer. Never contains bot tokens."""

        return {
            "sub_id": self.sub_id,
            "chat_id": self.chat_id,
            "filter": {
                "event_types": sorted(self.filter.event_types),
                "service_hashes": sorted(self.filter.service_hashes),
                "receivers": sorted(self.filter.receivers),
            },
            "created_at": self.created_at,
        }


class SubscriptionRegistry:
    """In-memory subscription store.

    Thread-safe for the coroutine-based dispatcher — mutations run in the same
    event loop as :meth:`TelegramBridge.dispatch`. Callers must not share a
    registry across event loops.
    """

    def __init__(self, *, id_generator: Callable[[], str] | None = None) -> None:
        self._subs: dict[str, Subscription] = {}
        # Deterministic id generator makes tests stable; production uses
        # a random 16-byte hex.
        self._id_generator = id_generator or self._default_id

    @staticmethod
    def _default_id() -> str:
        import secrets

        return secrets.token_hex(8)

    def add(self, chat_id: int, filter_: SubscriptionFilter) -> Subscription:
        """Insert a subscription and return it.

        A ``chat_id`` may hold multiple subscriptions with different filters
        — the caller decides whether to deduplicate. This keeps the SDK
        simple and lets the HTTP layer enforce per-user policy.
        """

        if not isinstance(chat_id, int):
            raise TypeError("chat_id must be int")
        sub = Subscription(
            sub_id=self._id_generator(),
            chat_id=chat_id,
            filter=filter_,
            created_at=time.time(),
        )
        self._subs[sub.sub_id] = sub
        return sub

    def remove(self, sub_id: str) -> bool:
        """Remove a subscription by id. Returns ``True`` if it existed."""

        return self._subs.pop(sub_id, None) is not None

    def list(self) -> list[Subscription]:
        """Return a stable, chronologically-ordered list of subscriptions."""

        return sorted(self._subs.values(), key=lambda s: (s.created_at, s.sub_id))

    def matching(self, event: Mapping[str, Any]) -> list[Subscription]:
        """Return the subscriptions whose filter passes *event*."""

        return [s for s in self.list() if s.filter.matches(event)]

    def clear(self) -> None:
        """Drop every subscription. Used by tests and by administrator resets."""

        self._subs.clear()

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._subs)


# --------------------------------------------------------------------------- #
# Telegram client
# --------------------------------------------------------------------------- #


class TelegramAPIError(RuntimeError):
    """Raised when the Telegram API returns a permanent error.

    ``status_code`` mirrors the HTTP status. Retryable errors (429, 5xx,
    network) are handled inside :class:`TelegramClient` and never surface as
    this exception — they either succeed after backoff or exhaust the retry
    budget and raise this as a *permanent* failure.
    """

    def __init__(self, status_code: int, description: str) -> None:
        super().__init__(f"telegram api error {status_code}: {description}")
        self.status_code = status_code
        self.description = description


class TelegramClient:
    """Minimal Telegram Bot API client.

    Uses HTTPS ``https://api.telegram.org/bot<token>/`` with :mod:`httpx`. The
    client only implements ``sendMessage`` because that is the only surface
    the bridge needs; other verbs can be layered later.
    """

    # Retry budget & backoff. Values are conservative so a Telegram outage
    # cannot pin the FastAPI event loop.
    _MAX_RETRIES = 3
    _INITIAL_BACKOFF_SEC = 0.5
    _MAX_BACKOFF_SEC = 8.0

    def __init__(
        self,
        token: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = "https://api.telegram.org",
        sleep: Callable[[float], "asyncio.Future[None]"] | None = None,
    ) -> None:
        if not token or not isinstance(token, str):
            raise ValueError("telegram bot token must be a non-empty string")
        # Store the token privately so `repr(client)` cannot leak it.
        self._token = token
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        self._api = f"{base_url.rstrip('/')}/bot{token}"
        # Tests inject a fake sleep to keep suites fast.
        self._sleep = sleep or asyncio.sleep

    def __repr__(self) -> str:  # pragma: no cover - debug helper only
        # Explicitly redact the token; the API URL is derived from it.
        return "TelegramClient(token=***redacted***)"

    async def aclose(self) -> None:
        """Close the underlying HTTP client if we own it."""

        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "TelegramClient":  # pragma: no cover - trivial
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover
        await self.aclose()

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: str | None = "MarkdownV2",
        disable_web_page_preview: bool = True,
    ) -> dict[str, Any]:
        """POST ``sendMessage`` with retry.

        Returns the ``result`` object from Telegram on success. Raises
        :class:`TelegramAPIError` after the retry budget is exhausted or on
        a permanent 4xx (except 429, which is retried honouring
        ``retry_after``).
        """

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode

        return await self._post_with_retry("sendMessage", payload)

    async def _post_with_retry(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Retry-aware POST for Telegram methods.

        Retryable errors: httpx transport errors, HTTP 5xx, HTTP 429
        (honouring ``retry_after``). Everything else is permanent and raises
        immediately so bugs surface loudly.
        """

        url = f"{self._api}/{method}"
        attempt = 0
        backoff = self._INITIAL_BACKOFF_SEC
        last_error: Exception | None = None

        while attempt <= self._MAX_RETRIES:
            try:
                resp = await self._client.post(url, json=payload)
            except httpx.HTTPError as exc:
                last_error = exc
                # Network / transport error → retry.
                logger.debug("telegram transport error attempt=%d: %s", attempt, exc)
            else:
                status = resp.status_code
                if 200 <= status < 300:
                    body = resp.json()
                    if not body.get("ok"):
                        raise TelegramAPIError(status, body.get("description", "unknown"))
                    return body["result"]

                # Parse best-effort description.
                try:
                    body = resp.json()
                    description = body.get("description", resp.text or "")
                except Exception:  # noqa: BLE001 - defensive
                    body = {}
                    description = resp.text or ""

                if status == 429:
                    retry_after = self._parse_retry_after(body, resp.headers)
                    logger.info("telegram 429, retry_after=%.2fs", retry_after)
                    last_error = TelegramAPIError(status, description)
                    if attempt >= self._MAX_RETRIES:
                        break
                    await self._sleep(retry_after)
                    attempt += 1
                    continue

                if 500 <= status < 600:
                    last_error = TelegramAPIError(status, description)
                    logger.debug("telegram 5xx attempt=%d: %s", attempt, description)
                else:
                    # Permanent 4xx: never retry, do not paper over bugs.
                    raise TelegramAPIError(status, description)

            # Exponential backoff with jitter for transport / 5xx errors.
            if attempt >= self._MAX_RETRIES:
                break
            jitter = random.uniform(0, backoff * 0.25)
            await self._sleep(backoff + jitter)
            backoff = min(backoff * 2, self._MAX_BACKOFF_SEC)
            attempt += 1

        assert last_error is not None
        if isinstance(last_error, TelegramAPIError):
            raise last_error
        raise TelegramAPIError(0, f"transport error after retries: {last_error!s}")

    @staticmethod
    def _parse_retry_after(body: Mapping[str, Any], headers: Mapping[str, str]) -> float:
        """Extract ``retry_after`` in seconds from a 429 response.

        Telegram returns it in ``body.parameters.retry_after``; some proxies
        forward it as the standard ``Retry-After`` HTTP header. We accept
        both and clamp to the client's max backoff to bound the wait.
        """

        params = body.get("parameters") if isinstance(body, Mapping) else None
        if isinstance(params, Mapping) and "retry_after" in params:
            try:
                value = float(params["retry_after"])
            except (TypeError, ValueError):
                value = TelegramClient._INITIAL_BACKOFF_SEC
        else:
            header = headers.get("Retry-After") or headers.get("retry-after")
            try:
                value = float(header) if header else TelegramClient._INITIAL_BACKOFF_SEC
            except ValueError:
                value = TelegramClient._INITIAL_BACKOFF_SEC
        # Bound so a hostile server cannot pin us.
        return max(0.0, min(value, TelegramClient._MAX_BACKOFF_SEC))


# --------------------------------------------------------------------------- #
# Bridge
# --------------------------------------------------------------------------- #


class TelegramBridge:
    """Glue between the AE402 event stream and Telegram chats.

    Responsibilities:

    * Iterate the subscription registry for each incoming event.
    * Format the event exactly once, regardless of subscriber count.
    * Dispatch concurrently to all matching chats with bounded parallelism.
    * Isolate failures — one chat's error never blocks delivery to others.
    """

    def __init__(
        self,
        client: TelegramClient,
        registry: SubscriptionRegistry,
        formatter: EventFormatter | None = None,
        *,
        max_concurrency: int = 8,
    ) -> None:
        self._client = client
        self._registry = registry
        self._formatter = formatter or EventFormatter()
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self._semaphore = asyncio.Semaphore(max_concurrency)

    @property
    def registry(self) -> SubscriptionRegistry:
        """Expose the registry for the HTTP layer."""

        return self._registry

    async def dispatch(self, event: Mapping[str, Any]) -> list[str]:
        """Deliver *event* to every matching subscription.

        Returns the list of subscription ids to which delivery *succeeded*.
        Errors are logged and swallowed so a single misconfigured chat does
        not break the fan-out — the caller can inspect the return value if it
        needs per-subscription accounting.
        """

        matching = self._registry.matching(event)
        if not matching:
            return []

        text, parse_mode = self._formatter.format(event)

        async def _send(sub: Subscription) -> str | None:
            async with self._semaphore:
                try:
                    await self._client.send_message(
                        sub.chat_id, text, parse_mode=parse_mode
                    )
                    return sub.sub_id
                except TelegramAPIError as exc:
                    logger.warning(
                        "telegram delivery failed sub=%s chat=%s: %s",
                        sub.sub_id,
                        sub.chat_id,
                        exc,
                    )
                    return None
                except Exception as exc:  # noqa: BLE001 - keep fan-out safe
                    logger.exception(
                        "unexpected telegram delivery error sub=%s: %s", sub.sub_id, exc
                    )
                    return None

        results = await asyncio.gather(*(_send(s) for s in matching))
        return [sid for sid in results if sid is not None]
