# AgentEscrow402 — Compliance Baseline

**Status:** compliance-by-design baseline for the hackathon submission. This
document catalogues how the current architecture maps to major regulatory
regimes, what is designed-in, what is a documented gap, and what needs a
formal legal opinion before mainnet / commercial launch.

**This is not legal advice.** It is a good-faith engineering position paper
that a real counsel can pick up as a starting point.

---

## 1. Regulatory scope — what AE402 actually does

AE402 is a **non-custodial escrow and dispute-arbitration protocol** for
agent-to-agent (A2A) payments on Casper. The relevant surfaces:

| Surface | What it does | Custody? | Autonomy |
|---|---|---|---|
| Escrow smart contract | Locks CSPR / MOTES until conditions met | Contract holds funds; users hold keys | Deterministic on-chain |
| API / server | Orchestrates escrow lifecycle, exposes REST endpoints | Never signs on behalf of a user | Off-chain coordination only |
| LLM arbitration panel | Adjudicates disputes over evidence + policy | No fund control | Advisory; on-chain settlement always requires signed tx |
| VRF committee escalation | Fallback panel for abstain / low-confidence verdicts | No fund control | Verifiable randomness → panel |
| Audit trace + Merkle lineage | Redacted, verifiable evidence set for every decision | N/A | N/A |
| MCP server + LangChain tool | Read/write API surface for agent frameworks | N/A | N/A |

Key architectural facts that drive every downstream classification:

1. **Non-custodial.** The protocol never holds a user's private key. Users
   sign every transaction from their own wallet (browser wallet, hardware
   wallet, agent-owned key). The smart contract holds funds only under
   deterministic conditions the user signed for.
2. **Human-in-the-loop by default for value transfer.** No LLM output moves
   funds directly. Every settlement is a signed on-chain transaction; the
   LLM verdict is an *input* to a deterministic policy, not the trigger.
3. **Auditable arbitration.** Every arbitration decision produces a
   Merkle-rooted evidence set, redacted per policy, verifiable off-chain
   with the `/verify-evidence` endpoint (AE-8).
4. **Deny-by-default state machine.** FSM transitions in the hosted state
   API are explicitly deny-by-default (AE-14). Unknown transitions do not
   silently succeed.

---

## 2. EU — MiCA (Regulation (EU) 2023/1114)

**Deadline:** transitional regimes fully closed by 1 July 2026.

### Position

AE402 is designed to fall **outside the CASP (Crypto-Asset Service Provider)
perimeter** as a non-custodial protocol. The specific hooks:

- **Article 3 CASP definition** requires the *business* of providing
  crypto-asset services on a professional basis. AE402 is a protocol +
  reference implementation; the deployer runs the smart contract, the
  users sign transactions. The MiCA-regulated service surface (custody,
  exchange, execution of orders, transfer services) is not performed on
  behalf of clients.
- **Recital 83** explicitly states that "hardware or software providers of
  non-custodial wallets should not fall within the scope of this
  Regulation." AE402's smart contract behaves like a non-custodial wallet:
  the user retains the means of access (their signing key), and the
  protocol never has the ability to move funds without a valid signed
  transaction.
- **Article 2(3) exemption** — MiCA does not apply to crypto-asset
  services provided "in a fully decentralised manner without any
  intermediary." AE402 is not fully decentralised (the reference server
  is an intermediary for coordination and dispute UX), so this exemption
  is not the primary shield — non-custody is. Deployers who run the
  contract themselves and expose a coordination server sit outside the
  CASP definition on custody grounds, not on decentralisation grounds.

### Gaps / open questions for counsel

1. **Fee-taking coordination server.** If a deployer runs the coordination
   API commercially and charges a fee on top of the on-chain escrow, the
   commercial character of that activity is what a regulator will look at.
   Fee models that route through the smart contract (as protocol fees to a
   deployer-owned address) are cleaner than off-chain SaaS charges tied to
   custody-adjacent services. **Position:** the reference server exposes
   no custodial service, so fees for coordination alone are outside CASP.
2. **Dispute resolution as a service.** MiCA does not explicitly regulate
   arbitration. However, if a deployer markets LLM arbitration + VRF panel
   as a paid service *and* that service materially controls transfer
   outcomes, a regulator may look at Article 3(1)(19) execution of orders
   or transfer services. **Mitigation:** the LLM verdict does not execute
   the transfer; it emits a signed statement the user or beneficiary uses
   as an input to their own signed settlement transaction.
3. **Stablecoin / e-money interaction.** If future integrations settle in
   e-money tokens (EMT) or asset-referenced tokens (ART), issuer-side
   MiCA obligations apply to the *issuer*, not AE402. AE402 remains a
   downstream non-custodial rail.

### What we ship for EU deployers

- `docs/COMPLIANCE.md` — this document as evidence of good-faith mapping.
- `README.md#non-custodial-claim` — explicit non-custody statement.
- Deploy runbook flags fee configuration as a compliance-relevant knob.

---

## 3. EU — AI Act (Regulation (EU) 2024/1689)

**Deadline:** high-risk AI system obligations phase in through Aug 2026;
prohibited-practices provisions and GPAI transparency already in force.

### Position

The LLM arbitration panel is **very likely a high-risk AI system under
Annex III, point 8(a)** — "AI systems intended to be used ... in a
similar way in alternative dispute resolution." The August 2025 Draft
Guidelines expressly include arbitration in the ADR scope when the
outcome produces legal effects for the parties. An escrow settlement
enforced by a smart contract clearly has legal effect.

We accept this classification and treat AE402 as a deployer / provider of
a high-risk AI system for arbitration.

### How the design already meets Annex III / high-risk obligations

| Obligation (Art. 8-15, 26) | AE402 implementation |
|---|---|
| Risk management system (Art. 9) | `docs/STATUS_AND_ROADMAP.md` + this file; VRF panel escalation for abstain / low-confidence verdicts (AE-A1.4) is an in-loop risk control |
| Data and data governance (Art. 10) | Prompt-injection & equivocation fixture batteries (CP gate-3 test batteries used in engine); deterministic policy layer applied on top of LLM output |
| Technical documentation (Art. 11) | `docs/STATUS_AND_ROADMAP.md`, `docs/UNITS_CSPR_MOTES.md`, per-endpoint API docs |
| Record-keeping (Art. 12) | Merkle-rooted evidence set for every arbitration decision (AE-8); `/verify-evidence` endpoint |
| Transparency to deployers (Art. 13) | `HOW_TO_JUDGE.md` + judge / operator / developer surfaces (AE-A2) — every decision is inspectable |
| Human oversight (Art. 14) | LLM verdict never moves funds directly; settlement requires signed on-chain transaction. VRF panel escalation for abstain / low-confidence outputs. |
| Accuracy, robustness, cybersecurity (Art. 15) | Redacted audit trace hardening (AE-7); Ruff / Black baseline; TruffleHog secret scan in CI; deny-by-default FSM (AE-14) |
| Post-market monitoring (Art. 72) | Regime-shift detector (CUSUM / Page-Hinkley) + Beta-Binomial risk premium in `risk_api.py` — statistical monitoring of arbitration behaviour over time |
| Serious incident reporting (Art. 73) | Audit trace + Merkle lineage produce evidence for any incident post-mortem |

### Gaps / open questions for counsel

1. **CE marking + conformity assessment.** A high-risk AI system placed on
   the EU market by a provider needs conformity assessment (Annex VI, VII).
   For open-source protocols this maps awkwardly; the recital 61
   ADR-legal-effects test is the operative trigger. If a specific deployer
   commercialises the arbitration panel in the EU, they carry the
   provider / deployer split obligations. **Mitigation:** the reference
   implementation is shipped as a component under a permissive licence
   with explicit high-risk labelling in this document; the commercial
   deployer takes on the provider obligations.
2. **Fundamental Rights Impact Assessment (Art. 27).** Not applicable for
   private commercial arbitration between agents/counterparties, but
   applicable if a public-sector deployer adopts AE402. We do not
   currently ship an FRIA template; a scoped one goes into a follow-up.
3. **General-Purpose AI (GPAI) upstream.** AE402 uses an upstream LLM
   provider as a general-purpose AI model. Under Art. 53, that provider
   carries the GPAI transparency obligations. AE402 as a downstream
   deployer verifies the provider publishes the required summary and
   passes the relevant information through in `docs/`.

### What we ship for EU-AI-Act deployers

- Explicit high-risk classification statement (this section).
- Audit trace + Merkle lineage evidence set for every decision.
- Regime-shift statistical monitoring endpoints.
- Deterministic policy layer on top of LLM output (never LLM-only).

---

## 4. EU — GDPR (Regulation (EU) 2016/679)

### Position

AE402's data flows are narrow:

- **On-chain data.** Casper transactions and escrow state. Personal data
  is not intentionally written on-chain. Public-key hashes are
  pseudonymous identifiers within the meaning of Art. 4(5); they are
  personal data if combinable with off-chain identifiers.
- **Off-chain data.** Coordination API stores task metadata, evidence
  submissions, arbitration inputs/outputs. Some of this may be personal
  data (e.g., counterparty descriptions).
- **Evidence submissions.** Users control what they submit. Redaction
  patterns are applied before Merkle-rooting to prevent secret / PII
  leakage into the audit trace (AE-7).

### How the design already meets GDPR obligations

- **Data minimisation (Art. 5(1)(c)).** Redacted trace + Merkle lineage
  minimises what is retained for verifiability. The auditable object is
  a redacted evidence set, not the raw submissions.
- **Storage limitation (Art. 5(1)(e)).** Off-chain evidence retention is
  policy-driven; deployers configure retention windows.
- **Integrity and confidentiality (Art. 5(1)(f)).** Redaction patterns,
  secret-scanning CI (TruffleHog), and Merkle-rooted integrity for the
  auditable object.
- **Right of access / erasure caveat.** On-chain data is immutable;
  personal data must not be written on-chain. AE402 writes escrow amounts
  and settlement outcomes on-chain, not personal identifiers. Right to
  erasure applies to the off-chain coordination store, which is
  achievable.

### Gaps / open questions for counsel

1. **Controller / processor allocation.** The reference deployer is the
   controller for coordination-store data. A DPA template is a
   follow-up.
2. **Cross-border transfers (Chapter V).** LLM inference may cross
   borders depending on the upstream provider. Deployers pick the
   provider and carry the transfer-mechanism obligation.
3. **Records of processing (Art. 30).** Not shipped as a template yet;
   trivial to fill from this document.

---

## 5. US — FinCEN money transmitter analysis

Reference: FinCEN FIN-2019-G001 ("Application of FinCEN's Regulations to
Certain Business Models Involving Convertible Virtual Currencies", May 9,
2019).

### Position

AE402 is **not a money transmitter under 31 CFR 1010.100(ff)** when the
smart contract is used as a non-custodial escrow, because:

1. **No acceptance and transmission of value.** The protocol does not
   accept value and then transmit it. Users lock funds in a contract they
   control (via signed transaction); the contract releases funds under
   deterministic on-chain conditions. There is no intermediary that
   "accepts" value from a payer and then "transmits" it to a payee.
2. **Anonymizing software provider exemption analog.** FinCEN treats
   *software providers* as non-transmitters (Section 4.5.1(b) of the 2019
   guidance): "suppliers of tools ... that may be utilized in money
   transmission ... are engaged in trade and not money transmission."
   The AE402 codebase is such a tool. A deployer that hosts a
   coordination server without ever taking custody of user funds sits on
   the same side of this line as a non-custodial wallet vendor.
3. **Integral / total independence test.** For the FinCEN "integral
   exemption" the money-transmission cannot be the primary business.
   AE402's coordination API primarily provides dispute-resolution and
   audit-trail services; when it charges a fee, the fee is for those
   services, not for moving money. **However**, this exemption is
   narrowly construed by FinCEN and should not be relied on in isolation;
   the primary shield remains non-custody.

### Gaps / open questions for counsel

1. **State-by-state money transmitter licensing.** FinCEN classification
   is federal. Individual states run their own money-transmitter regimes
   (NYDFS, California DFPI, etc.) that may treat "control" differently.
   The safest deployment posture is one where the deployer never controls
   user funds and never sits between payer and payee — AE402's design
   supports this.
2. **Wyoming.** Wyoming's Money Transmitter Act (Title 40, Ch. 22) at
   § 40-22-104(a)(vi) explicitly exempts virtual-currency transactions:
   "Buying, selling, issuing, or taking custody of payment instruments in
   the form of virtual currency or receiving virtual currency for
   transmission ... by any means" is exempt. Deployers domiciled in
   Wyoming get an additional layer of comfort for CSPR-denominated
   activity.
3. **New York.** NYDFS BitLicense is the sharpest state-level regime and
   turns on control. Non-custodial deployment posture is the intended
   design; deployers targeting NY need a BitLicense analysis, not a
   default assumption.
4. **CFTC / SEC.** AE402 does not issue tokens. The escrow token is CSPR
   (native chain currency), not a security. Arbitration outputs are not
   securities. If a specific deployment settles in a stablecoin whose
   issuer is regulated (US-issued regulated stablecoins), the
   deployer-level analysis picks up any pass-through obligations.

### What we ship for US deployers

- Explicit non-custody claim in `README.md`.
- This document as the good-faith federal analysis.
- Deployer runbook flags state-level licensing as a per-deployment task.

---

## 6. US — NIST AI RMF 1.0 + GenAI Profile

The AI Act obligations covered above map cleanly onto the NIST AI RMF
Govern / Map / Measure / Manage functions and the July 2024 GenAI
profile. AE402's implementation:

- **Govern.** This document defines roles, incident-response posture,
  and legal/regulatory mapping. `docs/STATUS_AND_ROADMAP.md` sets the
  organizational scope.
- **Map.** Prompt-injection and equivocation fixture batteries enumerate
  known attack surfaces. Beta-Binomial risk premium quantifies uncertainty
  per arbiter.
- **Measure.** CUSUM / Page-Hinkley regime-shift detection continuously
  measures arbitration behaviour drift. Merkle-rooted evidence sets make
  every decision independently measurable.
- **Manage.** VRF panel escalation for abstain / low-confidence verdicts;
  deny-by-default FSM; redaction pipeline for trace hardening.

The GenAI profile subcategories most relevant here: GV-1.1 (legal /
regulatory), GV-3.2 (human-AI configuration), MP-5.1 (impacts), MS-2.5
(content provenance — Merkle lineage), MG-4.1 (post-deployment
monitoring — CUSUM / PH).

---

## 7. Enterprise-sales positioning

The three-line pitch to a compliance officer:

1. **Non-custodial by construction.** The protocol never holds keys or
   moves funds on behalf of users. MiCA (Recital 83), FinCEN (2019
   guidance, integral / anonymizing-software analog), and every state
   money-transmitter regime turn on custody. AE402 does not custody.
2. **High-risk AI, done right.** The LLM arbitration panel is classified
   as high-risk under EU AI Act Annex III 8(a). We treat it that way:
   redacted-trace + Merkle-lineage record-keeping, VRF-panel human
   oversight for abstain / low-confidence outputs, deterministic policy
   layer on top of LLM output, statistical drift monitoring
   (CUSUM / Page-Hinkley), and a full technical documentation pack.
3. **Audit-friendly.** Every decision produces a redacted, Merkle-rooted
   evidence set the counterparty (or a regulator) can verify with a
   single `/verify-evidence` call.

---

## 8. Gap list (short)

Explicit follow-ups that need work before a serious commercial deployment:

- [ ] FRIA (Fundamental Rights Impact Assessment) template for public-sector deployers.
- [ ] DPA (Data Processing Agreement) template for deployers.
- [ ] Article 30 GDPR records-of-processing template.
- [ ] Per-jurisdiction deployer runbook (EU / US / UK / Singapore).
- [ ] Formal legal opinion covering the primary jurisdictions of the first paying deployer.
- [ ] Cross-border-transfer mechanism selection for the upstream LLM provider (SCCs / adequacy).

---

## 9. Change log

- 2026-07-21 — v0.1 initial baseline (hackathon submission).

---

*This document is written to hand to counsel, not to replace them. If you
are commercialising AE402 in any jurisdiction, retain local counsel.*
