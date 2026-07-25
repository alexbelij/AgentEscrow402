# AgentEscrow402 — pilot pitch

*One-page, spoken in ~90 seconds, read in ~2 minutes.*

## The problem

AI agents are starting to spend money — subscription fees, worker
payouts, API credits, in-game rewards. **They have no recourse when
they get scammed.** A human buyer disputes a Stripe charge; an agent
buyer eats the loss. Every serious multi-agent system silently
reinvents an escrow half-layer, badly.

## The insight

Agents don't need "faster payments." They need **the same consumer
protections a Visa cardholder has, exposed as an API call.**
Programmatic escrow. Programmatic dispute. Deterministic outcome.
Auditable receipts. All in one line of code, callable inside their
existing loop.

## The product

**AgentEscrow402** — a Casper-native escrow + dispute layer with:

- **One-line SDK:** `client.create_escrow(receiver=..., amount=...)`.
- **Dispute path:** `client.dispute(escrow_id, evidence=...)`.
- **Real LLM arbiter** (not a mock — a Groq-hosted judge over a signed
  evidence pack + FSM state).
- **On-chain escrow** in a Rust CasperLabs contract, deployed to testnet.
- **Insurance pool** for edge cases where the arbiter is wrong.
- **W.2 (this batch):** confidential-amount escrows via Pedersen
  commitments — the on-chain observer sees only a range proof, not
  the value.
- **W.3 (this batch):** cross-chain trigger — release on Casper when a
  specific event lands on Ethereum.

## Why Casper

- **Predictable gas** — an agent that pays gas needs the cost to be
  bounded; PoS + no MEV = no fee spike surprise.
- **Wasm contracts** — the Rust-based escrow FSM is real Rust, testable
  the way an engineer expects.
- **No PoW carbon story** to explain to the CFO.
- **Native multi-key accounts** — the escrow can enforce a two-of-two
  signer arrangement between agent and arbiter without a smart-wallet
  layer.

## The pilot ask

**One weekend, one existing flow of yours, wired to AgentEscrow402.**
We supply:

- $50 testnet credit (already funded on our side).
- 15-min pair-programming setup call.
- Direct Slack/DM line to the maintainer (me) for the 48h afterward.

You supply:

- One real workflow where an agent pays another agent.
- Honest feedback — what broke, what confused you, what you'd change.
- (If it works) A 3-sentence testimonial we can quote on the hackathon
  submission page.

If it doesn't work, we say so publicly.

## Contact

- Repo: <https://github.com/alexbelij/AgentEscrow402>
- Quickstart: [`QUICKSTART_5MIN.md`](./QUICKSTART_5MIN.md)
- Founder: [@quentin.tortotino@gmail.com](mailto:quentin.tortotino@gmail.com)
- Slack: `@quentin` on the Casper community Slack
