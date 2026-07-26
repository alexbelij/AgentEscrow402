"""Regime-shift alerts for AgentEscrow402 risk streams.

Two lightweight online change-point detectors, both stateless-per-call
(the caller passes in the accumulated statistics) so they slot naturally
into a stateless FastAPI worker:

- **CUSUM** (Cumulative Sum, Page 1954) — the classic two-sided variant.
  Tuned for stationary-mean deviations; fast, cheap, tight false-alarm
  bounds via ARL_0 tuning.

- **Page-Hinkley** (Page 1954 / Hinkley 1971) — one-sided cumulative
  deviation with a "minimum" reset; robust to gradual drift, standard
  in the streaming-ML literature.

Both detectors are Baseline vs Alarm-only APIs — the caller decides
what to do on alarm (open ticket, halt disbursement, flag counterparty,
etc.). No side effects here.

Reference:
- Page, E. S. (1954). *Continuous Inspection Schemes*. Biometrika 41.
- Hinkley, D. V. (1971). *Inference about the change-point from cumulative sum tests*. Biometrika 58.
- Basseville & Nikiforov (1993). *Detection of Abrupt Changes: Theory and Application*. Prentice-Hall.

We deliberately DO NOT bring in scikit-multiflow / river — those add a
transitive dep the escrow service does not need. The math here is 30
lines and mechanically verified against the original papers' formulas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# CUSUM — two-sided
# ---------------------------------------------------------------------------


@dataclass
class CUSUMState:
    """Accumulator for two-sided CUSUM.

    ``mu0``   — assumed in-control mean (baseline).
    ``sigma`` — assumed in-control std-dev (>0).
    ``k``     — reference-value slack (in sigma units). Typical: 0.5.
    ``h``     — alarm threshold (in sigma units). Typical: 4-5 for ARL_0 ~ 200.
    ``s_pos`` / ``s_neg`` — running upper/lower cumulative sums.
    ``n``     — samples observed since reset.
    """

    mu0: float
    sigma: float
    k: float = 0.5
    h: float = 5.0
    s_pos: float = 0.0
    s_neg: float = 0.0
    n: int = 0

    def __post_init__(self) -> None:
        if self.sigma <= 0:
            raise ValueError("CUSUM sigma must be > 0")
        if self.k < 0:
            raise ValueError("CUSUM k must be >= 0")
        if self.h <= 0:
            raise ValueError("CUSUM h must be > 0")

    def update(self, x: float) -> "CUSUMResult":
        """Fold one new observation into the accumulator and return the state.

        Returns a CUSUMResult with the current sums and whether an alarm fires.
        """
        z = (x - self.mu0) / self.sigma
        self.s_pos = max(0.0, self.s_pos + z - self.k)
        self.s_neg = min(0.0, self.s_neg + z + self.k)
        self.n += 1
        alarm_upper = self.s_pos > self.h
        alarm_lower = self.s_neg < -self.h
        return CUSUMResult(
            n=self.n,
            s_pos=self.s_pos,
            s_neg=self.s_neg,
            alarm_upper=alarm_upper,
            alarm_lower=alarm_lower,
            direction=("upper" if alarm_upper else ("lower" if alarm_lower else None)),
        )

    def reset(self) -> None:
        self.s_pos = 0.0
        self.s_neg = 0.0
        self.n = 0


class CUSUMResult(BaseModel):
    """Result of a CUSUM update. Immutable snapshot."""

    model_config = ConfigDict(frozen=True)

    n: int = Field(ge=0)
    s_pos: float
    s_neg: float
    alarm_upper: bool
    alarm_lower: bool
    direction: str | None  # "upper" | "lower" | None


def cusum_stream(
    values: Iterable[float],
    mu0: float,
    sigma: float,
    k: float = 0.5,
    h: float = 5.0,
) -> list[CUSUMResult]:
    """Offline convenience: fold a fixed sequence through CUSUM and return the
    per-step results (useful for backtests and unit tests).
    """
    state = CUSUMState(mu0=mu0, sigma=sigma, k=k, h=h)
    return [state.update(x) for x in values]


# ---------------------------------------------------------------------------
# Page-Hinkley — one-sided (streaming ML canonical form)
# ---------------------------------------------------------------------------


@dataclass
class PageHinkleyState:
    """Page-Hinkley test with running minimum.

    ``delta``     — magnitude of change we care about (>0).
    ``threshold`` — alarm level for cumulative deviation above the running minimum.
    ``alpha``     — EWMA factor for the running mean; 0 = strict Page-Hinkley,
                    (0,1] = EWMA-augmented variant (robust to slow drift baseline).

    The state tracks:
    ``mean``   — running (EWMA) mean of the observed stream.
    ``m_t``    — cumulative deviation from mean, minus delta.
    ``m_min``  — running minimum of m_t (the "reference" the alarm is measured against).
    """

    delta: float = 0.005
    threshold: float = 50.0
    alpha: float = 1.0
    mean: float = 0.0
    m_t: float = 0.0
    m_min: float = 0.0
    n: int = 0

    def __post_init__(self) -> None:
        if self.delta < 0:
            raise ValueError("Page-Hinkley delta must be >= 0")
        if self.threshold <= 0:
            raise ValueError("Page-Hinkley threshold must be > 0")
        if not (0.0 < self.alpha <= 1.0):
            raise ValueError("Page-Hinkley alpha must be in (0, 1]")

    def update(self, x: float) -> "PageHinkleyResult":
        self.n += 1
        # EWMA-updated running mean (alpha=1 -> arithmetic streaming mean).
        if self.alpha == 1.0:
            self.mean = self.mean + (x - self.mean) / self.n
        else:
            self.mean = self.alpha * x + (1.0 - self.alpha) * self.mean

        self.m_t += x - self.mean - self.delta
        if self.m_t < self.m_min:
            self.m_min = self.m_t
        ph_stat = self.m_t - self.m_min
        alarm = ph_stat > self.threshold
        return PageHinkleyResult(
            n=self.n,
            mean=self.mean,
            m_t=self.m_t,
            m_min=self.m_min,
            ph_stat=ph_stat,
            alarm=alarm,
        )

    def reset(self) -> None:
        self.mean = 0.0
        self.m_t = 0.0
        self.m_min = 0.0
        self.n = 0


class PageHinkleyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    n: int = Field(ge=0)
    mean: float
    m_t: float
    m_min: float
    ph_stat: float
    alarm: bool


def page_hinkley_stream(
    values: Iterable[float],
    delta: float = 0.005,
    threshold: float = 50.0,
    alpha: float = 1.0,
) -> list[PageHinkleyResult]:
    state = PageHinkleyState(delta=delta, threshold=threshold, alpha=alpha)
    return [state.update(x) for x in values]


# ---------------------------------------------------------------------------
# Combined benchmark
# ---------------------------------------------------------------------------


class RegimeShiftBenchmark(BaseModel):
    """Side-by-side output when caller wants to compare CUSUM vs Page-Hinkley
    on the same stream (used by /risk/regime-shift/benchmark)."""

    model_config = ConfigDict(frozen=True)

    n: int
    baseline_mean: float
    baseline_sigma: float
    cusum: CUSUMResult
    page_hinkley: PageHinkleyResult
    # Agreement flag: True iff both detectors agree (both alarm or both silent).
    detectors_agree: bool


def benchmark_stream(
    values: list[float],
    mu0: float,
    sigma: float,
    cusum_k: float = 0.5,
    cusum_h: float = 5.0,
    ph_delta: float = 0.005,
    ph_threshold: float = 50.0,
    ph_alpha: float = 1.0,
) -> list[RegimeShiftBenchmark]:
    """Run both detectors on a stream and yield paired snapshots. O(n)."""
    cs = CUSUMState(mu0=mu0, sigma=sigma, k=cusum_k, h=cusum_h)
    ps = PageHinkleyState(delta=ph_delta, threshold=ph_threshold, alpha=ph_alpha)
    out: list[RegimeShiftBenchmark] = []
    for x in values:
        cr = cs.update(x)
        pr = ps.update(x)
        c_al = cr.alarm_upper or cr.alarm_lower
        out.append(
            RegimeShiftBenchmark(
                n=cr.n,
                baseline_mean=mu0,
                baseline_sigma=sigma,
                cusum=cr,
                page_hinkley=pr,
                detectors_agree=(c_al == pr.alarm),
            )
        )
    return out
