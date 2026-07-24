# Telegram bot bridge to AE402 SSE

**Status:** additive-only. Off by default. Enabling the bridge never affects
the on-chain escrow lifecycle nor the SSE stream at `/events`.

The bridge fans out AE402 escrow lifecycle events (`escrow_created`,
`escrow_released`, `escrow_disputed`, `dispute_opened`, `escrow_resolved`,
`insurance_claimed`, …) to registered Telegram chats. Each subscription
carries a filter (event types, service hashes, receivers) so a chat can be
narrowly scoped to a single escrow, a single payee, or a single event kind.

## Threat model

* **Bot token confidentiality.** The token is only ever read from
  `TELEGRAM_BOT_TOKEN`; it is never logged, never included in error
  messages, and `TelegramClient.__repr__` explicitly redacts it. Do not
  read the token in application code — use the `TelegramClient` provided
  by `init_bridge`.
* **Webhook authentication.** The webhook receiver requires **two** shared
  secrets to be equal: the path segment `TELEGRAM_WEBHOOK_SECRET` and the
  `X-Telegram-Bot-Api-Secret-Token` header. Either match is sufficient, so
  operators can pick their transport. Without `TELEGRAM_WEBHOOK_SECRET`,
  the endpoint returns 503.
* **MarkdownV2 injection.** Every user-supplied field from the event payload
  (`service_hash`, `payer`, `payee`, `reason`, `amount`, …) is escaped for
  Telegram's MarkdownV2 syntax before it is placed in the message. A
  crafted `service_hash` can neither break out of a code span nor create
  a fake link.
* **Rate limits.** The client retries transport errors, `5xx`, and `429`
  responses. `429` honours `parameters.retry_after` (Telegram's canonical
  form) or the `Retry-After` header, both clamped to `_MAX_BACKOFF_SEC`.
  Permanent `4xx` responses raise immediately so misconfigured chats are
  detected during smoke tests instead of being silently swallowed.
* **Fan-out isolation.** A single failing chat cannot block delivery to
  other subscribers: each dispatch runs under `asyncio.gather` with
  exception handling, and any failure is logged and dropped.
* **Bridge disabled.** When `TELEGRAM_BOT_TOKEN` is unset, the bridge is
  disabled. All mutation endpoints (`POST /telegram/subscribe`,
  `DELETE /telegram/subscriptions/{id}`, `POST /telegram/test`,
  `POST /telegram/webhook/{secret}`) return `503`. Read-only endpoints
  (`GET /telegram/status`, `GET /telegram/subscriptions`) stay available
  so operators can observe the disabled state.

## Configuration

| Env var | Purpose |
| ------- | ------- |
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather. Presence enables the bridge. |
| `TELEGRAM_WEBHOOK_SECRET` | Shared secret for inbound webhook auth. Optional; without it, webhook endpoint returns 503. |
| `AE402_PUBLIC_BASE_URL` | Optional. When set, every notification contains a clickable link to `<base>/escrows/<service_hash>`. |

## HTTP surface

All endpoints live under `/telegram/*`.

### `GET /telegram/status`

Reports readiness. Never leaks the token.

```json
{ "ready": true, "configured": true, "active_subscriptions": 3 }
```

### `POST /telegram/subscribe`

Creates a subscription. Request body:

```json
{
  "chat_id": 123456789,
  "filter": {
    "event_types": ["escrow_released", "escrow_disputed"],
    "service_hashes": ["abcd1234"],
    "receivers": ["alice.did", "did:key:z6Mk..."]
  }
}
```

`filter` is optional; omitting it (or leaving every list empty) subscribes
the chat to every event.

Returns `201 Created`:

```json
{
  "sub_id": "e1c1b0…",
  "chat_id": 123456789,
  "filter": {
    "event_types": ["escrow_released", "escrow_disputed"],
    "service_hashes": ["abcd1234"],
    "receivers": ["alice.did", "did:key:z6Mk..."]
  },
  "created_at": 1721822400.42
}
```

### `DELETE /telegram/subscriptions/{sub_id}`

Removes a subscription. Returns `204 No Content` on success, `404` when the
id is unknown.

### `GET /telegram/subscriptions`

Lists active subscriptions. Read-only; safe when the bridge is disabled.

### `POST /telegram/test`

Sends a smoke-test message. Useful when onboarding a new chat: the operator
adds the bot to the chat, then hits this endpoint to confirm the token has
permission to post there.

```json
{ "chat_id": 123456789, "text": "AE402 bridge is alive" }
```

`text` is escaped as MarkdownV2 before send. A permanent Telegram error is
returned as `502` so it never looks like a bug in AE402.

### `POST /telegram/webhook/{secret}`

Handles inbound updates from Telegram's setWebhook. Supports three
commands:

* `/subscribe [event_type …]` — subscribe this chat. Additional args are
  interpreted as an `event_types` filter.
* `/unsubscribe` — remove **every** subscription for this chat.
* `/status` — reply with the current bridge status.

The bot suffix (`/status@your_bot`) is stripped so the same handler runs in
DMs and group chats. Unsupported updates are acknowledged silently — the
endpoint always returns `200 OK` so Telegram does not retry.

## Worked example

Suppose we want to notify a chat every time an escrow with a particular
service hash is released or disputed.

```bash
curl -X POST https://ae402.example.com/telegram/subscribe \
  -H 'content-type: application/json' \
  -d '{
        "chat_id": 987654321,
        "filter": {
          "event_types": ["escrow_released", "escrow_disputed"],
          "service_hashes": ["deadbeef" ]
        }
      }'
```

When the escrow with hash `deadbeef` is released, the SSE stream still
delivers `{"type":"escrow_released", "service_hash":"deadbeef", ...}` to
existing subscribers, and additionally the bridge posts to the Telegram
chat:

```
✅ *Escrow released*
*hash:* `deadbeef`
_2026-07-24T14:00:00Z_
[view escrow](https://ae402.example.com/escrows/deadbeef)
```

## Relationship to existing routes

The bridge does not consume the `/events` SSE stream — it is invoked from
inside `_broadcast_event`, which is the same fan-out primitive the SSE
route uses. That means the two channels always see the same event set and
cannot drift.

## Not covered

* Two-way message routing beyond `/subscribe`, `/unsubscribe`, `/status`.
  The bridge intentionally does not expose escrow mutations via Telegram.
* Multiple bot instances. The bridge assumes a single bot per pod. Running
  two AE402 pods that share a bot token is out of scope.
