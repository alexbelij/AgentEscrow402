#!/usr/bin/env python3
"""Autonomous ReAct-style agent that detects HTTP 402, pays, and consumes.

This is the smallest possible reference implementation of an agent that
transacts autonomously through AE402:

  1. Receive a natural-language *goal* (e.g. "fetch the current CSPR
     price and store it").
  2. Decide which tool to call. In this demo we have a single tool:
     `get_market_data(symbol)`.
  3. Call the tool endpoint. If it returns HTTP 402 with a payment
     challenge, the agent creates an escrow with the SDK, retries, and
     records the outcome.
  4. Return the tool result to the calling loop.

The ReAct loop terminates when the agent has an answer for the goal.

The agent's "brain" is a deterministic mock LLM (`MockLLM`) so this file
runs in CI without any API key. In production you'd swap in an Anthropic /
OpenAI / local model call — the interface (`step(observation) -> Action`)
is the only contract.

Usage:
    python -m sdk.samples.autonomous_agent                 # sandbox default
    python -m sdk.samples.autonomous_agent --goal "..."    # custom goal
    python -m sdk.samples.autonomous_agent --json          # machine output
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# In-process sandbox setup.
os.environ.setdefault("SANDBOX", "true")
os.environ.setdefault("ALLOW_HOSTED_DEMO_IDENTITY", "true")

HOSTED_DEMO_SENDER = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
HOSTED_DEMO_SIG = "a" * 128
X402_VERSION = "x402-v1"


# ---------- The Mock LLM -----------------------------------------------------


@dataclass
class Thought:
    """One reasoning + action step produced by the agent's brain."""

    thought: str
    action: str
    args: dict[str, Any] = field(default_factory=dict)


class MockLLM:
    """Deterministic 'agent brain' for demo + CI.

    Real production code replaces this with an Anthropic / OpenAI call:

        class RealBrain:
            def step(self, goal, observations):
                resp = anthropic.messages.create(...)
                return parse(resp)

    We keep the interface a single method — `step()` — so both types
    are drop-in compatible.
    """

    def __init__(self, price_map: dict[str, float] | None = None):
        # A tiny in-memory table so we can round-trip a plausible "answer".
        self._prices = price_map or {"CSPR": 0.0451, "BTC": 65_432.10, "ETH": 3_204.55}

    def step(self, goal: str, observations: list[str]) -> Thought:
        # Turn 0: no observations yet — always call the pricing tool.
        if not observations:
            symbol = "CSPR"
            for candidate in ("BTC", "ETH", "CSPR"):
                if candidate.lower() in goal.lower():
                    symbol = candidate
                    break
            return Thought(
                thought=f"I need current price for {symbol}. Calling market data tool.",
                action="get_market_data",
                args={"symbol": symbol},
            )

        # Turn 1+: we got the tool result — synthesise the final answer.
        last = observations[-1]
        return Thought(
            thought=f"Tool returned {last!r}. That answers the goal.",
            action="answer",
            args={"final": last},
        )


# ---------- The Priced Tool --------------------------------------------------


class PricedMarketDataTool:
    """A pay-per-call market-data tool wired to AE402.

    First call returns HTTP 402 with an escrow challenge. The agent
    creates an escrow, retries with the challenge accepted, and the
    tool returns the data.

    In real deployment the tool would be a separate HTTP service the
    seller runs and this shim would be a thin `httpx.get()`. Here it's
    an in-process class so the demo is self-contained.
    """

    PRICE_PER_CALL = 100_000_000  # 0.1 CSPR

    def __init__(self, client, seller_hex: str):
        self._client = client
        self._seller = seller_hex
        self._prices = {"CSPR": 0.0451, "BTC": 65_432.10, "ETH": 3_204.55}
        self._paid_escrows: set[str] = set()

    def _challenge_for(self, symbol: str) -> dict:
        """Produce the 402 payment challenge for a symbol."""
        nonce = secrets.token_hex(16)
        service_hash = hashlib.sha256(
            f"market-data|{symbol}|{HOSTED_DEMO_SENDER}|{self._seller}|"
            f"{self.PRICE_PER_CALL}|{nonce}".encode()
        ).hexdigest()
        return {
            "amount": self.PRICE_PER_CALL,
            "receiver": self._seller,
            "service_hash": service_hash,
            "nonce": nonce,
            "sender": HOSTED_DEMO_SENDER,
        }

    def call(self, symbol: str, paid_service_hash: str | None = None) -> tuple[int, dict]:
        if paid_service_hash is None or paid_service_hash not in self._paid_escrows:
            challenge = self._challenge_for(symbol)
            return 402, {"error": "payment_required", "challenge": challenge}

        # Payment observed. Return the data.
        price = self._prices.get(symbol.upper())
        if price is None:
            return 404, {"error": "unknown_symbol", "symbol": symbol}
        return 200, {"symbol": symbol, "price": price, "quote_ts": int(time.time())}

    def mark_paid(self, service_hash: str) -> None:
        self._paid_escrows.add(service_hash)


# ---------- Autonomous Agent -------------------------------------------------


@dataclass
class AgentRun:
    goal: str
    turns: int
    escrows_created: int
    total_paid: int
    final_answer: Any
    trace: list[dict[str, Any]]


class AutonomousAgent:
    """A skeleton ReAct agent wired to a mock LLM + a priced tool."""

    MAX_TURNS = 6

    def __init__(self, brain: MockLLM, tool: PricedMarketDataTool, client):
        self._brain = brain
        self._tool = tool
        self._client = client

    # ----- x402 helpers (kept tiny — a real SDK client would wrap these) ----

    def _x402_header(self, service_hash: str, amount: int, nonce: str) -> dict:
        ts = str(int(time.time()))
        payment = ";".join([
            X402_VERSION, service_hash, str(amount), HOSTED_DEMO_SENDER, ts, nonce, HOSTED_DEMO_SIG
        ])
        return {"X-Payment": payment, "X-AE402-Demo-Identity": "hosted-console"}

    def _create_escrow(self, challenge: dict) -> str:
        """Create the escrow the tool asked for. Returns the escrow's service_hash."""
        body = {
            "sender": challenge["sender"],
            "receiver": challenge["receiver"],
            "amount": str(challenge["amount"]),
            "nonce": challenge["nonce"],
            "service_hash": challenge["service_hash"],
        }
        headers = self._x402_header(
            challenge["service_hash"], challenge["amount"], challenge["nonce"]
        )
        r = self._client.post("/escrow", json=body, headers=headers)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"escrow create failed: {r.status_code} {r.text[:200]}")
        return challenge["service_hash"]

    def _release_escrow(self, service_hash: str, amount: int) -> None:
        headers = self._x402_header(service_hash, amount, secrets.token_hex(16))
        r = self._client.post(
            "/release",
            json={"service_hash": service_hash, "arbiter_pubkeys": [], "arbiter_signatures": []},
            headers=headers,
        )
        if r.status_code not in (200, 201):
            # Not fatal — the tool has already served us the data. Log it.
            pass

    # ----- The ReAct loop ---------------------------------------------------

    def run(self, goal: str) -> AgentRun:
        observations: list[str] = []
        trace: list[dict[str, Any]] = []
        escrows_created = 0
        total_paid = 0
        final_answer: Any = None

        for turn in range(self.MAX_TURNS):
            thought = self._brain.step(goal, observations)
            trace.append({"turn": turn, **asdict(thought)})

            if thought.action == "answer":
                final_answer = thought.args.get("final")
                break

            if thought.action == "get_market_data":
                symbol = thought.args["symbol"]

                # First call — expect 402.
                status, payload = self._tool.call(symbol)
                trace.append({"turn": turn, "tool_first_call": {"status": status, "payload": payload}})

                if status == 402:
                    challenge = payload["challenge"]
                    escrow_svc_hash = self._create_escrow(challenge)
                    escrows_created += 1
                    total_paid += challenge["amount"]
                    self._tool.mark_paid(escrow_svc_hash)
                    trace.append({"turn": turn, "escrow_created": escrow_svc_hash})

                    # Retry with proof of payment.
                    status2, payload2 = self._tool.call(symbol, paid_service_hash=escrow_svc_hash)
                    trace.append({"turn": turn, "tool_retry": {"status": status2, "payload": payload2}})

                    # Release funds to seller now that we got the data.
                    self._release_escrow(escrow_svc_hash, challenge["amount"])
                    trace.append({"turn": turn, "escrow_released": escrow_svc_hash})

                    observations.append(json.dumps(payload2))
                elif status == 200:
                    observations.append(json.dumps(payload))
                else:
                    observations.append(json.dumps({"error": payload}))
                    break

        return AgentRun(
            goal=goal,
            turns=len(trace),
            escrows_created=escrows_created,
            total_paid=total_paid,
            final_answer=final_answer,
            trace=trace,
        )


# ---------- CLI --------------------------------------------------------------


def _setup_stubs() -> None:
    """One-time in-process setup: stub casper.

    NOTE: We used to also replace ``server.app._rate_limits`` with a no-op
    dict to avoid the 60/min limit during the demo. That mutation is
    process-global and poisoned other tests in the suite (the rate-limit
    middleware tests started passing 200s where they should have seen 429).
    The sample only makes a handful of requests per run — well under the
    limit — so the stub is unnecessary. Removed to keep the suite clean.
    """
    try:
        from server import app as _sapp
        if getattr(_sapp, "_casper", None) is None:
            class _StubCasper:
                async def close(self):
                    return None
            _sapp._casper = _StubCasper()
    except Exception:
        pass

    try:
        from server.config import get_config
        cfg = get_config()
        cfg.allow_hosted_demo_identity = True
        # Some code paths read the raw env var each request instead of the
        # cached Config object. Set both so we're covered whichever path
        # is exercised.
        os.environ["ALLOW_HOSTED_DEMO_IDENTITY"] = "true"
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--goal",
        default="Get the current price of CSPR.",
        help="Natural-language goal for the agent.",
    )
    ap.add_argument("--json", dest="as_json", action="store_true", help="Machine-readable output")
    args = ap.parse_args()

    _setup_stubs()
    from fastapi.testclient import TestClient
    from server.app import app  # noqa: E402

    seller_hex = hashlib.sha256(b"autonomous-agent-sample-seller").hexdigest()

    with TestClient(app) as client:
        tool = PricedMarketDataTool(client, seller_hex)
        brain = MockLLM()
        agent = AutonomousAgent(brain, tool, client)
        run = agent.run(args.goal)

    if args.as_json:
        print(json.dumps(asdict(run), indent=2, sort_keys=True, default=str))
        return 0

    print(f"Goal:              {run.goal}")
    print(f"Turns taken:       {run.turns}")
    print(f"Escrows created:   {run.escrows_created}")
    print(f"Total paid:        {run.total_paid} motes  (~{run.total_paid / 1e9:.4f} CSPR)")
    print(f"Final answer:      {run.final_answer}")
    print()
    print("Trace (last 6 steps):")
    for entry in run.trace[-6:]:
        keys = ", ".join(k for k in entry if k != "turn")
        print(f"  turn {entry.get('turn', '?')}: {keys}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
