# Post-Hackathon Roadmap

> **Timeline:** submission → v1.0 → v1.1. Aims to answer the judge
> question "what happens after the hackathon deadline?" with a
> concrete plan grounded in the current inventory (see
> `AE402_OPEN_TASKS_INVENTORY.md`).
>
> **Status of this document.** Directional. Item ordering may shift
> as pilot feedback lands, but every phase gate has a fixed exit
> criterion — no phase closes on vibes.

---

## Phase 0 — Submission Freeze (T-0)

**Duration:** 48 hours before deadline.
**Exit criterion:** hackathon submission goes live.

Only actions in this phase:

- Video, presentation, README polish (`AE402_OPEN_TASKS_INVENTORY.md` §Submission).
- Repo cleanup (delete stale branches, prune experimental docs).
- Final judge-facing links: `make judge-lite`, `make judge-demo`, `docs/JUDGE_QUICKSTART.md`.
- Freeze `main`; open PRs get tagged `post-submission` and land in Phase 1.

**Explicitly NOT in scope:** new features, breaking changes, external announcements.

---

## Phase 1 — Fast Follow (T+0 → T+2 weeks)

**Goal:** ship every "shipped source but not fully wired" item still
open at submission. No new surface area.

**Exit criterion:** every `S1/S2/S4/S8/S11/S12` inventory item in the
"on-chain closure" cluster is either merged to `main` or explicitly
deferred with a written rationale.

Priority order:

1. **On-chain redeploy after tag alignment** (D1, D6). Regenerate manifest, update contract-hash env vars, re-verify `make judge-demo`.
2. **Unit unification wave 2** (U1, U2, U6). One breaking change window, `sdk/migrate_units.py` helper shipped ahead. See `feat/unit-consistency-w2` planning notes when the branch lands.
3. **On-chain preflight CI gate** (D1 partial). `scripts/onchain_preflight.py` → CI workflow `onchain-preflight.yml` blocks a merge if any contract-touching file lacks a matching audit note.
4. **Dependabot review sweep** (15 open PRs, backlog). Review each, merge or close with a note; nothing sits open indefinitely.

Non-goals in this phase: new integrations, new agent capabilities,
external launch.

---

## Phase 2 — Pilot (T+2 → T+8 weeks)

**Goal:** onboard 3 real pilot integrators. Learn what breaks first
in the wild, fix that. Nothing else.

**Exit criterion:** 3 pilots have executed at least 10 escrows each
through the deployed backend, and at least one pilot has hit an edge
case we didn't anticipate at submission (and we fixed it).

Work streams:

- **Integration guide + code samples** (`docs/INTEGRATION_GUIDE.md`, `docs/DISTRIBUTION.md`). Cover LangGraph, MCP-native, CrewAI wiring in narrated examples.
- **Public MCP endpoint** for the sandbox backend (behind a rate-limit + demo funds cap). Judges/pilots hit a single URL and start exploring.
- **Observability escalation:** existing Grafana dashboard is per-instance. Add PagerDuty/Discord alert wiring for pilot deployments; ship a `docker-compose.observability.yml` bundle (Prometheus + Grafana + Loki).
- **Support SLA:** issues raised by pilots ≤ 24h first response.

Non-goals: mainnet redeploy, breaking API changes.

---

## Phase 3 — Hardening (T+8 → T+16 weeks)

**Goal:** upgrade the trust posture from "hackathon prototype" to
"production-grade for the pilot cohort".

**Exit criterion:** a third-party auditor firm has completed a
written review of the on-chain contracts + agent-facing API and the
outstanding findings are either resolved or documented as accepted
risk.

Work streams:

- **Third-party contract audit** (Odra WASM + Solidity HTLC + arbiter contracts). Budget line item; solicit 3 bids.
- **Formal threat-model refresh** (`docs/THREAT_MODEL.md`). Add pilot-lifecycle threats not present in the hackathon scope: key-loss recovery, arbiter compromise, adversarial buyer→seller reputation gaming.
- **Property-based tests wave 2.** Extend Hypothesis coverage to arbiter-quorum voting, cross-chain HTLC unhappy paths, insurance-pool solvency invariants.
- **Rate limiting + abuse detection** on the public MCP endpoint. Backfill risk-score signals from real traffic once the corpus is meaningful.
- **Real-time replay of production traffic in a staging environment** for regression baseline before every deploy.

Non-goals: mainnet launch on Ethereum (we bridge only, we don't run the L1). Full sound-cryptography formal proofs (out of budget).

---

## Phase 4 — v1.0 Launch (T+16 → T+24 weeks)

**Goal:** publicly-usable, versioned SDK + backend + contract set.

**Exit criterion:** v1.0 tag on the repo, blog post published,
public MCP endpoint moved from `sandbox.` to `api.` subdomain, three
paying pilots (i.e. running commercial workloads through us, not
just kicking tyres).

Work streams:

- **Versioning contract:** SemVer for `sdk/`, backend API, and Casper contract hashes. `CHANGELOG.md` becomes canonical.
- **Public docs site** (docs.ae402.io or similar). Auto-published from `docs/` on tag.
- **Distribution:** `pip install agent-escrow-402`, MCP tool listing in the Anthropic MCP registry, `docs/DISTRIBUTION.md` up to date with real numbers.
- **Regulatory footprint:** legal review of custodial vs non-custodial claims; ToS + privacy policy for the hosted endpoint.

---

## Phase 5 — v1.1 (T+24 weeks → open)

**Goal:** the next set of ambitious features (RWA extensions,
cross-chain beyond Sepolia, multi-asset intent routing, agent-to-agent
reputation graph).

Scoped on demand from Phase-4 traction, not pre-committed here.

---

## Non-goals across all phases

- **Any custodial handling of user funds.** AE402 is a coordination
  protocol; funds live in contract purses only.
- **Building yet-another LLM.** We integrate arbitration assist,
  we don't train models.
- **Consumer-facing UI beyond a judge demo + operator dashboard.**
  We're an infrastructure product; the UI is the SDK and the MCP
  surface.

---

## Related

- `docs/INTEGRATION_GUIDE.md` — how to build an agent on top of AE402.
- `docs/DISTRIBUTION.md` — how AE402 gets to integrators (packaging,
  registries, endpoints).
- `docs/THREAT_MODEL.md` — canonical threat model (updated per phase).
- `docs/OBSERVABILITY.md` — the operator's view once deployed.
- `docs/JUDGE_QUICKSTART.md` — the 60-second reproducibility path
  (unchanged across phases).
