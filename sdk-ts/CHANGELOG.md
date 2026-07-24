# Changelog

All notable changes to `@ae402/sdk` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Version bump rules for this SDK:

- **Patch** — bug fixes, doc-only changes, additive JSDoc, non-behavioral
  refactors.
- **Minor** — new modules, new exported functions/types, new webhook
  event types added to the `WebhookEventType` string-literal union
  (declared open with `| (string & {})` so downstream code compiles
  against unknown event names — treat unknown types as "keep going").
- **Major** — removed exports, renamed functions, changed function
  signatures, changed HMAC signature scheme or header name, changed
  Node engine floor, breaking `EscrowResponse` / `ReputationResponse`
  field renames or removals.

## [Unreleased]

## [0.1.0] - 2026-07-24

### Added
- Initial publishable release under the name `@ae402/sdk`.
- **Read-only HTTP client** (`AgentEscrow402ReadClient`) with
  `getEscrow`, `getReputation`, `riskScore`, `health`. Unauthenticated,
  matches the same-name GET routes in `server/app.py`.
- **Ed25519 signature verification** (`verifyEd25519Vote`,
  `countValidVotes`, `countValidCapApprovalVotes`,
  `countValidInsuranceClaimVotes`) with the same tag-prefixed-hex
  canonical-message builders as `server/arbiter_crypto.py`
  (`buildResolveMessage`, `buildCapApprovalMessage`,
  `buildInsuranceClaimMessage`).
- **HMAC-SHA256 webhook signature verification** (`verifyWebhookSignature`)
  for `X-AE402-Signature: t=<unix-seconds>,v1=<hex>` headers, with
  constant-time comparison, configurable timestamp tolerance
  (default 300s to reject replays), rolling-secret support (multiple
  `v1=` entries per header), and forward-compatibility with unknown
  scheme keys (a future `v2=` is silently ignored today). Companion
  `signWebhookPayload` for tests and server-side implementations.
- **Error hierarchy** (`AgentEscrowError`, `APIError`, `BadRequestError`,
  `UnauthorizedError`, `ForbiddenError`, `NotFoundError`,
  `ConflictError`, `errorForStatus`) mirroring the Python SDK's mapping.
- **Types** (`TokenType`, `EscrowStatus`, `EscrowResponse`,
  `ReputationResponse`, `HealthResponse`, `WebhookEvent`,
  `WebhookEventType`) matching `sdk/agentescrow402/models.py`.
- **Barrel export** (`index.ts`) so downstream code can
  `import { verifyEd25519Vote, verifyWebhookSignature } from "@ae402/sdk"`.
  Sub-path exports (`@ae402/sdk/client`, `/verify`, `/webhooks`,
  `/types`, `/errors`) preserved for tree-shaking.
- **Publishable package layout**: `package.json` with `exports` map,
  `files: ["dist", "README.md", "CHANGELOG.md", "LICENSE"]`,
  `publishConfig.access = "public"`, `engines.node >=19`.
- **Build tooling**: `tsconfig.build.json` emits typed JS+`.d.ts` to
  `dist/` (declaration maps, source maps, rewritten import
  extensions). Existing `tsconfig.json` kept for the zero-build /
  vendorable use case (noEmit + `allowImportingTsExtensions`).
- **Tests**: 21 unit tests total — 6 for `client.ts` (fetch-mocked),
  8 for `verify.ts` (Ed25519 vectors), 15 for `webhooks.ts` (roundtrip,
  reject conditions, tolerance edge, tampering, rolling secrets,
  forward-compat).

### Not shipped in 0.1.0
- **Write path** (`createEscrow`, `release`, `refund`, `dispute`,
  `resolve`, batch ops, VRF election, streaming claim) — requires the
  full x402 signing flow. Use `sdk/python/` (see PR #25) or a future
  full TS port for write-path work.
- **Checkpoint-signature verification** mirroring `server/audit_log.py`.
  Planned for a follow-up release.
