# @ae402/sdk — AgentEscrow402 TypeScript SDK

A **publishable, zero-dependency** TypeScript SDK for AgentEscrow402:
the read-only HTTP client, Ed25519 signature verification for arbiter
votes / cap approvals / insurance claims, and **HMAC-SHA256 webhook
signature verification** — everything a downstream Node or modern-browser
agent needs to look up an escrow, verify a signature it was handed, and
authenticate a webhook delivery.

The **write path** (`createEscrow`, `release`, `refund`, `dispute`,
`resolve`, batch ops, VRF election, streaming claim) stays in the
Python SDK (`sdk/`) — it requires the full x402
signing flow. This package covers "look something up" and "verify
something I was handed", which is what most integrators actually need.

## Install

Once published to npm (see [Publishing](#publishing) — publish itself is
out of scope for this repo, but the package config is fully wired):

```bash
npm install @ae402/sdk
# or
pnpm add @ae402/sdk
# or
yarn add @ae402/sdk
```

Vendorable use (no npm) is still supported — see [Vendoring](#vendoring).

## Zero dependencies

Ed25519 verification uses Node's built-in `crypto.webcrypto.subtle`
(`Ed25519` is natively supported since Node 19+, confirmed on Node 24 in
this repo's environment). HTTP calls use the global `fetch`. HMAC-SHA256
webhook verification uses the same `webcrypto.subtle` primitive. This
keeps the SDK free of `@noble/ed25519`, `tweetnacl`, `axios`, or any
other third-party runtime dependency.

## Quick start

```ts
import {
  AgentEscrow402ReadClient,
  verifyEd25519Vote,
  buildResolveMessage,
  verifyWebhookSignature,
} from "@ae402/sdk";

// 1. Read-only client
const client = new AgentEscrow402ReadClient("https://agentescrow402-api-ywm8.onrender.com");
const escrow = await client.getEscrow("deadbeef...");

// 2. Verify an arbiter vote
const msg = buildResolveMessage(escrow.service_hash, "beneficiary_pubkey_hex");
const ok = await verifyEd25519Vote(msg, "arbiter_pubkey_hex", "sig_hex");

// 3. Verify a webhook delivery
const parsed = await verifyWebhookSignature(
  rawRequestBody,
  request.headers["x-ae402-signature"],
  process.env.AE402_WEBHOOK_SECRET!,
);
console.log(parsed.type, parsed.data);
```

## Modules

- **`@ae402/sdk/client`** — `AgentEscrow402ReadClient`: `getEscrow`,
  `getReputation`, `riskScore`, `health`. Read-only, unauthenticated —
  matches the unauthenticated GET routes in `server/app.py` (no
  `X-Payment` / `X-402-Auth` header required for these endpoints).
- **`@ae402/sdk/verify`** — canonical-message builders
  (`buildResolveMessage`, `buildCapApprovalMessage`,
  `buildInsuranceClaimMessage`) and `verifyEd25519Vote`,
  `countValidVotes`, `countValidCapApprovalVotes`,
  `countValidInsuranceClaimVotes`, byte-for-byte mirroring
  `server/arbiter_crypto.py`'s tag-prefixed-hex Ed25519 checks.
  Checkpoint-signature verification (see `server/audit_log.py`) is
  planned for a follow-up release.
- **`@ae402/sdk/webhooks`** — `verifyWebhookSignature` and
  `signWebhookPayload` for `X-AE402-Signature: t=<ts>,v1=<hex>` headers.
  Constant-time comparison, configurable ±tolerance (default 300s to
  reject replays), rolling-secret support (multiple `v1=` entries),
  forward-compat with a future `v2=` scheme (unknown keys are ignored).
- **`@ae402/sdk/types`** — `TokenType`, `EscrowStatus`, `EscrowResponse`,
  `ReputationResponse`, `HealthResponse`, `WebhookEvent`, mirroring
  `sdk/agentescrow402/models.py`.
- **`@ae402/sdk/errors`** — `AgentEscrowError` (base), `APIError`,
  `BadRequestError`, `UnauthorizedError`, `ForbiddenError`,
  `NotFoundError`, `ConflictError`, and the `errorForStatus` factory
  the read client uses.

Barrel import (`import { … } from "@ae402/sdk"`) re-exports everything
above. Sub-path imports are preserved so tree-shaking picks up only
what you use.

## Webhook signature scheme

The `X-AE402-Signature` header follows the Stripe / GitHub convention:

```
X-AE402-Signature: t=1752000100,v1=deadbeef…64hex
```

- `t=` — unix seconds when the server emitted the event.
- `v1=` — HMAC-SHA256 hex digest of `"{t}.{raw_body}"` using the
  endpoint's shared secret.

The signed string uses the **raw request body**, not the parsed JSON —
so a downstream framework MUST expose the raw body to the handler (e.g.
`express.raw({ type: 'application/json' })`, `fastify`'s
`rawBody: true`, or Next.js `route.ts` with `req.text()`).

Multiple `v1=` entries in one header are supported for secret rotation:
sign new deliveries with both the old and new secret for a
grace-period, verify with either, then retire the old secret. Unknown
scheme keys (a hypothetical `v2=` in a future SDK release) are silently
ignored, so old verifier code keeps working against newer senders.

### Server-side implementation

`signWebhookPayload` is provided for tests, mocks, and server-side
implementations that need to produce the header value:

```ts
import { signWebhookPayload } from "@ae402/sdk/webhooks";

const body = JSON.stringify(eventEnvelope);
const header = await signWebhookPayload(body, secret);
await fetch(customerUrl, {
  method: "POST",
  headers: {
    "content-type": "application/json",
    "x-ae402-signature": header,
  },
  body,
});
```

## Versioning

`@ae402/sdk` follows [Semantic Versioning](https://semver.org/):

- **Patch** — bug fixes, doc-only changes, non-behavioral refactors.
- **Minor** — new modules, new exported functions or types, new webhook
  event names appended to `WebhookEventType` (the union is declared open
  with `| (string & {})`, so downstream code compiles against unknown
  event names — treat unknown types as "keep going").
- **Major** — removed exports, renamed functions, changed signatures,
  changed HMAC scheme or header name, changed Node engine floor,
  breaking rename or removal of fields in `EscrowResponse` /
  `ReputationResponse` / `WebhookEvent`.

See [CHANGELOG.md](./CHANGELOG.md) for the release history.

## Vendoring

If you'd rather vendor the SDK into your app instead of installing from
npm, the source layout is intentionally flat and dependency-free:

1. Copy `client.ts`, `verify.ts`, `webhooks.ts`, `errors.ts`, `types.ts`
   into your repo.
2. Use the shipped `tsconfig.json` as-is (it enables
   `allowImportingTsExtensions` + `noEmit`, so `.ts` imports work
   without a build step and Node's built-in type-stripping executes it
   directly).
3. Skip the `dist/` build — Node 22+ runs `.ts` directly with
   `--experimental-strip-types`.

## Build / test

```bash
npm run typecheck   # tsc --noEmit
npm test            # node --test --experimental-strip-types
npm run build       # emit dist/ (JS + .d.ts)
```

The `prepublishOnly` hook runs typecheck + tests + build.

## Publishing

`publishConfig.access = "public"` is set. Once the maintainer has npm
credentials wired in CI (out of scope for this repo — see the AE402
release runbook), `npm publish` from `sdk-ts/` cuts a release.

**Not shipped in `0.1.0`:**

- Write path — use the Python SDK (`sdk/`), which ships the full x402 signing flow.
- Checkpoint-signature verification (`server/audit_log.py` mirror) —
  planned for `0.2.0`.
