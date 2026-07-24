# Timelocked Admin + Renounce Lifecycle

Additive governance layer on top of the existing installer-only admin
routes (`server/admin_api.py`). Wraps every mutating admin action into
a two-step lifecycle: **queue → wait `min_delay_seconds` → execute**,
plus a terminal one-way **renounce**.

## Threat model

The escrow contract's admin actions (`configure_fee`, `set_release_cap`,
`set_arbiters`, `emergency_freeze`, `unfreeze`) originally executed
immediately against the deployer key. Any leak of `X-Admin-Key` or the
deployer secret would let the attacker rug-pull the escrow in a single
call.

The timelock buys operators **`min_delay_seconds` of public visibility**
before any admin change lands. Users watching `/timelock/actions` (or a
signed event feed built on top of it) can:
- see a hostile action being queued,
- withdraw funds through the normal escrow flow before the delay elapses,
- react (rotate keys, cancel the pending action, freeze the system) with
  time to spare.

**Renounce** goes further: it flips a one-way flag that permanently
disables every mutating timelock route (and cancels every pending
action). It is the on-ramp to a governance handover — once renounce is
called, no admin key can move the fee, cap, arbiters, or freeze state
via this router again.

**Non-goals.** The layer does not protect against:
- direct calls to the raw `/admin/*` router (retire that router once
  the timelock is live — see *Deployment* below);
- direct calls to the underlying Casper contract with the installer key
  (mitigate at the key-custody layer);
- a compromised timelock router itself (mitigate by putting the timelock
  behind mTLS / an internal-only network).

## API

All routes require `X-Admin-Key`. If the env var is unset, every route
returns 503.

| Route | Purpose |
|---|---|
| `POST /timelock/queue` | Enqueue an admin action; returns `action_id` and `ready_at`. |
| `POST /timelock/execute/{action_id}` | Executes iff now ≥ `ready_at`. |
| `POST /timelock/cancel/{action_id}` | Cancel a pending action (idempotent on already-cancelled). |
| `GET  /timelock/actions` | List all actions (pending + settled). |
| `GET  /timelock/actions/{id}` | Fetch one action. |
| `GET  /timelock/status` | `min_delay_seconds`, `renounced`, counts. |
| `POST /timelock/renounce` | Terminal, one-way. Cancels every pending action. |

### Allowed action types

Whitelisted at queue-time; unknown types are refused with 400.

| `action_type` | `params` |
|---|---|
| `configure_fee` | `{"new_fee_bps": int}` |
| `set_release_cap` | `{"new_cap_motes": int}` |
| `set_arbiters` | `{"arbiters": [str]}` |
| `emergency_freeze` | `{}` |
| `unfreeze` | `{}` |
| `set_delay` | `{"new_delay_seconds": int}` — monotonic; can only grow |

### Response codes

- `200` — success
- `400` — unknown action_type / missing / extra params
- `403` — missing / wrong `X-Admin-Key`
- `404` — unknown action_id
- `409` — action already executed or cancelled; or set_delay would shrink
- `410` — admin renounced (queue / execute refused)
- `425` — execute called before `ready_at`
- `502` — on-chain execution failed
- `503` — `ADMIN_API_KEY` not configured

## Config

| Env | Default | Meaning |
|---|---|---|
| `ADMIN_API_KEY` | *(unset → 503)* | Shared secret required on every timelock route. |
| `TIMELOCK_DELAY_SECONDS` | `86400` (24h) | Default `min_delay_seconds` at boot. Bump via `POST /timelock/queue` with `action_type=set_delay`. |

## Worked example

```bash
# 1. Propose a fee change; delay is public
curl -X POST http://host/timelock/queue \
  -H "X-Admin-Key: $ADMIN_API_KEY" \
  -d '{"action_type":"configure_fee","params":{"new_fee_bps":25}}'
# -> {"action_id": 1, "ready_at": 1721664000, ...}

# 2. Anyone can inspect
curl http://host/timelock/actions -H "X-Admin-Key: $ADMIN_API_KEY"

# 3. After 24h, admin executes
curl -X POST http://host/timelock/execute/1 -H "X-Admin-Key: $ADMIN_API_KEY"
# -> {"state":"executed", "result":{"deploy_hash":"..."}}

# 4. If something is wrong, cancel before ready_at
curl -X POST http://host/timelock/cancel/1 \
  -H "X-Admin-Key: $ADMIN_API_KEY" \
  -d '{"reason":"discovered bug in proposed cap"}'

# 5. Final step in governance handover: renounce
curl -X POST http://host/timelock/renounce -H "X-Admin-Key: $ADMIN_API_KEY"
# -> {"renounced": true, "cancelled_pending": [...]}
```

## Deployment checklist

1. Set `ADMIN_API_KEY` (long random) and `TIMELOCK_DELAY_SECONDS` (24h+ recommended).
2. Publish the endpoint (or a read-only mirror of `/timelock/actions`) so
   watchers can monitor.
3. **Retire `/admin/*` calls** — either remove the router from `app.py`
   or gate it behind a network policy that only accepts calls from the
   timelock router itself.
4. Test the flow end-to-end in sandbox (`SANDBOX=true`) before enabling
   live mode.
5. When ready for handover, call `POST /timelock/renounce`. This is
   irreversible.

## Guarantees (checked by property tests)

- **Timelock**: `execute()` at `t` fails unless `t ≥ ready_at`.
- **Delay monotonicity**: `set_delay(d)` fails if `d < current`.
- **Renounce is terminal**: after renounce, every `queue()` / `execute()`
  / `set_delay()` raises `RenouncedError`.
- **Renounce cancels pending**: every `Pending` action becomes `Cancelled`
  with `cancel_reason="renounce"`.
- **Renounce is idempotent**: second call is a no-op; original
  `renounced_at` is preserved.
- **Executed actions are immutable**: renounce and further cancel calls
  do not touch them.
- **Action id monotonicity**: strictly increasing uint64 per Registry.
- **Params isolation**: mutation of the input dict after queue does not
  affect the stored action.
- **Executor errors leave state Pending**: caller can retry.

## Files

| Path | Purpose |
|---|---|
| `sdk/admin_timelock.py` | Pure state machine (framework-agnostic, zero deps). |
| `server/timelock_api.py` | FastAPI router; wires state machine to Casper client. |
| `tests/test_admin_timelock.py` | 31 property tests over the state machine. |
| `tests/test_timelock_api.py` | 18 HTTP tests over the router. |
| `docs/TIMELOCK_ADMIN.md` | This document. |
