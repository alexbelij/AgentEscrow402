# AgentEscrow402 TypeScript SDK (read + verify subset)

A minimal, dependency-free TypeScript port of a subset of the Python SDK
(`sdk/client.py`, `sdk/arbiter_signing.py`): the **read-only** HTTP calls
(`getEscrow`, `getReputation`, `health`) and the **Ed25519 verification**
helpers arbiters/observers need to independently check a signed
`resolve()` vote or an audit-log checkpoint signature, without needing to
sign or submit transactions themselves.

This intentionally does **not** port the write path (`createEscrow`,
`release`, `refund`, `dispute`, `resolve`, batch ops, VRF election,
streaming claim) — those require the full x402 signing flow and stay in
the Python SDK. If a TypeScript agent needs to *write*, use the Python
SDK or a future full port; this package covers "look something up" and
"verify a signature I was handed" use cases from Node/browser code.

## Why no dependencies

Ed25519 verification uses Node's built-in `crypto.webcrypto.subtle`
(`Ed25519` is natively supported since Node 19+, confirmed on Node 24 in
this repo's environment) — no `@noble/ed25519` or `tweetnacl` needed for
this subset. HTTP calls use the global `fetch`. This keeps the SDK
zero-dependency and easy to vendor into any Node or modern-browser
project.

## Modules

- `types.ts` — `TokenType`, `EscrowStatus`, `EscrowResponse`, and friends,
  mirroring `sdk/agentescrow402/models.py`.
- `client.ts` — `AgentEscrow402ReadClient`: `getEscrow`, `getReputation`,
  `health`. Read-only, unauthenticated — matches the unauthenticated GET
  routes in `server/app.py` (no `X-Payment` / `X-402-Auth` header
  required for these endpoints).
- `verify.ts` — canonical-message builders (`buildResolveMessage`,
  `buildCapApprovalMessage`, `buildInsuranceClaimMessage`) and
  `verifyEd25519Vote` / `countValidVotes`, a byte-for-byte TypeScript
  mirror of `server/arbiter_crypto.py`'s tag-prefixed-hex Ed25519 checks.
  Also `verifySignedCheckpoint`, mirroring `server/audit_log.py`'s
  checkpoint-signature verification.

## Usage

```ts
import { AgentEscrow402ReadClient } from "./client.js";
import { verifyEd25519Vote, buildResolveMessage } from "./verify.js";

const client = new AgentEscrow402ReadClient("https://agentescrow402-api-ywm8.onrender.com");
const escrow = await client.getEscrow("deadbeef...");
console.log(escrow.status);

const ok = await verifyEd25519Vote(
  "01" + "...64-hex-pubkey...",
  "01" + "...128-hex-sig...",
  buildResolveMessage(serviceHash, inFavorOf),
);
```

## Testing

Run with Node's built-in test runner (Node 24 supports executing `.ts`
directly, no build step or ts-node needed):

```bash
node --test sdk-ts/*.test.ts
```
