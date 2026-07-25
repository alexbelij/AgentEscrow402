# How to Judge AgentEscrow402 — Casper Hackathon 2026

> A **2-minute** walkthrough for judges. If you have 20 minutes, follow
> the deep-dive links; if you have 2, the *Fast path* section is what
> you need.

## Fast path (2 minutes)

1. Open the live console: **https://ae402.xyz**
2. Click **Guided demo → Start**.
   - Step 1: create an escrow (~5 s, real testnet tx).
   - Step 2: release funds (or dispute — the demo shows both).
   - Step 3: verify the arbitration evidence Merkle root
     (client-side, no server trust).
3. Every visible transaction is a live testnet deploy — the tx hash
   links to **cspr.live** so you can inspect it yourself.

That's it. The rest of this document is depth on how each of the 8
judging criteria is satisfied.

## 8-criteria map

| # | Criterion | Where to look |
|---|-----------|---------------|
| 1 | **Casper-native architecture** | `contracts/` — Rust WASM contracts deployed to testnet: escrow, manager, insurance pool, agent identity registry. Verify hashes at `/contracts`. |
| 2 | **Working demo on testnet** | Guided demo on ae402.xyz. Each step emits a real testnet tx; hashes are visible in the UI and pinned in `docs/evidence/`. |
| 3 | **Technical correctness** | 624 tests across contract Rust (`contracts/tests/`) and server Python (`tests/`). Suites include: escrow FSM invariants, VRF election, 3-of-5 arbiter recovery, Merkle inclusion proofs, insurance replay guards, redacted audit trace. |
| 4 | **Novelty / originality** | `docs/originality-statement.md` (roadmap): agent-first escrow with LLM arbitration + on-chain Merkle evidence provenance + auto-escalation to VRF-elected panel on abstain/low-conf. See also §Originality below. |
| 5 | **Documentation quality** | `README.md`, `docs/ARCHITECTURE.md`, `docs/API_SDK_MCP.md`, `docs/SDK.md`, `docs/AUDIT_TRACE_AND_LINEAGE.md`, `docs/MERKLE_PROVENANCE.md`, `docs/FSM.md`, `docs/CSPR_UNITS.md`, `docs/OPERATOR_RUNBOOK.md`. |
| 6 | **Security posture** | `docs/RED_TEAM.tmp` (15 attack vectors self-audit); `SECURITY.md`; escrow FSM = deny-by-default; detached signatures with nonce + domain separation; insurance replay guards; supply-chain audit in `docs/BUILD_AUDIT.md`. |
| 7 | **Developer experience** | `sdk/README.md` — Python SDK, LangChain tool, and MCP server (26 tools). 2-minute quickstart at `examples/quickstart.py`. OpenAPI at `docs/openapi.yaml`. |
| 8 | **Business viability** | `docs/STATUS_AND_ROADMAP.md` — target ICP (autonomous LLM agents doing paid work for other agents/humans), revenue model, GTM. |

## One-click paths

Copy-paste these from the deploy URL bar; each opens a specific verified
surface without navigating the whole app.

- Contracts + hashes → `/contracts` (JSON) → cross-check against
  cspr.live.
- Recent arbitrations (verdict + provider + confidence + evidence_root)
  → `/arbitration/history`.
- Verify an evidence inclusion proof client-side or via API →
  `POST /arbitration/verify-evidence` (`docs/AUDIT_TRACE_AND_LINEAGE.md`).
- Operator health (deps, retries, circuit breakers) → `/ops/health`.
- 3-step guided demo contract → `POST /demo/three-step` (returns the
  demo script as JSON so a UI or a judge can replay it end-to-end).

## Real vs sim — what's on-chain, what's in-process

| Component | Status | Notes |
|-----------|--------|-------|
| Escrow lifecycle (create / release / refund / dispute / resolve) | **Real** (testnet) | Every state transition emits a deploy hash. |
| 3-of-5 arbiter recovery | **Real** (testnet) | On-chain multisig; deploy visible in evidence page. |
| VRF panel election on escalation | **Real** (testnet) | Verifiable random arbiter selection excludes dispute parties. |
| Insurance pool premium / claim | **Real** (testnet) | With replay guard tests (`tests/test_insurance_replay.py`). |
| LLM arbitration (Groq → NVIDIA NIM → OpenRouter → heuristic) | **Real** (off-chain, deterministic hash committed on-chain) | Provider fallback chain. Prompt is not persisted; `prompt_hash` + `evidence_root` are. |
| Merkle evidence root | **Real** (deterministic, on-chain committed) | Same math as RWA-Sentinel `merkleProvenance.ts`. |
| Redacted audit trace + lineage | **Real** (deterministic) | `server/audit_trace.py`. No PII / no secrets ever persisted. |
| Guided demo UI wiring | **Real** | Powered by `/demo/three-step` deterministic contract. |
| Legacy hash-based ZK proof endpoints (`/zk/verify-groth16` etc.) | **Sim** | Marked `simulation: true` in every response. Real Groth16 (BN254 via gnark) is at `/zk/groth16-real/*`. |

## Originality (2-line pitch per angle)

- **Agent-first escrow.** Not a marketplace with humans-in-the-loop; the
  buyer, seller, and arbitrator are LLM agents. The SDK/LangChain
  tool/MCP server exist because agents are the primary customer, not
  humans clicking buttons.
- **Merkle-committed evidence.** Arbitration always publishes a root
  over the evidence set it saw at decision time. Anyone — judge,
  loser, third party — can verify inclusion later without trusting the
  server, using the same tree math a JS client can run.
- **Auto-escalation to VRF panel.** When the LLM abstains or returns
  low-confidence, a verifiably random panel is elected on-chain
  (excluding the dispute parties). No hidden switch; the escalation
  rule is one function in `server/app.py`.

## Limitations we admit up front

- Legacy `/zk/verify-*` endpoints are hash-based simulations. **Real**
  BN254 Groth16 is at `/zk/groth16-real/*` (Gate 4 CP handoff — CP
  side is the primary user of ZK proofs; AE402 only consumes them for
  optional arbitration attestations).
- Live deployment currently targets **testnet**. Mainnet migration is
  a separate hardening pass (see `docs/DEPLOYMENT_LESSONS.md`).
- Some evidence pages in `docs/evidence/` predate the CSPR / motes
  unit fix (`docs/CSPR_UNITS.md`) and display legacy amounts. New
  arbitrations use the dual-unit contract (`{amount_cspr, amount_motes}`).

## Where the money would come from

- **Take rate** on escrowed volume (bps) — same shape as Stripe /
  Escrow.com, applied to agent-to-agent flows.
- **Insurance pool premium** — opt-in, priced by risk score.
- **SDK / infra** — free; the take rate is the business.

Full model, ICP, TAM/SAM/SOM: `docs/STATUS_AND_ROADMAP.md`.

## If a judge asks "how do I trust this?"

Everything the server produces is either:

- **Verifiable client-side** (Merkle inclusion proofs → the JS port
  reproduces the fold; the `/arbitration/verify-evidence` endpoint is
  a convenience, not a source of trust), or
- **Committed on-chain** (deploy hashes, contract hashes, arbiter
  signatures over the analysis_hash which folds in the evidence_root),
  or
- **Deterministic + reproducible** (audit trace events; same input →
  same event_id → same chain root, in any language with sha256).

If any of these fails a judge's spot-check, that's a security bug,
not a demo failing gracefully.

## Regulatory posture (30-second read)

AE402 is designed to be **regulator-friendly by construction**.
Full analysis in `docs/COMPLIANCE.md`.

- **EU MiCA** — out of CASP scope. The escrow contract is
  non-custodial: users retain private keys, the smart contract
  holds funds under programmatic release conditions. Recital 83
  explicitly excludes non-custodial wallet software from CASP
  authorisation. AE402 provides utility infrastructure, not a
  crypto-asset service.
- **EU AI Act** — AE402 is classified as a **high-risk AI system**
  under Annex III 8(a) (alternative dispute resolution with binding
  legal effect), per the July 2024 Commission Draft Guidelines
  that name arbitration explicitly. What we already implement
  to satisfy Art. 8-15 + 26: redacted audit trace (Art. 12),
  Merkle-committed evidence lineage (Art. 12), VRF-panel human
  escalation on abstain (Art. 14), deterministic policy layer
  before LLM call (Art. 15), CUSUM/Page-Hinkley post-market
  monitoring on decision drift (Art. 72). Full mapping in
  `docs/COMPLIANCE.md`.
- **US FinCEN (2019 guidance)** — not a money transmitter. AE402
  is a non-custodial software provider under the integral-service
  analog of Section 4.5.1(b). Value moves peer-to-peer under
  smart-contract control; we do not accept or transmit customer
  funds.
- **US SEC / CFTC** — AE402 handles service-work escrow, not
  investment contracts or derivatives. CSPR is the payment rail;
  no yield, no pooled investment, no leverage.
- **NIST AI RMF 1.0 + GenAI Profile (July 2024)** — explicit
  Govern/Map/Measure/Manage mapping in `docs/COMPLIANCE.md`
  (GV-1.1, GV-3.2, MS-2.5, MS-2.11, MG-4.1, MG-4.2).
- **GDPR** — evidence-minimisation by design: only hashes,
  decisions, provider IDs and confidence scores are audited;
  raw prompts and secrets are redacted before the trace event
  is emitted.

Honest gap-list in `docs/COMPLIANCE.md`: FRIA / DPA / Art. 30
templates, per-jurisdiction deployer runbooks, formal legal
opinion under the first commercial deployer, cross-border
transfer mechanism for upstream LLM provider.

## Contact

- Repo: https://github.com/alexbelij/AgentEscrow402
- Live: https://ae402.xyz
- SDK: `pip install -e sdk/` from a repo clone (PyPI publish pending
  Gate 5).
