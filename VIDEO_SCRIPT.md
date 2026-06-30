# Demo Walkthrough Script

Duration target: 2:00–2:30

## Setup

- Open ae402.xyz in browser (landing page visible)
- Terminal with curl ready
- Casper testnet explorer tab open

## Scene 1 — Hook (0:00–0:10)

[SHOW: landing page hero]
Narration: "What happens when AI agents need to pay each other for compute, data, or API calls? Today I'll show you how AgentEscrow402 solves this on Casper Network."

## Scene 2 — Problem (0:10–0:25)

[SHOW: terminal running a curl request that returns HTTP 402 Payment Required]
Narration: "An agent calls an API. Gets 402 — Payment Required. There's no wallet, no human, no credit card. Standard HTTP has no answer for this."

## Scene 3 — The Flow (0:25–0:45)

[SHOW: scroll landing page to architecture diagram]
Narration: "AgentEscrow402 adds an x402-compatible middleware. The sender agent locks CSPR in an on-chain escrow smart contract. The receiver agent delivers the service. Then the escrow releases automatically — or gets disputed."

## Scene 4 — Live API Demo (0:45–1:15)

[SHOW: ae402.xyz/dashboard]
Narration: "Here's the live dashboard. 50 escrow transactions. Real status — pending, released, disputed, refunded. Volume tracked in real time."

[SHOW: click Agents tab, expand an agent]
Narration: "Each agent has a reputation score. Completed escrows increase it, disputes decrease it. On-chain, transparent, auditable."

[SHOW: click Operations tab, create escrow form]
Narration: "Connect your Casper Wallet and you can create escrows, release funds, or file disputes directly from the UI."

## Scene 5 — On-Chain Proof (1:15–1:35)

[SHOW: click contract link → Casper testnet explorer]
Narration: "Everything is on Casper testnet. Here's the deployed escrow contract — stored arguments, entry points for create, release, dispute, resolve, and the insurance pool."

[SHOW: scroll to contract deploys / transactions]

## Scene 6 — SDK (1:35–1:50)

[SHOW: terminal with python code snippet]
```python
from agent_escrow import EscrowClient
client = EscrowClient(node_url="...", key="...")
tx = client.create_escrow(receiver="agent-gpt4", amount=25000, ttl=3600)
```
Narration: "Three lines. Any Python agent can create, release, or dispute escrows. LangChain tool adapter included."

## Scene 7 — Insurance & Reputation (1:50–2:05)

[SHOW: dashboard stats showing insurance pool, reputation scores]
Narration: "Every released escrow contributes 2% to the insurance pool. If an agent goes rogue, victims can claim from the pool. Reputation decays over time — you can't just farm a good score and stop."

## Scene 8 — Close (2:05–2:20)

[SHOW: landing page final section]
Narration: "AgentEscrow402 — machine-to-machine commerce, trustlessly, on Casper. Check the repo, try the dashboard, read the docs."

[SHOW: GitHub URL + ae402.xyz]
