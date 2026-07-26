"""End-to-end tests for the new risk-analytics endpoints:

- POST /risk/regime-shift/cusum
- POST /risk/regime-shift/page-hinkley
- POST /risk/regime-shift/benchmark
- POST /risk/premium
- POST /risk/premium/batch
"""

from __future__ import annotations

import random

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.risk_api import router


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Regime-shift endpoints
# ---------------------------------------------------------------------------


def test_cusum_endpoint_stationary(client: TestClient) -> None:
    # Deterministic seed + a *conservative* threshold. On stationary N(0,1)
    # with h=8 the ARL_0 is ~2000+, so 200 samples should be almost always
    # alarm-free. We check the *count* of alarms rather than their position
    # because CUSUM naturally fires occasionally in the tail of any finite
    # gaussian window regardless of true stationarity.
    rng = random.Random(101)
    stream = [rng.gauss(0.0, 1.0) for _ in range(200)]
    r = client.post(
        "/risk/regime-shift/cusum",
        json={"values": stream, "mu0": 0.0, "sigma": 1.0, "cusum_h": 8.0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["n_samples"] == 200
    total_alarms = sum(1 for res in body["results"] if res["alarm_upper"] or res["alarm_lower"])
    # With h=8 on N(0,1), expect ~0 alarms in 200 samples.
    assert total_alarms <= 5, f"too many false alarms on stationary noise: {total_alarms}"


def test_cusum_endpoint_detects_upshift(client: TestClient) -> None:
    rng = random.Random(103)
    stream = [rng.gauss(0.0, 1.0) for _ in range(200)]
    stream += [rng.gauss(2.5, 1.0) for _ in range(200)]
    r = client.post(
        "/risk/regime-shift/cusum",
        json={"values": stream, "mu0": 0.0, "sigma": 1.0, "cusum_h": 5.0},
    )
    body = r.json()
    assert body["first_alarm_idx"] is not None
    assert 200 <= body["first_alarm_idx"] <= 260
    assert body["first_alarm_direction"] == "upper"


def test_cusum_endpoint_empty_stream_rejected(client: TestClient) -> None:
    r = client.post("/risk/regime-shift/cusum", json={"values": []})
    assert r.status_code == 400


def test_cusum_endpoint_oversized_rejected(client: TestClient) -> None:
    r = client.post(
        "/risk/regime-shift/cusum",
        json={"values": [0.0] * 10001},
    )
    assert r.status_code == 413


def test_cusum_endpoint_bad_sigma_returns_400(client: TestClient) -> None:
    r = client.post(
        "/risk/regime-shift/cusum",
        json={"values": [0.0, 1.0], "sigma": 0.0},
    )
    assert r.status_code == 400


def test_page_hinkley_endpoint_stationary(client: TestClient) -> None:
    rng = random.Random(107)
    stream = [rng.gauss(0.0, 1.0) for _ in range(200)]
    r = client.post(
        "/risk/regime-shift/page-hinkley",
        json={"values": stream, "ph_threshold": 50.0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["first_alarm_idx"] is None


def test_page_hinkley_endpoint_detects_drift(client: TestClient) -> None:
    rng = random.Random(109)
    stream = [3.0 * t / 500.0 + rng.gauss(0.0, 0.5) for t in range(500)]
    r = client.post(
        "/risk/regime-shift/page-hinkley",
        json={"values": stream, "ph_delta": 0.005, "ph_threshold": 20.0},
    )
    body = r.json()
    assert body["first_alarm_idx"] is not None
    assert body["first_alarm_idx"] < 450


def test_benchmark_endpoint_reports_agreement(client: TestClient) -> None:
    rng = random.Random(113)
    stream = [rng.gauss(0.0, 1.0) for _ in range(200)]
    stream += [rng.gauss(3.0, 1.0) for _ in range(200)]
    r = client.post(
        "/risk/regime-shift/benchmark",
        json={"values": stream, "mu0": 0.0, "sigma": 1.0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["n_samples"] == 400
    assert body["first_cusum_alarm_idx"] is not None
    assert body["first_page_hinkley_alarm_idx"] is not None
    # Both should fire on a sustained 3-sigma shift
    assert 0.0 <= body["agreement_ratio"] <= 1.0


def test_benchmark_endpoint_extra_fields_rejected(client: TestClient) -> None:
    r = client.post(
        "/risk/regime-shift/benchmark",
        json={"values": [0.0, 1.0], "surprise_field": True},
    )
    assert r.status_code == 422  # pydantic strict rejection


# ---------------------------------------------------------------------------
# Premium endpoints
# ---------------------------------------------------------------------------


def test_premium_endpoint_zero_history(client: TestClient) -> None:
    r = client.post("/risk/premium", json={"successes": 0, "disputes": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["should_refuse"] is False
    assert body["premium_bps"] > 0


def test_premium_endpoint_clean_vs_dirty(client: TestClient) -> None:
    clean = client.post("/risk/premium", json={"successes": 100, "disputes": 0}).json()
    dirty = client.post("/risk/premium", json={"successes": 100, "disputes": 20}).json()
    assert clean["premium_bps"] < dirty["premium_bps"]
    assert clean["ci_upper"] < dirty["ci_upper"]


def test_premium_endpoint_extreme_disputes_refuses(client: TestClient) -> None:
    r = client.post("/risk/premium", json={"successes": 10, "disputes": 90})
    body = r.json()
    assert body["should_refuse"] is True


def test_premium_endpoint_rejects_negative(client: TestClient) -> None:
    r = client.post("/risk/premium", json={"successes": -1, "disputes": 0})
    assert r.status_code == 422  # pydantic validation


def test_premium_batch_endpoint(client: TestClient) -> None:
    r = client.post(
        "/risk/premium/batch",
        json={
            "items": [
                {"successes": 100, "disputes": 0},
                {"successes": 100, "disputes": 5},
                {"successes": 100, "disputes": 30},
            ]
        },
    )
    assert r.status_code == 200
    out = r.json()
    assert len(out) == 3
    assert out[0]["premium_bps"] <= out[1]["premium_bps"] <= out[2]["premium_bps"]


def test_premium_batch_oversized_rejected(client: TestClient) -> None:
    items = [{"successes": 0, "disputes": 0} for _ in range(501)]
    r = client.post("/risk/premium/batch", json={"items": items})
    assert r.status_code == 413
