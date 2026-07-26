"""Tests for sdk/samples/autonomous_agent.py.

Two flavours:

- Unit tests instantiate the classes directly (no subprocess). Fast.
- One subprocess test to verify the CLI happy path end-to-end.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module", autouse=True)
def _setup_env(monkeypatch_module=None):
    """Set the sandbox env vars before the module is imported."""
    import os

    os.environ.setdefault("SANDBOX", "true")
    os.environ.setdefault("ALLOW_HOSTED_DEMO_IDENTITY", "true")
    yield


def _import_sample():
    """Import the sample after env is set."""
    from sdk.samples import autonomous_agent

    return autonomous_agent


def _make_test_client():
    from fastapi.testclient import TestClient

    from server.app import app

    return TestClient(app)


def test_mock_llm_first_call_selects_a_tool():
    mod = _import_sample()
    brain = mod.MockLLM()
    thought = brain.step("get me CSPR price", observations=[])
    assert thought.action == "get_market_data"
    assert thought.args == {"symbol": "CSPR"}


def test_mock_llm_picks_symbol_from_goal():
    mod = _import_sample()
    brain = mod.MockLLM()
    for symbol in ("BTC", "ETH", "CSPR"):
        thought = brain.step(f"give me the current {symbol.lower()} price", [])
        assert thought.args["symbol"] == symbol


def test_mock_llm_answers_after_observation():
    mod = _import_sample()
    brain = mod.MockLLM()
    thought = brain.step("goal", observations=["some tool output"])
    assert thought.action == "answer"
    assert thought.args["final"] == "some tool output"


def test_priced_tool_returns_402_without_payment():
    mod = _import_sample()
    tool = mod.PricedMarketDataTool(client=None, seller_hex="ff" * 32)
    status, payload = tool.call("CSPR")
    assert status == 402
    assert payload["error"] == "payment_required"
    ch = payload["challenge"]
    assert ch["amount"] == mod.PricedMarketDataTool.PRICE_PER_CALL
    assert len(ch["service_hash"]) == 64


def test_priced_tool_returns_data_after_mark_paid():
    mod = _import_sample()
    tool = mod.PricedMarketDataTool(client=None, seller_hex="ff" * 32)
    _, payload = tool.call("CSPR")
    svc_hash = payload["challenge"]["service_hash"]
    tool.mark_paid(svc_hash)
    status, data = tool.call("CSPR", paid_service_hash=svc_hash)
    assert status == 200
    assert data["symbol"] == "CSPR"
    assert data["price"] > 0


def test_full_agent_run_creates_and_releases_escrow(monkeypatch):
    """End-to-end integration: agent should produce a released escrow.

    We use a random seller each run so we can't collide with escrows
    left over from other tests in the same suite (SandboxStore is
    process-global and shared across the whole pytest run).

    Config is a FROZEN dataclass and other tests in the suite
    reinstantiate it without the hosted-demo flag — which knocks out
    the _setup_stubs() config patch we set here. Guard by rebuilding
    the singleton with the env var set, so this test is deterministic
    regardless of file ordering.
    """
    mod = _import_sample()
    monkeypatch.setenv("ALLOW_HOSTED_DEMO_IDENTITY", "true")
    monkeypatch.setenv("SANDBOX", "true")

    # server/app.py caches get_config() via @lru_cache. Other tests may
    # have poisoned the cache before we set the env. Clear both caches
    # so we get a fresh Config from the env we just monkeypatched.
    import server.app as _sapp
    import server.middleware as _smw

    _sapp.get_config.cache_clear()
    for fn_name in ("get_config",):
        fn = getattr(_smw, fn_name, None)
        if fn is not None and hasattr(fn, "cache_clear"):
            fn.cache_clear()

    mod._setup_stubs()

    import hashlib
    import secrets

    seller_hex = hashlib.sha256(secrets.token_bytes(16)).hexdigest()

    with _make_test_client() as client:
        tool = mod.PricedMarketDataTool(client, seller_hex)
        agent = mod.AutonomousAgent(mod.MockLLM(), tool, client)
        run = agent.run("get me the current CSPR price")

    assert run.escrows_created == 1
    assert run.total_paid == mod.PricedMarketDataTool.PRICE_PER_CALL
    # Final answer should be a JSON string with the tool's data.
    parsed = json.loads(run.final_answer)
    assert parsed["symbol"] == "CSPR"
    assert isinstance(parsed["price"], float)


def test_cli_produces_json_receipt(tmp_path):
    """Subprocess smoke test: python -m sdk.samples.autonomous_agent --json"""
    result = subprocess.run(
        [sys.executable, "-m", "sdk.samples.autonomous_agent", "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, f"CLI failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    # The JSON receipt is the entire stdout (or the last block starting
    # with '{' if the sandbox prints warnings first). Find the first line
    # that is exactly '{' and parse from there.
    lines = result.stdout.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == "{"), None)
    assert start is not None, f"no JSON object start in stdout:\n{result.stdout}"
    receipt = json.loads("\n".join(lines[start:]))
    assert receipt["escrows_created"] == 1
    assert receipt["total_paid"] > 0
    assert receipt["turns"] >= 3  # thought + 402 + escrow + retry + data + answer path
