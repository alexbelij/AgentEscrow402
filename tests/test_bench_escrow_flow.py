"""Smoke tests for scripts/bench_escrow_flow.py.

We do NOT assert absolute latency numbers here — those depend on
hardware. We only verify:

- The script runs to completion in reasonable time.
- All scenarios succeed (rate-limit patch works, no auth errors).
- The JSON schema is stable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "bench_escrow_flow.py"


def _run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_fast_profile_runs_and_all_scenarios_succeed(tmp_path):
    out = tmp_path / "bench.json"
    result = _run(["--profile", "fast", "--iterations", "30", "--concurrency", "4", "--out", str(out)])
    assert result.returncode == 0, (
        f"bench script failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert out.exists(), f"expected JSON at {out}"

    report = json.loads(out.read_text())

    # Schema-shape assertions.
    for key in ("timestamp", "python", "profile", "iterations", "concurrency", "scenarios"):
        assert key in report, f"missing key {key} in report"
    assert isinstance(report["scenarios"], list)
    assert len(report["scenarios"]) >= 3

    # Every scenario must have zero errors (rate-limit patch working)
    # and populated latency percentiles.
    for sc in report["scenarios"]:
        for key in ("name", "ok", "errors", "rps", "p50_ms", "p95_ms", "p99_ms", "max_ms"):
            assert key in sc, f"scenario {sc.get('name')!r} missing key {key}"
        assert sc["errors"] == 0, f"scenario {sc['name']} errored: {sc.get('error_samples')}"
        assert sc["ok"] == 30
        assert sc["p50_ms"] > 0
        assert sc["p95_ms"] >= sc["p50_ms"]
        assert sc["p99_ms"] >= sc["p95_ms"]


def test_no_write_mode_still_prints_summary():
    result = _run(["--profile", "fast", "--iterations", "20", "--concurrency", "2", "--no-write"])
    assert result.returncode == 0, result.stderr
    # Markdown summary printed to stdout.
    assert "AE402 escrow-flow benchmark" in result.stdout
    assert "GET  /health" in result.stdout
    assert "POST /escrow" in result.stdout


def test_custom_iterations_override_profile(tmp_path):
    out = tmp_path / "b.json"
    result = _run(["--iterations", "10", "--concurrency", "2", "--out", str(out)])
    assert result.returncode == 0, result.stderr
    report = json.loads(out.read_text())
    assert report["iterations"] == 10
    assert report["concurrency"] == 2
    for sc in report["scenarios"]:
        assert sc["ok"] == 10
