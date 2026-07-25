# BRANCH_HYGIENE.md — Dangling branch audit (2026-07-25)

Audit of every `origin/*` branch that isn't `main` or `tier1/pre-submission-block`. 52 remote branches classified; recommended action per bucket below.

*Owner:* Quentin. This doc is the **triage sheet** — merge / close / mark-followup / rebase. Not a merge PR itself.

## Summary

| Bucket | Count | Recommended action |
|--------|-------|-------------------|
| **MERGED** into main already | 4 | Delete remote branches (`git push origin :branch`) |
| **DEPENDABOT** (auto-generated, 1 commit each) | 13 | Batch-merge or batch-close; do NOT hand-review |
| **FEAT-CURRENT** (Tier 1 work in flight) | 3 | Kept live: #62 range-proofs, #63 governance-dao, #55 challenge-arbiter |
| **FEAT-STALE** (submission-block features, drifted far behind main) | 19 | Triage individually below |
| **TEST-STALE** (Tier 2 test suites, not yet merged) | 6 | Kept for Tier 2 execution |
| **DOCS-STALE** (Tier 1/2 doc branches) | 3 | 1 already ported (sdk-cookbook → T1.8); 2 to port under Tier 2 |
| **FIX** (bug-fix branches) | 4 | Triage individually below |

**Grand total:** 52 branches. **Recommendation:** cut to ~10 live after this pass.

---

## 1. MERGED (safe to delete remotes, 4 branches)

These branch tips are already reachable from `main` — the work is in main and the remote is just noise.

```bash
git push origin \
  :feat/ae402-strict-mode-guards \
  :feat/ae402-canonical-manifest \
  :fix/contract-test-gate \
  :fix/insurance-claim-replay
```

## 2. DEPENDABOT (13 branches, all 1 commit each)

All dependency bumps, all in the same 1-day window (2026-07-24). Two options:

**Option A — batch-merge (fast, if CI is green):**
```bash
# Repository → PRs → filter label:dependencies → tick all → Squash and merge
```

**Option B — batch-close (defer to a scheduled dep-bump window):**
```bash
# Same UI → Close (does not delete branch; dependabot re-opens on next scan)
```

Full list (as of audit):
- pip: `opentelemetry-sdk-eq-1.44.star`, `opentelemetry-api-eq-1.44.star`, `hypothesis-gte-6.161.2`, `black-gte-26.5.1`, `fastapi-eq-0.139.star`
- github_actions: `setup-python-7`, `upload-artifact-7`
- npm frontend: `vite-8.1.5`, `react-router-dom-7.18.1`, `tailwindcss-4.3.3`, `vitejs/plugin-react-6.0.3`, `lucide-react-1.25.0`
- cargo contracts: `casper-types-7.0`

## 3. FEAT-CURRENT (3 branches — keep live)

Live submission-block work; do not touch.

| Branch | PR | Rationale |
|--------|----|----------|
| `feat/ae402-governance-dao` | [#63](https://github.com/alexbelij/AgentEscrow402/pull/63) | Governance DAO (Tier 1 #11 in original roadmap) |
| `feat/ae402-range-proofs` | [#62](https://github.com/alexbelij/AgentEscrow402/pull/62) | Range Proof Registry (Tier 1 #10) |
| `feat/ae402-challenge-commit-reveal` | [#55](https://github.com/alexbelij/AgentEscrow402/pull/55) | Challenge Arbiter (Tier 1 #9) |

## 4. FEAT-STALE (19 branches, drifted ≥36 behind main)

Individual triage — each row is a discrete decision.

### High-value, port under Tier 2

| Branch | Behind | Action | Ticket |
|--------|--------|--------|--------|
| `feat/ae402-timelocked-admin-renounce` | -40 | **Rebase + PR** — timelock hardening is Tier 2 must-do | T2.4 |
| `feat/ae402-audit-trace-merkle-lineage` | -52 | **Cherry-pick core commit** — Merkle lineage is judge-value | T2.4 |
| `feat/ae402-audit-log-signing` | -52 | **Cherry-pick** — pairs with above | T2.4 |
| `feat/ae402-signed-payloads-hardening` | -52 | **Cherry-pick** — 4 commits, security-critical | T2.6 |
| `feat/ae402-rate-limit-middleware` | -52 | **Cherry-pick** — 1 commit, quick win | T2.3 |
| `feat/ae402-risk-analytics-cusum-and-beta-binomial` | -52 | **Cherry-pick** — extends ML risk | T2.9 |
| `feat/ae402-sbom-cyclonedx` | -52 | **Cherry-pick** — SBOM is supply-chain hygiene | T2.5 |
| `feat/ae402-formal-verification` | -52 | **Keep as Tier 3** — TLA+ is post-hackathon | T2.13 |
| `feat/ae402-arbiter-signing-e2e` | -52 | **Keep as Tier 2** — 2 commits, defer | T2.14 |
| `feat/ae402-gate4-judge-surfaces` | -52 | **Investigate first** — 2 commits; content overlaps with docs shipped in Tier 1 | T2.11 |
| `feat/ae402-mcp-server-security` | -52 | **Cherry-pick core commit** — MCP surface is hackathon-visible | new T2 |
| `feat/ae402-vrf-selection-e2e` | -52 | **Cherry-pick** — VRF end-to-end test complements evidence doc | new T2 |
| `feat/ae402-vc-2.0-receipts` | -36 | **Review** — already claimed as merged in some CHANGELOG entries; verify | audit |

### Lower priority / superseded

| Branch | Behind | Action |
|--------|--------|--------|
| `feat/ae402-observability-signoz` | -52 | **Close** — SigNoz is in main already (`bb6888a`) |
| `feat/ae402-two-key-account` | -52 | **Close** — merged as `f995927` |
| `feat/ae402-nctl-e2e` | -52 | **Close** — landed as `70b3399` |
| `feat/ae-cspr-motes-unit-fix` | -74 | **Close** — units fix landed as `86b483b` |
| `chore/dockerfile-cleanup` | -52 | **Close** — content is stale, dockerfile has evolved |
| `chore/ae402-ci-lint-gate-baseline` | -52 | **Close** — CI gates re-baselined in main |

## 5. TEST-STALE (6 branches — Tier 2 backlog)

Keep for Tier 2 execution; do not touch now.

| Branch | Ticket | Notes |
|--------|--------|-------|
| `test/ae402-chaos-failure-injection` | T2.1 | 3 commits, chaos smoke suite |
| `test/ae402-chaos-extended` | T2.1 | Sibling suite |
| `test/ae402-rust-fuzzing` | T2.2 | 2 commits, cargo-fuzz harness |
| `test/ae402-e2e-casper-nctl` | superseded | NCTL e2e is in main already; **close** |
| `test/ae402-testnet-markers` | keep | Pytest marker infra; **rebase** if picked up |
| `test/ae402-insurance-cooldown-replay-odra` | **T1.7 ✅** | Ported this pass; **close** |

## 6. DOCS-STALE (3 branches)

| Branch | Status |
|--------|--------|
| `docs/ae402-sdk-cookbook` | **Ported → T1.8 ✅**; safe to close |
| `docs/ae402-security-policy` | Port under T2.8 |
| `docs/ae402-compliance-baseline` | Port under T2.7 |

## 7. FIX (4 branches)

| Branch | Action |
|--------|--------|
| `fix/ae402-sbom-casper-tx-regen` | Cherry-pick as part of T2.5 (SBOM regen) |
| `fix/ae402-blake2b-256-fuzzing` | Cherry-pick as T2.10 |
| `fix/ae402-testnet-fixture-async` | Investigate; may already be superseded by later NCTL work |
| `fix/agent-batch-3` | -80 behind; **close** unless content still relevant |

---

## Post-hygiene target state

After Quentin executes this triage, expected `origin/*` roster (excluding `main`, `tier1/pre-submission-block`):

**Live (kept):** ~10 branches
- 3 FEAT-CURRENT (open PRs #55/#62/#63)
- ~5 features flagged as Tier 2 port candidates (kept until ported)
- ~2 test branches (Tier 2 chaos + fuzz)

**Gone:** ~40 branches
- 4 MERGED (deleted)
- 13 dependabot (merged or closed)
- ~8 stale features (closed, superseded by main)
- ~3 docs (2 ported, 1 closed)
- ~3 tests / fixes (ported or superseded)

Net effect: dropping from **52 → ~10** dangling branches, releasing merge-conflict pressure and making Tier 2 execution easier.

## Verify

```bash
git fetch origin --prune                                    # sync deletions
git branch -r | grep -v "HEAD\|main\|tier1" | wc -l         # target: ~10
```

---

*This audit ships as documentation — the actual `git push origin :branch` / PR merges / PR closes are Quentin's call, one branch at a time, with the CI pipeline as the safety net.*
