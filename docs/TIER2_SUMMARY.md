# Tier 2 — Security & Audit Block

**Branch:** `tier2/security-and-audit-block`
**Ticket:** internal T2 backlog (14 items).
**Status:** 13 landed, 1 deferred as duplicate.

## Delivered

| T-id  | Item                                         | Source                                          | Commit prefix |
| ----- | -------------------------------------------- | ----------------------------------------------- | ------------- |
| T2.1  | Chaos / failure-injection suite (2 files)    | `test/ae402-chaos-failure-injection` + `-extended` | `698ed9a` + `21c219c` |
| T2.3  | Rate-limit middleware coverage               | `feat/ae402-rate-limit-middleware`              | `97d9b3b`     |
| T2.4  | Audit-log signing + Merkle lineage           | `feat/ae402-audit-log-signing` + `-audit-trace-merkle-lineage` | `3d8a36b` + `f39f69b` |
| T2.5  | SBOM CycloneDX + regeneration guard          | `feat/ae402-sbom-cyclonedx` + regen fix         | `b*` + `c7c711b` |
| T2.6  | Signed-payload envelope hardening (4 stages) | `feat/ae402-signed-payloads-hardening`          | `eab424e`…`a88d0f8` |
| T2.7  | Compliance baseline doc                      | `docs/ae402-compliance-baseline`                | `5c2cbf8`     |
| T2.8  | Security policy + threat model               | `docs/ae402-security-policy`                    | `e38da01`     |
| T2.9  | CUSUM/Page-Hinkley + Beta-Binomial risk      | `feat/ae402-risk-analytics-cusum-and-beta-binomial` | `~5c*`   |
| T2.10 | Rust proptest fuzzing + Blake2b-256 fix      | `fix/ae402-blake2b-256-fuzzing`                 | `76a5083` + `a56b45b` |
| T2.11 | Gate-4 judge/operator/developer surfaces     | `feat/ae402-gate4-judge-surfaces`               | `07fd20b` + `3a6c753` |
| T2.12 | **FlashGuard server-side activation (NEW)**  | (implemented in this PR)                        | `12ce230`     |
| T2.13 | Formal-verification FSM proptest suite       | `feat/ae402-formal-verification`                | `991c388`     |
| T2.14 | Arbiter signing end-to-end contract test     | `feat/ae402-arbiter-signing-e2e`                | `61b47bc` + `c0b2c3d` |

## Deferred

| T-id | Item                            | Reason                                                                   |
| ---- | ------------------------------- | ------------------------------------------------------------------------ |
| T2.2 | Rust `cargo fuzz` standalone    | Fully absorbed by T2.10 (`contract_fuzzing.rs` proptest harness) and T2.1 (chaos coverage of the same code paths). Standalone `cargo fuzz` corpus would duplicate the same primitives. Re-open only if AFL-style differential fuzzing is desired. |

## Test delta

- **Rust:** `contracts/tests` +2 harnesses (contract_fuzzing + fsm_property_tests), 8 + 16 = **+24 tests**
- **Python:** 1067 → 1229 baseline, **+162 tests**, 0 regressions

## Files added at top level

- `docs/COMPLIANCE.md`
- `docs/THREAT_MODEL.md`
- `docs/HOW_TO_JUDGE.md`
- `docs/OPERATOR_RUNBOOK.md`
- `docs/AUDIT_TRACE_AND_LINEAGE.md`
- `docs/SIGNED_PAYLOADS.md`
- `docs/RISK_ANALYTICS.md`
- `docs/FLASH_GUARD.md`
- `docs/MERGE_NOTES.md`
- `docs/MERGE_NOTES_FORMAL_VERIFICATION.md`
- `sbom/` (12 CycloneDX SBOMs across Python / Node / Rust contracts)
- `.github/workflows/sbom-guard.yml` (CI regen check)

## Follow-up (not in scope of this PR)

- Wire `flash_guard.enforce(...)` into the escrow release/refund
  endpoints (one line per handler; primitive shipped in T2.12).
- Rate-limit middleware endpoint enforcement (test coverage shipped;
  wire-in is a middleware toggle).
- SBOM regen CI already flags stale SBOMs — no action unless it fails.
