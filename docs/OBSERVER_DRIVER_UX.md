# Observer / Driver console mode

The AE402 console can be operated in two clearly-labelled modes. The
choice lives entirely in the browser — it is a **frontend policy fence**,
not a backend permission.

- **Observer** (default): read-only. The console reads live data from the
  hosted backend, subscribes to the SSE lifecycle stream, and lets the
  visitor navigate the entire product; but every write action (creating an
  escrow, releasing / refunding / disputing an existing one, registering
  or slashing an identity, depositing to or claiming from the insurance
  pool, running any admin operation) is refused. Regulators, auditors,
  hackathon judges, and external reviewers use this mode.
- **Driver**: full authority. Every write action is enabled. This is the
  mode a real integrator uses to act on behalf of an agent, either with
  the hosted demo signer or with their own connected wallet.

## Where the mode is set

- A segmented Observer / Driver control sits in the console top bar, next
  to the wallet indicator, on every `/console/*` route.
- The default on first visit is **Observer**, so a random reviewer can
  never accidentally seed junk records on the shared testnet backend.
- Flipping to Driver requires an explicit confirm dialog. Cross-tab
  changes propagate through the `storage` event so all open tabs stay in
  sync.
- The choice is persisted in `localStorage` under the key
  `ae402_console_role` and reflected on the `<html>` element as
  `data-console-role="observer" | "driver"`, which non-React callers can
  inspect if needed.

## What Observer mode blocks

Three concentric layers, each one sufficient on its own:

1. **UI layer** — every write CTA (Create Escrow, Release, Refund,
   Dispute, Resolve, Register Agent, Delegate Capability, Deposit to /
   Claim from Insurance Pool, Register Identity, Record Deals, Apply
   Decay, Slash, Advance Verification, Add Capability) is rendered
   `disabled` with a title tooltip explaining Observer mode.
2. **Action-hook layer** — the shared browser-side write helpers
   (`useLifecycleAction`, `useCreateEscrowAction`,
   `useInsuranceClaimAction`, `useCep18PermitDeposit`) short-circuit
   *before* touching the wallet or the network, returning the Observer
   error message.
3. **API-client layer** — the shared `fetcher` in `lib/api.ts` refuses
   any non-GET request when the console is in Observer mode, returning
   `{ status: 403, error: "Observer mode is read-only…" }`. Idempotent
   compute-only POST endpoints (`/compute-hash`, `/estimate`) are
   allow-listed since they never change backend state.

The layers are additive, so a raw `api.releaseEscrow(...)` call from
anywhere in the codebase — even from a component that forgot to disable
its button — is still refused.

## What Observer mode does NOT block

- Any read operation: `/escrows`, `/agents`, `/health`, `/stats`,
  `/registry/*` read endpoints, the SSE `/events` stream, wasm/artifact
  downloads.
- Compute-only POST endpoints on the allow-list (`/compute-hash`,
  `/estimate`) — these never mutate state.
- Wallet connection itself: a reviewer can inspect a wallet's own
  identity without being able to sign anything.

## What this is NOT

**This is a UX affordance, not an authorisation boundary.** Anyone who
opens the browser devtools can flip `data-console-role` back to
`driver` locally; the hosted backend still trusts whatever a signed
wallet is authorised for. The purpose of Observer mode is to make the
default posture safe for third-party reviewers and to communicate the
sensitivity of a write action, not to enforce a permission model. Real
authorisation lives in the escrow contract on Casper (only the escrow's
sender/receiver can drive its lifecycle) and in the hosted x402 payment
header.

## Extending

Adding a new write endpoint or component:

1. If the write goes through one of the four action hooks, no work
   needed — the hook already short-circuits.
2. If it uses `api.*` directly, no work needed either — `fetcher`'s
   `isObserverBlocked` guard catches it.
3. Update the button's `disabled` prop and `title` for the visual
   affordance: `disabled={isObserver} title={isObserver ? blockedReason : ...}`.
4. If a new POST endpoint is idempotent / compute-only (a la
   `/compute-hash`), add its prefix to `OBSERVER_ALLOWED_POST_PREFIXES`
   in `lib/api.ts` so Observer mode still permits it.

## Related non-goals (per the deadline scope)

- **Hosted MCP playground** is a separate follow-up (see 8b) — it is
  purely a builder-tool surface, not a role.
- **CLI** is 8c — same story.
