"""Subprocess smoke tests for demo/multi_asset_flow.py.

Same style as tests/test_demo_agent_flow.py (from C3) — treat the demo as
a real user command, invoke it via subprocess, parse its JSON output,
assert the lifecycle actually completed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_MODULE = "demo.multi_asset_flow"


def _run(*flags: str, timeout: int = 45) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", DEMO_MODULE, *flags],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _parse_json(stdout: str) -> dict:
    """The demo may print a Neon-unavailable warning before the JSON.
    Find the first line that starts a JSON object and parse from there.
    """
    idx = stdout.rfind("{")
    if idx < 0:
        raise AssertionError(f"no JSON object in stdout: {stdout!r}")
    return json.loads(stdout[idx:])


def test_default_run_produces_released_receipt():
    result = _run("--json")
    assert result.returncode == 0, (
        f"demo failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    receipt = _parse_json(result.stdout)
    assert receipt["token_type"] == "cspr"
    assert receipt["created_status"] == "pending"
    assert receipt["final_status"] == "released"
    assert receipt["terminal_http"] == 200
    # service_hash is 64-hex.
    assert len(receipt["service_hash"]) == 64
    int(receipt["service_hash"], 16)  # parseable as hex


def test_refund_flag_produces_refunded_receipt():
    result = _run("--refund", "--json")
    assert result.returncode == 0, (
        f"demo --refund failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    receipt = _parse_json(result.stdout)
    assert receipt["final_status"] == "refunded"
    assert receipt["terminal_http"] == 200


def test_amount_override_flows_through():
    result = _run("--amount", "5000000000", "--json")
    assert result.returncode == 0, result.stderr
    receipt = _parse_json(result.stdout)
    assert receipt["amount"] == 5_000_000_000


def test_human_readable_output_mentions_all_fields():
    """Non-JSON default output must show the fields a demo watcher expects."""
    result = _run()
    assert result.returncode == 0, result.stderr
    text = result.stdout
    for needle in ("token_type", "service_hash", "created_status", "final_status", "terminal_http"):
        assert needle in text, f"missing {needle!r} in default output:\n{text}"
