# AgentEscrow402 — VIDEO SCRIPT
**Format:** Faceless tutorial | ~2 min | English  
**Style:** Terminal-first — show the escrow contract, then the dashboard  
**No voiceover** — subtitles + tooltips + background music

---

## HOOK OPTIONS (pick one — first 5 seconds)

**Hook A:**
[SHOW: Terminal — curl POST to /escrows creating a new escrow, deploy hash returned]  
[SUBTITLE: "AI agent sends 10,000 CSPR to another agent. Fully on-chain. No intermediary."]

**Hook B:**
[SHOW: testnet.cspr.live/contract/5dd33e8... loading — escrow contract on Casper]  
[SUBTITLE: "This escrow contract just settled $10K between two AI agents on Casper testnet."]

**Hook C:**
[SHOW: Dashboard — pending escrow ticking TTL down, then "Release" button clicked]  
[SUBTITLE: "HTTP 402 + Casper blockchain = AI-native payments with insurance."]

---

## SECTION 1 — Contract & Dashboard (0:00–0:40)

[SHOW: Terminal — contract hash constant in code, then navigate to testnet.cspr.live/contract/5dd33e8e7...]

[SUBTITLE: "Contract deployed at 5dd33e8e... — click any row to verify on-chain."]

[SHOW: Dashboard opens — header bar shows the contract hash as a clickable link]

[SHOW: Escrows tab — list of pending/released escrows. Each row has amount, sender → receiver, TTL countdown]

[SHOW: Hover over an escrow row — "On-chain" link appears at the bottom right]

[SHOW: Click "On-chain" → testnet.cspr.live/deploy/... opens with the deploy hash]

[TOOLTIP: "Every escrow is a real deploy on Casper testnet."]

[SHOW: Stats bar at the top — Total, Pending, Released, Volume]

---

## RE-HOOK at ~0:40

[SHOW: Connect Wallet button — click it — wallet connects (simulated mode)]  
[SUBTITLE: "Connect your wallet to interact with escrows in real time."]

---

## SECTION 2 — Create & Resolve Escrow (0:40–1:20)

[SHOW: Click "New Escrow" button — CreateEscrow modal opens]

[SUBTITLE: "Enter receiver public key, amount in CSPR, and TTL."]

[SHOW: Type amount → fee estimate appears live: Net: 9,800 | Fee: 200 (2.0%)]

[TOOLTIP: "2% insurance fee funds the dispute resolution pool."]

[SHOW: Submit form — success toast: "Escrow created: 7a3e9b2c..."]

[SHOW: New escrow row appears in list — status: pending]

[SHOW: Click "Release" on a pending escrow — ActionModal confirms: "This action is final"]

[SHOW: Confirm → success toast: "Escrow released successfully"]

[SHOW: Escrow status changes to green "released" badge]

[B-ROLL: Operations tab — Escrow Lifecycle visualization: Create → Pending → Release/Dispute/Refund]

---

## SECTION 3 — Agents Leaderboard & Explorer (1:20–1:55)

[SHOW: Switch to Agents tab — ranked list of AI agents with CSPR volume]

[SHOW: Click agent row → expand detail panel]

[SUBTITLE: "Every agent has an on-chain address — click 'View on Explorer'."]

[SHOW: Click "View on Explorer" → testnet.cspr.live/account/0202... opens]

[SHOW: Operations tab — "View Contract" card → click → testnet.cspr.live/contract/5dd33e8e...]

[TOOLTIP: "Insurance Pool: 2% fee on every escrow — fully transparent, on-chain."]

---

## OUTRO (1:55–2:00)

[SHOW: Escrow dashboard with live stats + Casper explorer in background]  
[SUBTITLE: "AgentEscrow402. AI-native payments, insured by code."]  
[B-ROLL: GitHub repo URL]
