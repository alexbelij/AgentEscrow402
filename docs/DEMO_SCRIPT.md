# AE402 · Demo script

Ten-minute walkthrough for judges, investors, and anyone dropping in
for the first time. Every step below has a matching runnable command
(all `demo/*_showcase.py` scripts exit 0 on green and are exercised
nightly by `.github/workflows/nightly-demos.yml`).

**Setup once:**

```bash
git clone https://github.com/alexbelij/AgentEscrow402 && cd AgentEscrow402
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && pip install -e .
export AE402_BOOTSTRAP_MODE=1 AE402_DEMO_MODE=1
```

Everything below then runs offline against the in-memory FastAPI
`TestClient` — no Casper node, no Ethereum RPC, no LLM keys.

---

## 1 · Escrow lifecycle (2 min)

**Story:** two AI agents transact on-chain. Buyer pays via HTTP 402;
seller does the work; escrow settles.

```bash
PYTHONPATH=. python demo/x402_agent_showcase.py
```

You'll see:

- **CREATE**  → escrow row is written with amount + service_hash
- **PAY**     → x402 payment attaches; nonce recorded; replay-guard armed
- **SETTLE**  → funds move to seller
- **REPLAY**  → same nonce twice → 401 (proof the guard fires)

---

## 2 · Insurance × Dispute × Reputation (3 min)

**Story:** an escrow goes wrong. Agent A demands a refund. The rubric
scores it; the arbiter panel decides. Reputation compounds.

```bash
PYTHONPATH=. python demo/insurance_showcase.py
```

Then open [`/console/insurance-demo`](https://ae402.xyz/console/insurance-demo)
in the browser:

- Move the **reputation slider** — watch the premium change tier
  (`high_risk` → `medium_risk` → `neutral` → `low_risk`)
- Fill the **rubric preview**: reputation deltas, evidence counts,
  prior disputes → deterministic score with ordered reasons
- Toggle **X402 replay flagged** → note the panel is *always* required
  (safety invariant)

Backing files: `server/rep_pricing.py`, `server/dispute_ai.py`.

---

## 3 · Regime shift & risk (2 min)

**Story:** a counterparty's escrow amounts are drifting up. When is a
regime shift real vs. noise? CUSUM says.

Open [`/console/risk`](https://ae402.xyz/console/risk):

- Paste a sample stream (or use the default)
- Nudge k/h — see the alarm engage as the S_pos accumulator crosses
  the threshold
- **Direction** column tells you whether it's a positive or negative
  shift; **first_alarm_index** tells you when it first crossed

Query pack the widget consumes lives in `docs/analytics/allium/`.

---

## 4 · Bridge lifecycle (2 min)

**Story:** move value across chains, deterministically, with atomic
HTLC. Happy path plus refund on timelock expiry.

```bash
PYTHONPATH=. python demo/bridge_e2e_showcase.py
```

Eight steps end-to-end:

1. Initiate swap (both legs PROPOSED)
2. Lock casper leg
3. Lock EVM leg (both legs under hashlock)
4. Claim EVM leg → preimage revealed
5. Claim casper leg → same preimage propagates
6. Verify both legs CLAIMED
7. Second swap: lock, expire, refund
8. Verify both legs REFUNDED

Set `AE402_BRIDGE_MODE=sepolia` to point the same nine steps at a real
Ethereum testnet (adapter in `server/bridge_evm_adapter.py`; mode
selector in `server/bridge_mode.py`; safety fuse on mainnet).

---

## 5 · Arbiter MEV, slashing, panel sizing (30 s)

**Story:** what stops arbiters from front-running each other's
verdicts?

- **Commit-reveal** (`server/arbiter_commit_reveal.py`) — a verdict
  hash is committed *before* any reveal; the salt is ≥16 bytes; verify
  runs in constant time.
- **Slashing** (`server/slashing.py`) — a deterministic decision
  function maps offence kind → bond burn + panel ban. Equivocation is
  a hard slash (100% bond, ~permanent ban).
- **Panel sizing** (`server/panel_sizing.py`) — a bigger escrow gets a
  bigger panel (3 → 5 → 7 → 9). Always odd. No ties.

Test:

```bash
pytest tests/test_arbiter_commit_reveal.py tests/test_slashing.py \
       tests/test_panel_sizing.py -v
```

---

## 6 · Prompt-injection safety (30 s)

**Story:** an untrusted agent tries to poison the dispute AI narrator
via evidence text. The safety filter blocks it.

```bash
PYTHONPATH=. python demo/prompt_injection_demo.py
```

12 payloads, exit 0. The dispute rubric itself is a pure function —
even a passing payload can't change the deterministic score.

---

## FAQ

**Q: Is this on-chain?**
Yes for Casper Testnet (349 deploys and counting — see
[cspr.live](https://testnet.cspr.live)). The EVM leg of the bridge
runs on Sepolia; mainnet requires an explicit safety flag.

**Q: What LLM do you use?**
For the dispute-AI narrator, any host that speaks MCP works — Claude
Desktop, Cursor, OpenClaw. The narrator is **advisory only** and
never mutates the score. The rubric is a pure function of the inputs.

**Q: What if the sub-agent lies?**
It can't — every safety property is enforced by a pure function or an
on-chain check. See `docs/AGENTIC_SAFETY.md` for the threat model.

---

## Related documents

- `README.md` — repo entry point
- `docs/ARCHITECTURE.md` — system architecture
- `docs/AGENTIC_SAFETY.md` — safety model
- `docs/API_SDK_MCP.md` — the three surfaces
- `docs/mcp/README.md` — curated MCP tool set
- `docs/analytics/README.md` — Allium query pack
