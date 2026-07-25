# 5-minute quickstart — pilot integration

**Goal:** an external agent-dev sees a working end-to-end escrow flow
in under 5 minutes. Zero fluff. No wallet UX. No CasperLabs docs to
read.

## Prereqs

- Python 3.10+ (or Node 18+ if you use the TypeScript SDK).
- 5 minutes.

## 1. Install (30s)

```bash
pip install agentescrow402-sdk  # not published yet — pilot users pip install git+https://github.com/alexbelij/AgentEscrow402.git#subdirectory=sdk
```

Or for TypeScript:

```bash
npm install @agentescrow402/sdk-ts  # git tag equivalent above
```

## 2. Get a testnet key (1 min)

DM **@quentin** on the Casper Slack (or email
`quentin.tortotino@gmail.com`) with a one-liner:

> Pilot request — [your project name], [your handle]. Want a testnet key
> and $50 credit.

You'll get back an API key + a `.env` snippet within a few hours.

## 3. Create an escrow (30s)

```python
from agentescrow402 import Client

client = Client(api_key="ae402_test_...")

# Agent A locks 10 CSPR for Agent B in exchange for service_hash.
escrow = client.create_escrow(
    receiver="account-hash-<AGENT_B_ACCOUNT>",
    amount_motes=10_000_000_000,       # 10 CSPR
    service_hash="<sha256 of the agreed deliverable spec>",
    ttl=3600,                          # 1 hour
)

print(escrow.escrow_id, escrow.status)  # "esc-abc123..." "pending"
```

## 4. Release on success (30s)

```python
# Agent B delivered. Agent A releases the funds.
receipt = client.release(escrow.escrow_id)
print(receipt.tx_hash)  # real Casper testnet tx
```

## 5. Dispute on failure (60s)

```python
# Agent B never delivered. Agent A files a dispute with evidence.
verdict = client.dispute(
    escrow.escrow_id,
    evidence={
        "expected_hash": "<sha256 of spec>",
        "received_hash": None,           # nothing shipped
        "notes": "Receiver did not respond within TTL.",
    },
)

# The arbiter (real LLM, not a mock) reads the FSM history + your
# evidence and rules. If it rules for you, funds refund automatically.
print(verdict.ruling, verdict.reasoning)  # "REFUND" / "..."
```

## 6. That's it

You now have:

- A programmatic escrow with a real on-chain deposit.
- A programmatic dispute path with a real LLM arbiter.
- Auditable receipts (`receipt.tx_hash`) for both outcomes.
- No wallet UX for your users to worry about.

## Advanced (5 more minutes)

- **Confidential amounts (W.2):** `client.create_confidential_escrow(...)`
  — the amount is a Pedersen commitment; only sender + receiver see
  the value.
- **Cross-chain trigger (W.3):** `client.create_cross_chain_escrow(...,
  trigger_chain="ethereum", trigger_tx_hash="0x...")` — the escrow
  releases automatically when a specific Ethereum event lands.
- **Insurance pool:** every escrow is optionally backed by a pool that
  pays out if the arbiter is wrong (post-mortem review).
- **LangChain / AutoGen / CrewAI:** first-class `Tool` wrappers ship in
  `sdk/langchain_tool.py`, `sdk/autogen_tool.py`, `sdk/crewai_tool.py`.

## Feedback loop

- **Slack:** DM `@quentin` on the Casper community Slack.
- **GitHub issues:** <https://github.com/alexbelij/AgentEscrow402/issues>
- **48h reply SLA** during the pilot week.

## When it clicks

We ask for a 3-sentence quote for the hackathon submission page and a
public GitHub star. That's the whole ask. Nothing more.
