"""Smoke test for demo/agent_flow.py (C3).

The demo is intended to be run by judges/CI as a single-command
proof-of-life. If it stops importing or its scenarios stop returning
success, we want CI to fail loudly.

The test is a subprocess run, not an in-process one, so we exercise
the exact code path a judge would (`python -m demo.agent_flow`).
"""

from __future__ import annotations

import subprocess
import sys


def test_demo_agent_flow_happy_only() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "demo.agent_flow", "--good"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    assert "All scenarios completed as expected" in r.stdout
    assert "escrow created" in r.stdout
    assert "escrow released" in r.stdout


def test_demo_agent_flow_json_report() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "demo.agent_flow", "--good", "--json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr

    # The JSON report is emitted at the end as a pretty-printed multi-line
    # blob. Parse by walking backward from EOF looking for the LAST top-level
    # '{' that starts a column-0 line.
    import json

    lines = r.stdout.splitlines()
    start = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i] == "{":
            start = i
            break
    assert start is not None, f"no top-level JSON blob in stdout:\n{r.stdout}"
    payload = json.loads("\n".join(lines[start:]))
    assert "happy" in payload
    assert payload["happy"]["final_status"] == "released"
    assert payload["happy"]["amount"] == 1_000_000
    # History must include both events in order.
    actions = [e["action"] for e in payload["happy"]["history"]]
    assert actions[0] == "created"
    assert actions[-1] == "released"


def test_demo_agent_flow_refund() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "demo.agent_flow", "--refund"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert "Scenario: refund" in r.stdout
