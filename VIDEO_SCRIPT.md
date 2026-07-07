# AE402 Demo Video — Production Script

> **Format:** Screen recording (2× speed) + text overlays + animations + bg music
> **Duration:** 90 seconds (hard cap)
> **No voiceover** — all info via fast on-screen text & tooltips
> **Style:** Dark theme matching ae402.xyz (slate-900, emerald-400, indigo-400)
> **Music:** Upbeat electronic ambient, 110-120 BPM, royalty-free
> **Rule:** NO static screens >2s. Every second has motion — cursor, scroll, transition, or animation.

---

## COLORS & STYLE

| Element | Value |
|---------|-------|
| Background | `#0f172a` (slate-900) |
| Accent 1 | `#818cf8` (indigo-400) |
| Accent 2 | `#34d399` (emerald-400) |
| Text | `#f8fafc` (slate-50) |
| Overlay bg | `rgba(15,23,42,0.85)` blur |
| Font | Inter / system sans |
| Code font | JetBrains Mono |
| Resolution | 1920×1080, Chrome dark, no bookmarks bar |

---

## SCENE BREAKDOWN — 90 SECONDS, NON-STOP ACTION

### 0:00–0:03 — LOGO FLASH (3s)

- Black → particles fly in → form "**AgentEscrow402**"
- Subtitle fades in: `Trustless x402 Escrow · Casper Network`
- **Immediate cut** to next scene on beat drop

---

### 0:03–0:08 — PROBLEM → SOLUTION (5s, split-screen animation)

- Left panel slides in (red tint): `Traditional: User → Bank → Middleman → Receiver` with ❌❌❌
- Right panel slides in (green tint): `AE402: Agent → Smart Contract → Agent` with ✅✅✅
- Center text punches in: **"No middleman. No trust. Just code."**
- **Hard cut** to landing page

---

### 0:08–0:18 — LANDING PAGE SPEED RUN (10s, real screen recording 2× speed)

**Actions at 2× speed:**
1. ae402.xyz loads (1s)
2. Fast scroll → Trust Signals bar zooms in: `8 Contracts · 142+ Txns · 62 API · 26 MCP · 13 Pages`
3. Click contract link → testnet.cspr.live opens showing real deployed contract (1.5s)
4. Back → scroll to feature comparison table (1s)
5. Click **"Launch Console →"** button

**Overlay tooltip (bottom-right, stays 2s):**
```
Every contract hash → live Casper testnet deployment
```

---

### 0:18–0:28 — CONSOLE SPEED TOUR (10s, 2× speed, rapid cuts)

**Rapid-fire sidebar clicks, ~0.8s per page:**
1. Overview — dashboard stats animate in
2. Escrows — table with statuses
3. Agents — reputation scores
4. Insurance — pool balance
5. Risk — anomaly chart
6. Contracts — 8 contracts grid
7. Advanced — multi-asset tabs
8. Arbitration — AI analysis
9. Identity Registry — DID list
10. Sandbox — endpoint cards
11. Docs — API reference
12. Agent Demo — autonomous flow

**Overlay (center, large):**
```
13 live console pages — all wired to the backend
```

---

### 0:28–0:48 — SANDBOX LIVE DEMO (20s, 1.5× speed)

**This is the hero section. Show real functionality.**

**Recording at 1.5× speed (responses are instant in sandbox):**

1. **① Create Escrow** (5s): Click card → fill amount `5000`, TTL `300` → Submit → green toast "Created!" → show `service_hash` in response
2. **② Get Escrow** (3s): Paste hash → Submit → shows full escrow detail (sender, receiver, amount, status: pending)
3. **③a Release** (3s): Click → Submit → toast "Released!" → status changes to `released`
4. **③b Dispute** (3s): New escrow → click Dispute → reason hash → Submit → status `disputed`
5. **Batch Create** (3s): Show 2 escrows created atomically
6. **HTLC Commit** (3s): SHA-256 secret → Commit → Reveal → released

**Tooltip flashes (rotate every 3s):**
- `x402 header auto-signed · Ed25519 identity`
- `On-chain deploy hash · Verify on testnet.cspr.live`
- `Shared hash flows — one hash connects the full lifecycle`

---

### 0:48–0:58 — AI ARBITRATION + VRF + IDENTITY (10s, 2× speed)

**Fast cuts between 3 features:**

1. **Arbitration** (3.5s): Submit dispute → AI analysis returns verdict + confidence score + evidence breakdown
2. **VRF Election** (3s): Click "Elect" → random arbiter selected → on-chain proof hash shown
3. **Identity Registry** (3.5s): Agent detail view → reputation score, capabilities list, "Add Capability" button click

**Overlay text (cycles):**
- `AI-powered dispute resolution`
- `VRF-elected arbiters · 3-of-5 quorum`
- `DID agent identity · Staking · Slashing`

---

### 0:58–1:08 — INSURANCE + MULTI-ASSET + RISK (10s, 2× speed)

1. **Insurance** (3s): Pool stats → click Deposit → modal → submit (fast)
2. **Multi-Asset** (4s): Advanced tab → create CEP-18 escrow → release → show NFT support
3. **Risk Dashboard** (3s): Anomaly scores chart, per-agent risk bars

**Overlay:**
```
Not just CSPR — escrow any token (CEP-18 / CEP-78)
Insurance pool · IsolationForest risk scoring
```

---

### 1:08–1:20 — SDK / MCP / API DOCS (12s, 2× speed)

**Three tabs, fast switches:**

1. **REST API tab** (4s): Scroll through endpoint groups → expand "Core Escrow" → show request/response JSON → method badges (GET/POST)

2. **Python SDK tab** (4s): Show code example (highlight):
```python
async with EscrowClient.generate(url) as client:
    escrow = await client.create_escrow(
        receiver="ab"*32, amount=5000, ttl=300
    )
```
→ Scroll to LangChain integration code

3. **MCP tab** (4s): Show 26 tools table → Claude Desktop config JSON → AI agent dialog example

**Overlay:**
```
62 API endpoints · Python SDK · 26 MCP tools for any LLM
```

---

### 1:20–1:30 — CLOSING CTA (10s)

**Screen:** Fade to dark bg, centered content

**Animation sequence (stagger 0.3s each):**
1. Logo: `AgentEscrow402` (large, white)
2. Tagline: `Trustless x402 Escrow for AI-to-AI Payments`
3. Stats fly in one by one: `8 Contracts` → `62 API` → `26 MCP` → `490 Tests` → `Open Source`
4. Two CTA buttons pulse in:

```
[▶ ae402.xyz]    [⭐ GitHub]
```

5. Bottom: `Casper Agentic Buildathon 2026 · MIT License`

**Music:** Final beat → fade out

---

## PACING RULES

| Rule | Why |
|------|-----|
| **No screen stays static >2 seconds** | Dead air kills retention |
| **Screen recording always 1.5–2× speed** | Real-time API waits are boring |
| **Text overlays appear on action, not before** | Context, not pre-reading |
| **Every tooltip ≤8 words** | Must be scannable at speed |
| **Transitions = hard cuts or 150ms fades** | No slow dissolves |
| **Cursor always moving** | Creates visual momentum |
| **Beat-synced scene changes** | Music drives the rhythm |

---

## TOOLTIP LIBRARY (short, punchy)

| Context | Text |
|---------|------|
| Deploy hash appears | `✅ Live on Casper testnet` |
| x402 header | `Ed25519 signed · No middleman` |
| Contract click | `Real WASM contract on-chain` |
| Sandbox submit | `Demo identity · Real SDK uses Ed25519` |
| Insurance | `2% fee · Pool-backed guarantees` |
| Risk score | `IsolationForest anomaly detection` |
| MCP | `Any LLM can manage escrows` |
| Batch | `Up to 50 escrows in one deploy` |
| HTLC | `SHA-256 atomic swap` |

---

## TECHNICAL SPECS

- **Resolution:** 1920×1080 (16:9)
- **Recording speed:** 1.5× for demos, 2× for navigation, 1× for CTA
- **Browser:** Chrome, dark mode, URL bar visible (proves live site)
- **Cursor:** Visible + 20px emerald highlight circle on click
- **Text:** Slide up 150ms ease-out, stay 2-3s, fade 100ms
- **Transitions:** Hard cut or 150ms crossfade
- **Music:** Electronic ambient, 110-120 BPM, no vocals, -10dB
- **Counter animations:** Count-up (0→N) over 0.5s

---

## 45-SECOND EMERGENCY CUT

If even 90s is too long:

| Time | Content | Speed |
|------|---------|-------|
| 0:00–0:02 | Logo + tagline | 1× |
| 0:02–0:06 | Landing page: trust signals + testnet link click | 2× |
| 0:06–0:10 | Console: rapid 13-page sidebar tour | 3× |
| 0:10–0:25 | Sandbox: Create → Get → Release → Dispute (hero) | 1.5× |
| 0:25–0:32 | Arbitration AI + VRF + Identity (montage) | 2× |
| 0:32–0:38 | Docs: API → SDK → MCP (3 tab switches) | 2× |
| 0:38–0:42 | Contracts → testnet link proof | 2× |
| 0:42–0:45 | CTA: ae402.xyz + GitHub | 1× |
