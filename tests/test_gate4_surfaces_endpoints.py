"""End-to-end tests for Gate 4 operator + judge surfaces."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# /ops/health
# ---------------------------------------------------------------------------


def test_ops_health_returns_snapshot_shape():
    resp = client.get("/ops/health")
    assert resp.status_code == 200
    body = resp.json()
    for key in [
        "started_at",
        "uptime_s",
        "build_sha",
        "config_version",
        "mode",
        "strict_mode",
        "dependencies",
        "retries",
        "warnings",
    ]:
        assert key in body, f"missing key: {key}"


def test_ops_health_no_secrets_in_payload():
    resp = client.get("/ops/health")
    body_text = resp.text.lower()
    for forbidden in ("api_key", "api-key", "gsk_", "sk-", "nvapi-", "openrouter_api"):
        assert forbidden not in body_text, f"secret-shape leaked: {forbidden}"


def test_ops_health_reports_all_providers():
    resp = client.get("/ops/health")
    body = resp.json()
    names = {p["name"] for p in body["dependencies"]}
    assert names == {"groq", "nvidia", "openrouter", "gemini"}


# ---------------------------------------------------------------------------
# /demo/three-step
# ---------------------------------------------------------------------------


def test_demo_three_step_happy_scenario():
    resp = client.post("/demo/three-step", json={"scenario": "happy"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["scenario"] == "happy"
    assert len(body["steps"]) == 3
    assert body["steps"][0]["title"] == "Create escrow"
    assert body["steps"][1]["title"] == "Release funds"
    # Determinism: same call, same body
    resp2 = client.post("/demo/three-step", json={"scenario": "happy"})
    assert resp2.json() == body


def test_demo_three_step_dispute_scenario():
    resp = client.post("/demo/three-step", json={"scenario": "dispute"})
    body = resp.json()
    assert body["scenario"] == "dispute"
    assert len(body["steps"]) == 3
    paths = [s["path"] for s in body["steps"]]
    assert "/arbitration/analyze" in paths


def test_demo_three_step_abstain_scenario():
    resp = client.post("/demo/three-step", json={"scenario": "abstain"})
    body = resp.json()
    assert body["scenario"] == "abstain"
    assert len(body["steps"]) == 3
    # Auto-escalation must be part of the abstain script
    assert any("VRF" in s["title"] or "panel" in s["title"] for s in body["steps"])


def test_demo_three_step_default_is_happy():
    resp = client.post("/demo/three-step", json={})
    assert resp.status_code == 200
    assert resp.json()["scenario"] == "happy"


def test_demo_three_step_unknown_scenario_rejected():
    resp = client.post("/demo/three-step", json={"scenario": "chaos"})
    assert resp.status_code == 400
    assert "scenario" in resp.json()["detail"]


def test_demo_three_step_case_insensitive():
    resp = client.post("/demo/three-step", json={"scenario": "HAPPY"})
    assert resp.status_code == 200
    assert resp.json()["scenario"] == "happy"


def test_demo_three_step_step_indices_are_1_2_3():
    for scenario in ("happy", "dispute", "abstain"):
        resp = client.post("/demo/three-step", json={"scenario": scenario})
        indices = [s["index"] for s in resp.json()["steps"]]
        assert indices == [1, 2, 3], f"{scenario}: {indices}"
