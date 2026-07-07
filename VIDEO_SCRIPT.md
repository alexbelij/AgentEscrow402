# AE402 Demo Video — Production Script

> **Format:** Screen recording + text overlays + animations + background music
> **Duration:** 2:30–3:00
> **No voiceover** — all info via on-screen text, tooltips, and C2A banners
> **Style:** Dark theme matching ae402.xyz (slate-900 bg, emerald-400/indigo-400 accents)
> **Music:** Neutral electronic ambient (royalty-free, e.g. "Synthwave Chill" or "Digital Horizons")

---

## COLOR PALETTE & STYLE

| Element | Color |
|---------|-------|
| Background | `#0f172a` (slate-900) |
| Primary accent | `#818cf8` (indigo-400) |
| Success/CTA | `#34d399` (emerald-400) |
| Text | `#f8fafc` (slate-50) |
| Subtitle bg | `rgba(15,23,42,0.85)` with blur |
| Border glow | `#6366f1` (indigo-500) pulse |

**Font:** Inter or system sans-serif, same as site.
**Transitions:** Smooth fade (300ms) between sections. No hard cuts.
**Cursor:** Visible with subtle highlight circle on click.

---

## SCENE-BY-SCENE BREAKDOWN

### SCENE 1 — COLD OPEN (0:00–0:08)

**Screen:** Black → fade in animated particle canvas (same as ae402.xyz hero)

**Text overlay (center, large):**
```
AgentEscrow402
```
**Subtitle (fade in 0.5s after):**
```
Trustless x402 Escrow on Casper Network
```
**Bottom banner (emerald, pulse):**
```
▶ Live Demo — ae402.xyz
```

**Animation:** Particles coalesce into the AE402 logo shape, then explode outward as we transition to next scene.

---

### SCENE 2 — THE PROBLEM (0:08–0:18)

**Screen:** Split view — left side shows traditional payment flow diagram, right side shows x402 flow

**Left side (red-tinted):**
```
Traditional: User → Bank → Middleman → Receiver
             ❌ Trust required  ❌ Fees  ❌ Slow
```

**Right side (emerald-tinted):**
```
AE402: Agent → Smart Contract → Agent
       ✅ Trustless  ✅ On-chain  ✅ Instant
```

**Tooltip (bottom):**
```
x402 makes HTTP payments programmable.
AE402 makes them trustless — no facilitator holds your funds.
```

---

### SCENE 3 — LANDING PAGE TOUR (0:18–0:35)

**Screen:** Navigate to `ae402.xyz` — show landing page loading

**Actions (screen recording):**
1. Scroll down slowly — show Trust Signals bar:
   - `8 Deployed Contracts` · `142+ On-Chain Txns` · `62 API Endpoints` · `26 MCP Tools` · `13 Console Pages`
2. Pause on contract evidence links — click one → opens testnet.cspr.live showing real deployed contract
3. Show feature comparison table (AE402 vs Coinbase x402 vs Manual)

**Tooltip overlay:**
```
Every contract hash links to a live Casper testnet deployment
```

---

### SCENE 4 — CONSOLE OVERVIEW (0:35–0:55)

**Screen:** Click "Launch Console" → navigate to `/console/overview`

**Actions:**
1. Show Overview dashboard — live stats, escrow activity chart, recent transactions
2. Quick-click through sidebar navigation to show all 13 pages exist and load:
   - Overview → Escrows → Agents → Insurance → Risk → Contracts → Advanced → Arbitration → Identity Registry → Sandbox → Agent Demo → Use Cases → Docs

**Annotation arrow on sidebar:**
```
13 fully-wired console pages
```

---

### SCENE 5 — ESCROW LIFECYCLE DEMO (0:55–1:25)

**Screen:** `/console/sandbox` — Sandbox tab

**Text banner (top):**
```
🔴 LIVE DEMO — Creating a Real Escrow
```

**Actions (screen recording):**
1. Show the Sandbox info banner explaining shared hashes
2. Click ① **Create Escrow** → fill form → Submit
3. Show response: `service_hash`, `deploy_hash`, status `pending`
4. Click ② **Get Escrow** → paste hash → shows escrow details
5. Click ③a **Release** → submit → shows `released` status + deploy hash
6. Scroll to HTLC section — show ⑤ Commit / ⑥ Reveal flow

**Tooltip (during create):**
```
x402 payment header is auto-generated — Ed25519 signed, bound to this request
```

**Tooltip (during release):**
```
On-chain deploy submitted to Casper testnet — verifiable at testnet.cspr.live
```

---

### SCENE 6 — DISPUTE & AI ARBITRATION (1:25–1:45)

**Screen:** `/console/arbitration`

**Actions:**
1. Show Arbitration tab — submit a dispute for AI analysis
2. Show AI analysis response: evidence scoring, verdict recommendation
3. Switch to "VRF Election" tab — show verifiable random arbiter election
4. Switch to "Register Arbiter" tab — show arbiter registration form

**Text overlay:**
```
AI-Assisted Dispute Resolution
VRF-elected arbiters · 3-of-5 quorum · On-chain verified
```

---

### SCENE 7 — MULTI-ASSET & INSURANCE (1:45–2:00)

**Screen:** `/console/advanced` → Multi-Asset tab

**Actions:**
1. Show Multi-Asset Lifecycle tab — CSPR, CEP-18 tokens, CEP-78 NFTs
2. Switch to Insurance tab — show pool stats, deposit flow
3. Show Risk tab — IsolationForest anomaly scores per agent

**Tooltip:**
```
Not just CSPR — escrow any Casper token standard
```

---

### SCENE 8 — AGENT IDENTITY (2:00–2:10)

**Screen:** `/console/identity-registry`

**Actions:**
1. Show registered agents with DID, reputation scores, capabilities
2. Click agent detail → show capability list, reputation history
3. Show "Add Capability" button

**Text overlay:**
```
DID-Style Agent Identity · Staking · Slashing · Reputation Decay
```

---

### SCENE 9 — SDK / MCP / API DOCS (2:10–2:30)

**Screen:** `/console/docs`

**Actions:**
1. Show REST API tab — scroll through endpoint groups, expand one to show request/response examples
2. Switch to SDK tab — show Python code examples, LangChain integration
3. Switch to MCP tab — show 26 tools, Claude Desktop config, AI agent dialog example

**Text overlay (SDK tab):**
```python
async with EscrowClient.generate("https://ae402.xyz/backend") as client:
    escrow = await client.create_escrow(receiver="ab"*32, amount=5000, ttl=300)
```

**Tooltip (MCP tab):**
```
26 MCP tools — plug into Claude, GPT, Cursor, or any MCP-compatible LLM
```

---

### SCENE 10 — CONTRACTS ON-CHAIN PROOF (2:30–2:40)

**Screen:** `/console/contracts`

**Actions:**
1. Show all 8 deployed contracts with hashes
2. Click "View on Testnet" for Core Escrow → browser opens testnet.cspr.live showing the contract
3. Quick montage: click 2-3 more contract links to prove they're all real

**Text overlay:**
```
8 Smart Contracts · All deployed on Casper Testnet · All verifiable
```

---

### SCENE 11 — CLOSING CTA (2:40–3:00)

**Screen:** Fade to dark background with centered content

**Large text (fade in):**
```
AgentEscrow402
```

**Subtitle:**
```
Trustless x402 Escrow for AI-to-AI Payments on Casper Network
```

**Stats bar (animate in one by one):**
```
8 Contracts · 62 API Endpoints · 26 MCP Tools · 490 Tests · Open Source
```

**CTA buttons (pulse animation):**
```
[▶ Try Live Demo — ae402.xyz]    [⭐ GitHub — alexbelij/AgentEscrow402]
```

**Bottom text (small):**
```
Built for Casper Agentic Buildathon 2026 · MIT License
```

**Music:** Fade out over last 3 seconds

---

## TEXT OVERLAYS & TOOLTIPS LIBRARY

Use these throughout as contextual annotations:

| Trigger | Tooltip Text |
|---------|-------------|
| Any deploy hash appears | `✅ Real on-chain transaction — click to verify on testnet.cspr.live` |
| x402 header shown | `Ed25519-signed payment intent · No middleman · No trust required` |
| Contract hash shown | `Deployed WASM contract on Casper testnet` |
| Sandbox submit | `Demo identity auto-signs — real SDK uses Ed25519 private key` |
| Insurance pool | `2% fee · Automated claim processing · Pool-backed guarantees` |
| Risk score | `IsolationForest anomaly detection · Per-agent risk profiling` |
| MCP tools | `Model Context Protocol — any LLM can manage escrows autonomously` |

---

## TECHNICAL NOTES FOR VIDEO GENERATION

### Screen Recording Setup
- **Resolution:** 1920×1080 (16:9)
- **Browser:** Chrome, dark mode, no bookmarks bar
- **URL bar:** Visible (shows ae402.xyz — proves it's live)
- **DevTools:** Hidden (clean view)
- **Zoom:** 100% browser zoom

### Animation Specs
- **Section transitions:** 300ms crossfade with slight zoom (1.0→1.02→1.0)
- **Text overlays:** Slide up from bottom, 200ms ease-out
- **Tooltips:** Fade in 150ms, stay 3s, fade out 150ms
- **Stats counters:** Count-up animation (0→142 over 1s)
- **CTA buttons:** Gentle pulse (scale 1.0↔1.03, 2s cycle)
- **Cursor highlight:** 20px emerald circle, 30% opacity, follows cursor

### Music
- Genre: Ambient electronic / lo-fi synth
- BPM: 80-100
- No vocals
- Volume: -12dB (subtle background)
- Fade in: 0:00–0:03
- Fade out: last 3 seconds

### Text Style
- **Headers:** 48px Inter Bold, white, text-shadow `0 2px 8px rgba(0,0,0,0.5)`
- **Subtitles:** 24px Inter Regular, slate-300
- **Tooltips:** 16px Inter, emerald-400 text on slate-800/85 bg, rounded-lg, border emerald-500/30
- **Code blocks:** 16px JetBrains Mono, indigo-300 on slate-900, rounded-md

---

## ALTERNATIVE: 60-SECOND CUT

If time is tight, use this compressed version:

| Time | Content |
|------|---------|
| 0:00–0:05 | Logo + tagline |
| 0:05–0:10 | Landing page scroll (trust signals) |
| 0:10–0:25 | Sandbox: Create → Get → Release escrow (fast) |
| 0:25–0:35 | Arbitration + Insurance + Identity (quick montage) |
| 0:35–0:45 | Docs page: API → SDK → MCP (3 tabs) |
| 0:45–0:55 | Contracts page → click testnet link |
| 0:55–1:00 | CTA: ae402.xyz + GitHub |
