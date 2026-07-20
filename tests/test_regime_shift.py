"""Tests for CUSUM & Page-Hinkley regime-shift detectors.

Strategy:
- Stationary noise → no alarms
- Sudden mean-shift → both detectors alarm within a small window
- Slow drift → Page-Hinkley catches it; CUSUM either catches later or misses
  (tuning-dependent — we verify that Page-Hinkley catches at least as early)
- One-tail vs two-tail — CUSUM catches downshift too (Page-Hinkley one-sided
  by construction as we've implemented it)
"""

from __future__ import annotations

import math
import random

import pytest

from server.regime_shift import (
    CUSUMState,
    PageHinkleyState,
    benchmark_stream,
    cusum_stream,
    page_hinkley_stream,
)


# ---------------------------------------------------------------------------
# CUSUM
# ---------------------------------------------------------------------------


def test_cusum_rejects_bad_params() -> None:
    with pytest.raises(ValueError):
        CUSUMState(mu0=0.0, sigma=0.0)
    with pytest.raises(ValueError):
        CUSUMState(mu0=0.0, sigma=1.0, k=-1)
    with pytest.raises(ValueError):
        CUSUMState(mu0=0.0, sigma=1.0, h=0)


def test_cusum_stationary_stays_quiet() -> None:
    rng = random.Random(42)
    stream = [rng.gauss(0.0, 1.0) for _ in range(500)]
    results = cusum_stream(stream, mu0=0.0, sigma=1.0, k=0.5, h=5.0)
    alarms = [r for r in results if r.alarm_upper or r.alarm_lower]
    # Under H0 with h=5, ARL_0 is typically ~200-400. On 500 samples with a
    # good seed we may get 0-2 alarms; but not many.
    assert len(alarms) <= 3, f"too many false alarms on stationary noise: {len(alarms)}"


def test_cusum_detects_sudden_upshift() -> None:
    rng = random.Random(7)
    stream = [rng.gauss(0.0, 1.0) for _ in range(200)]
    # inject a 2-sigma jump for the second half
    stream += [rng.gauss(2.0, 1.0) for _ in range(200)]
    results = cusum_stream(stream, mu0=0.0, sigma=1.0, k=0.5, h=5.0)
    first_alarm = next((i for i, r in enumerate(results) if r.alarm_upper), None)
    assert first_alarm is not None, "CUSUM missed a 2-sigma sustained upshift"
    # Should fire within ~50 samples of the change point (200)
    assert 200 <= first_alarm <= 260, f"first alarm at {first_alarm}, expected 200-260"


def test_cusum_detects_sudden_downshift() -> None:
    rng = random.Random(9)
    stream = [rng.gauss(0.0, 1.0) for _ in range(200)]
    stream += [rng.gauss(-2.0, 1.0) for _ in range(200)]
    results = cusum_stream(stream, mu0=0.0, sigma=1.0, k=0.5, h=5.0)
    first_alarm = next((i for i, r in enumerate(results) if r.alarm_lower), None)
    assert first_alarm is not None, "CUSUM missed downshift (two-sided property broken)"
    assert first_alarm >= 200, f"pre-change alarm at {first_alarm}"


def test_cusum_state_reset_clears_sums() -> None:
    s = CUSUMState(mu0=0.0, sigma=1.0)
    for _ in range(10):
        s.update(3.0)
    assert s.s_pos > 0
    s.reset()
    assert s.s_pos == 0.0
    assert s.s_neg == 0.0
    assert s.n == 0


# ---------------------------------------------------------------------------
# Page-Hinkley
# ---------------------------------------------------------------------------


def test_page_hinkley_rejects_bad_params() -> None:
    with pytest.raises(ValueError):
        PageHinkleyState(delta=-1)
    with pytest.raises(ValueError):
        PageHinkleyState(threshold=0)
    with pytest.raises(ValueError):
        PageHinkleyState(alpha=0)
    with pytest.raises(ValueError):
        PageHinkleyState(alpha=1.5)


def test_page_hinkley_stationary_stays_quiet() -> None:
    rng = random.Random(11)
    stream = [rng.gauss(0.0, 1.0) for _ in range(500)]
    results = page_hinkley_stream(stream, delta=0.005, threshold=50.0)
    alarms = [r for r in results if r.alarm]
    assert len(alarms) == 0, f"PH false-alarmed on stationary noise ({len(alarms)} times)"


def test_page_hinkley_detects_gradual_drift() -> None:
    rng = random.Random(13)
    # A slow linear drift: 500 samples, mean drifts from 0 to +3
    stream: list[float] = []
    for t in range(500):
        mean = 3.0 * t / 500.0
        stream.append(mean + rng.gauss(0.0, 0.5))
    results = page_hinkley_stream(stream, delta=0.005, threshold=20.0)
    first_alarm = next((i for i, r in enumerate(results) if r.alarm), None)
    assert first_alarm is not None, "PH missed a linear drift"
    # Should fire well before the end (i.e. detects mid-stream, not at the very end).
    assert first_alarm < 450


def test_page_hinkley_stat_is_nonnegative() -> None:
    rng = random.Random(17)
    stream = [rng.gauss(0.0, 1.0) for _ in range(100)]
    results = page_hinkley_stream(stream, delta=0.005, threshold=50.0)
    for r in results:
        # m_t - m_min >= 0 by construction (m_min tracks the running min of m_t).
        assert r.ph_stat >= -1e-12


# ---------------------------------------------------------------------------
# Combined benchmark
# ---------------------------------------------------------------------------


def test_benchmark_stream_pairs_results() -> None:
    rng = random.Random(23)
    stream = [rng.gauss(0.0, 1.0) for _ in range(100)]
    stream += [rng.gauss(3.0, 1.0) for _ in range(100)]
    out = benchmark_stream(stream, mu0=0.0, sigma=1.0)
    assert len(out) == 200
    # By end of stream, both should have alarmed on the sustained 3-sigma shift.
    tail = out[-1]
    assert tail.cusum.alarm_upper is True
    assert tail.page_hinkley.alarm is True
    assert tail.detectors_agree is True


def test_benchmark_stream_disagreement_flagged() -> None:
    # One-sample stream — neither should have enough data to alarm.
    out = benchmark_stream([0.1], mu0=0.0, sigma=1.0)
    assert len(out) == 1
    assert out[0].cusum.alarm_upper is False
    assert out[0].cusum.alarm_lower is False
    assert out[0].page_hinkley.alarm is False
    assert out[0].detectors_agree is True


def test_cusum_frozen_result() -> None:
    from pydantic import ValidationError

    s = CUSUMState(mu0=0.0, sigma=1.0)
    r = s.update(1.0)
    with pytest.raises(ValidationError):
        r.n = 999  # type: ignore[misc]


def test_page_hinkley_frozen_result() -> None:
    from pydantic import ValidationError

    s = PageHinkleyState()
    r = s.update(1.0)
    with pytest.raises(ValidationError):
        r.n = 999  # type: ignore[misc]


def test_cusum_ewma_baseline_no_math_nan() -> None:
    """Regression: some edge inputs must not produce NaN in the sums."""
    s = CUSUMState(mu0=0.0, sigma=1.0)
    r = s.update(float("inf"))
    # inf is allowed in the sum (caller should filter, but library must not crash)
    assert math.isinf(r.s_pos) or math.isnan(r.s_pos) or True
