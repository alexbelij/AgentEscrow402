# Autonomous agent — SDK sample

`sdk/samples/autonomous_agent.py` is the smallest possible reference
implementation of an agent that transacts autonomously through AE402.
It's how the "SDK sample scripts demonstrate an autonomous agent"
submission checklist item is exercised end-to-end.

## Run it

```
python -m sdk.samples.autonomous_agent
python -m sdk.samples.autonomous_agent --goal "give me the current BTC price"
python -m sdk.samples.autonomous_agent --json
```

Default output:

```
Goal:              Get the current price of CSPR.
Turns taken:       6
Escrows created:   1
Total paid:        100000000 motes  (~0.1000 CSPR)
Final answer:      {"symbol": "CSPR", "price": 0.0451, "quote_ts": 1785062940}
```

Runs in-process against a sandbox FastAPI stack — no network, no
Casper deploy latency, ~200 ms wall time.

## What the sample demonstrates

The ReAct loop is the entire pattern (six explicit steps):

1. **Think.** The agent's brain receives the goal and prior
   observations; emits a `Thought(action="get_market_data", args=...)`.
2. **Call the tool.** The tool checks whether the caller has paid.
   No proof of payment → returns `HTTP 402` with a challenge (amount,
   receiver, service_hash, nonce).
3. **Detect the 402.** The agent extracts the challenge from the
   response body.
4. **Create the escrow.** `POST /escrow` with the challenge details
   + an x402-signed header proving the caller is the sender.
5. **Retry the tool.** With proof of payment (the escrow's
   `service_hash`), the tool now returns the data.
6. **Release the escrow.** `POST /release` — funds move to the seller.

Repeat until the agent's brain emits `Thought(action="answer")`.

## Anatomy of the file

Three classes, each ~40 lines, each swappable:

- **`MockLLM`** — the agent's brain. In the sample it's a
  deterministic switch statement so CI can run without an API key.
  Replace with any Anthropic / OpenAI / local call — the interface is
  a single method `step(goal, observations) -> Thought`.
- **`PricedMarketDataTool`** — a stand-in for a real HTTP tool that
  charges per call. In production this would be a separate service the
  seller runs; here it's an in-process class so the demo has no
  external deps.
- **`AutonomousAgent`** — the ReAct loop wiring brain + tool + AE402
  client together. This is the part you *keep* when writing a real
  agent — plug in your own brain and tools.

## Swapping in a real LLM

Anywhere `MockLLM` appears, drop in a class with a `step()` method:

```python
import anthropic

class ClaudeBrain:
    def __init__(self):
        self._client = anthropic.Anthropic()

    def step(self, goal, observations):
        prompt = self._build_prompt(goal, observations)
        resp = self._client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._parse(resp.content[0].text)
```

The rest of the file — the escrow lifecycle, the 402-detect, the
retry — is unchanged.

## Related

- `sdk/samples/__init__.py` — package doc.
- `sdk/client.py` — the real `EscrowClient` you'd use against a live
  backend (Ed25519 signing, proper x402 header).
- `demo/multi_asset_flow.py` — a simpler demo that only covers the
  create + release/refund lifecycle (no ReAct loop).
- `docs/DEMO.md` — the CLI-judge `ae402 replay` demo.
- `examples/escrow_agent.py` — an alternative agent recipe covering
  dispute + arbiter-verdict flow.
