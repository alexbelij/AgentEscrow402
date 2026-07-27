# AE402 Demo Video — Production Script v3 (2026-07-27 update)

> **Format:** Screen recording (2× speed) + text overlays + animations + bg music
> **Duration:** 100 seconds (was 90s — added one scene for the new-features block)
> **No voiceover** — all info via fast on-screen text & tooltips
> **Style:** Dark theme matching ae402.xyz (slate-900, indigo-400, emerald-400)
> **Music:** Upbeat electronic ambient, 110-120 BPM, royalty-free
> **Rule:** NO static screens >2s. Every second has motion — cursor, scroll, transition, or animation.

Numbers below are current as of 2026-07-27 (verified against README/TX_MANIFEST/live pytest run).
Old script (deleted from repo history, last version `dbace1d`) used stale figures —
8 contracts / 62 API / 26 MCP / 13 pages / ~490 tests. Corrected throughout.

---

## COLORS & STYLE (unchanged from v2)

| Element | Value |
|---------|-------|
| Background | `#0f172a` (slate-900) |
| Accent 1 | `#818cf8` (indigo-400) |
| Accent 2 | `#34d399` (emerald-400) |
| Text | `#f8fafc` (slate-50) |
| Font | Inter / system sans, code: JetBrains Mono |
| Resolution | 1920×1080, Chrome dark, no bookmarks bar |

---

## SCENE BREAKDOWN — 100 SECONDS, NON-STOP ACTION

### 0:00–0:03 — LOGO FLASH (3s)
- Black → particles fly in → form "**AgentEscrow402**"
- Subtitle: `Trustless x402 Escrow · Casper Network`

### 0:03–0:08 — PROBLEM → SOLUTION (5s)
- Left (red tint): `Traditional: User → Bank → Middleman → Receiver` ❌❌❌
- Right (green tint): `AE402: Agent → Smart Contract → Agent` ✅✅✅
- Center punch: **"No middleman. No trust. Just code."**

### 0:08–0:18 — LANDING PAGE SPEED RUN (10s, 2× speed)
1. ae402.xyz loads
2. Fast scroll → Trust Signals bar zooms in: `10 Contracts · 369+ Txns · 140 API · 26 MCP · 19 Pages`
3. Click contract link → testnet.cspr.live opens on the **Casper HTLC bridge** contract (newest, cross-chain)
4. Scroll to "Shipped since the Tier-1 baseline" panel → quick highlight
5. Click **"Launch Console →"**

Overlay: `Every contract hash → live Casper testnet deployment`

### 0:18–0:28 — CONSOLE SPEED TOUR (10s, rapid cuts, ~0.6s/page)
Sidebar clicks across all **19** pages: Overview, Escrows, Agents, Insurance, Risk, Contracts,
Advanced, Arbitration, Identity Registry, Sandbox, Docs, Agent Demo, Marketplace, Feature Map,
Use Cases, plus the 4 newer surfaces below.

Overlay: `19 live console pages — all wired to the backend`

### 0:28–0:46 — SANDBOX LIVE DEMO (18s, 1.5× speed) — unchanged hero flow
1. Create Escrow → amount `5000`, TTL `300` → toast "Created!" → `service_hash` shown
2. Get Escrow → full detail (status: pending)
3. Release → status `released`
4. Dispute → status `disputed`
5. Batch Create → 2 escrows atomically
6. HTLC Commit/Reveal → SHA-256 secret released

Tooltips (rotate): `x402 header auto-signed · Ed25519 identity` / `On-chain deploy hash — verify on testnet.cspr.live`

### 0:46–0:58 — **NEW THIS ROUND** (12s, 2× speed) — the block the old script didn't have
Fast cuts, one per feature, each with a one-line on-screen label:

1. **Threshold Escrow** (2s): Split release secret into shares → 3-of-5 reconstruct → release
2. **ZK Amount Privacy** (2s): Create escrow with hidden amount → range-proof badge `48-bit proof ✓`
3. **Gaming-Reward Escrow** (2s): Merkle root submitted → inclusion-proof claim → payout
4. **Multi-Hop A2A** (2s): 3-agent chain visual (A→B→C) → hash-chain attestation confirmed
5. **Casper↔EVM Bridge** (2s): Split-screen — Casper HTLC leg / Sepolia leg, same hashlock
6. **Compliance Engine** (2s): Jurisdiction + KYC tier badge auto-attached to a new escrow

Overlay: `6 new capabilities shipped this round — all live, not roadmap`

### 0:58–1:08 — AI ARBITRATION + VRF + IDENTITY + MARKETPLACE (10s, 2× speed)
1. Arbitration (3s): AI verdict + confidence + evidence
2. VRF Election (2.5s): Elect → arbiter selected → on-chain proof
3. Identity Registry (2s): Agent detail, reputation, capabilities
4. Agent Marketplace (2.5s): Browse listed agents → pricing/reputation cards

### 1:08–1:18 — INSURANCE + MULTI-ASSET + RISK (10s, 2× speed)
Same as v2 — Insurance pool deposit, CEP-18/CEP-78 escrow, IsolationForest risk chart.

### 1:18–1:30 — SDK / MCP / API DOCS (12s, 2× speed)
1. REST API tab: expand "Core Escrow" group, show request/response
2. Python SDK: `EscrowClient.generate(...)` snippet + LangChain integration
3. MCP tab: **26 tools** table, Claude Desktop config JSON

Overlay: `140 API endpoints · Python + JS/TS SDKs · 26 MCP tools`

### 1:30–1:40 — CLOSING CTA (10s)
1. Logo `AgentEscrow402`
2. Tagline `Trustless x402 Escrow for AI-to-AI Payments`
3. Stats fly in: `10 Contracts` → `140 API` → `26 MCP` → `2,335 Tests` → `369+ Testnet Txns` → `Open Source`
4. CTA buttons: `[▶ ae402.xyz]  [⭐ GitHub]`
5. Bottom: `Casper Agentic Buildathon 2026 · MIT License`

---

## PACING RULES (unchanged) — no static screen >2s, always 1.5–2× recording speed, hard cuts, beat-synced.

## TOOLTIP LIBRARY (add to v2's list)

| Context | Text |
|---------|------|
| Threshold escrow | `Shamir MPC — no single party holds the key` |
| ZK privacy | `Amount hidden · range-proof verifiable` |
| Gaming escrow | `Merkle-proof payouts · O(log N) claims` |
| Multi-hop | `Verifiable hash-chain across N agent hops` |
| Bridge | `Same hashlock, both chains — atomic or nothing` |
| Compliance | `Jurisdiction + KYC tier, inline on creation` |

## 45-SECOND EMERGENCY CUT (update numbers only, same shape as v2)

| Time | Content | Speed |
|------|---------|-------|
| 0:00–0:02 | Logo + tagline | 1× |
| 0:02–0:06 | Landing: trust signals (`10/369+/140/26/19`) + testnet link | 2× |
| 0:06–0:10 | Console: rapid 19-page sidebar tour | 3× |
| 0:10–0:22 | Sandbox: Create → Get → Release → Dispute (hero) | 1.5× |
| 0:22–0:30 | New-this-round montage (threshold/ZK/gaming/bridge, pick 2) | 2× |
| 0:30–0:36 | Arbitration AI + VRF + Identity (montage) | 2× |
| 0:36–0:40 | Docs: API → SDK → MCP (3 tab switches) | 2× |
| 0:40–0:45 | CTA: ae402.xyz + GitHub | 1× |
