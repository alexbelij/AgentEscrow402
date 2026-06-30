# AE402 Video Script — x402 Trustless Escrow

## HOOK OPTIONS (pick one)
**Hook A**: [SHOW: terminal window, curl command firing] "What if a payment protocol had no middleman — at all?"
**Hook B**: [SHOW: dashboard, escrow counter ticking up] "Every escrow here is enforced by code, not trust."
**Hook C**: [SHOW: two wallets, money moving] "x402 makes HTTP payments programmable. AE402 makes them trustless."

## SCRIPT (120 seconds)

[0:00-0:05] HOOK
[SHOW: dashboard loading, stats animating]
[NARRATION]: "This is AE402 — trustless escrow for x402 payments on Casper."

[0:05-0:20] PROBLEM
[SHOW: traditional payment flow diagram]
[NARRATION]: "x402 is brilliant. But who enforces the escrow? Right now — a centralized server. AE402 removes that assumption."

[0:20-0:50] DEMO — ESCROW CREATION
[SHOW: dashboard → Escrows tab → create escrow form]
[NARRATION]: "Open the dashboard. Hit Escrows. We deploy a smart contract directly to Casper testnet."
[SHOW: Casper explorer link appearing, clickable]
[NARRATION]: "The deploy hash is live. Click it — you're looking at the actual on-chain transaction."

[0:50-1:10] RE-HOOK
[SHOW: agent list, CSPR balances]
[NARRATION]: "No intermediary holds the funds. The contract does. And every agent's balance is verifiable on-chain."

[1:10-1:40] DEMO — PAYMENT FLOW
[SHOW: Operations tab, signing transaction]
[NARRATION]: "When conditions are met, funds release. Cryptographically signed on Casper — immutable, auditable, trustless."

[1:40-2:00] CTA
[SHOW: landing page, GitHub link]
[NARRATION]: "AE402 is open source. Built on Casper. Try the live demo at ae402.xyz."
[B-ROLL: terminal with deploy command, explorer confirmation]

---

## VISUAL NOTES
- **Terminal-first**: Open with terminal commands, not just GUI clicks
- **Explorer links**: Highlight clickable on-chain links (testnet.cspr.live)
- **Wallet connection**: Show connect wallet flow early
- **No voice-over**: Subtitles + on-screen tooltips + background music
- **2 minutes max**: Tight pacing, no filler

## HOOK RECOMMENDATION
Use **Hook A** (terminal) for technical judges. Developers expect CLI/API-first demos. Start with `curl` or `casper-client` before showing the UI.

## KEY MESSAGES
1. **Trustless**: No centralized escrow holder
2. **On-chain**: Every transaction verifiable via Casper explorer
3. **x402-native**: Built specifically for HTTP 402 payment flows
4. **Open source**: Code at github.com/alexbelij/AE402
