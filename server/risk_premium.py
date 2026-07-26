"""Beta-Binomial risk-premium calculator for AgentEscrow402.

Empirical Bayes over agent dispute history. Given an agent's observed
(successes, disputes) count and a workspace-wide prior, we compute:

- posterior mean of the dispute probability p̂
- (1-α) credible interval on p̂ (equal-tailed, from the Beta posterior)
- a *risk premium* expressed in basis points on top of the notional
  escrow amount, driven by the posterior UCB (upper credible bound)
  rather than the mean — the escrow charges for tail risk, not average risk

Why Beta-Binomial? Disputes are Bernoulli events, sample sizes are small,
we want conjugate updates without MCMC. This is the textbook prior for
click-through, defect-rate, and credit-default modelling.

Prior:
- `alpha0`, `beta0` — pseudo-counts. Defaults picked so the prior mean =
  1% dispute rate with weight-of-evidence n=20 (i.e. alpha0=0.2, beta0=19.8).
  These are tunable via config; document in ROADMAP if changed.

Reference:
- Gelman et al., *Bayesian Data Analysis* (3rd ed.), §2.4.
- Robbins (1956), *An Empirical Bayes Approach to Statistics*.

Deps: only mpmath (already in requirements via casper-client) and Python's
`math`. No scipy — keeps the runtime image small.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_ALPHA0 = 0.2  # ~1% dispute prior
DEFAULT_BETA0 = 19.8
DEFAULT_CI_LEVEL = 0.95
# Risk-premium curve: linear in posterior UCB, capped and floored.
MIN_PREMIUM_BPS = 5  # 5 bps floor (0.05%) — covers oracle + gas overhead
MAX_PREMIUM_BPS = 2500  # 25% ceiling — anything worse and we refuse the escrow
UCB_SLOPE_BPS = 10000.0  # 1 unit of UCB ~ 100% dispute prob → 100% premium
# (i.e. UCB=0.10 → 1000 bps → clipped to MAX)


# ---------------------------------------------------------------------------
# Beta-distribution quantile via bisection on the regularized incomplete beta
# ---------------------------------------------------------------------------


def _log_beta(a: float, b: float) -> float:
    """log B(a, b) — via lgamma for numerical stability."""
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _betainc_regularized(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b) via continued fraction.

    Numerical Recipes formula (§6.4). Accurate to ~1e-10 for a,b in [1, 1000].
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    # Symmetry: I_x(a,b) = 1 - I_{1-x}(b,a). Choose the faster-converging side.
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - _betainc_regularized(b, a, 1.0 - x)

    log_bt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x)
    bt = math.exp(log_bt)

    # Continued fraction
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        del_ = d * c
        h *= del_
        if abs(del_ - 1.0) < 3e-11:
            break
    return bt * h / a


def beta_quantile(p: float, a: float, b: float, tol: float = 1e-9, max_iter: int = 200) -> float:
    """Inverse CDF of Beta(a, b) at level ``p`` via bisection on the CDF.

    Robust for a, b >= 0.1. Not the fastest method but has no dep on scipy
    and stays in-house.
    """
    if not (0.0 <= p <= 1.0):
        raise ValueError("p must be in [0, 1]")
    if a <= 0 or b <= 0:
        raise ValueError("Beta parameters must be > 0")
    if p == 0.0:
        return 0.0
    if p == 1.0:
        return 1.0

    lo, hi = 0.0, 1.0
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        cdf = _betainc_regularized(a, b, mid)
        if abs(cdf - p) < tol:
            return mid
        if cdf < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class RiskPremiumRequest(BaseModel):
    successes: int = Field(ge=0, description="Number of settled-clean escrows for this agent")
    disputes: int = Field(ge=0, description="Number of disputed escrows for this agent")
    alpha0: float = Field(default=DEFAULT_ALPHA0, gt=0)
    beta0: float = Field(default=DEFAULT_BETA0, gt=0)
    ci_level: float = Field(default=DEFAULT_CI_LEVEL, gt=0.0, lt=1.0)


class RiskPremiumResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Posterior parameters
    alpha_post: float
    beta_post: float
    posterior_mean: float
    posterior_variance: float
    # Credible interval on p (dispute probability)
    ci_level: float
    ci_lower: float
    ci_upper: float
    # Risk premium output
    premium_bps: int
    premium_ratio: float  # premium_bps / 10000
    should_refuse: bool  # true iff UCB pushes premium past MAX_PREMIUM_BPS
    explanation: str


@dataclass(frozen=True)
class BetaBinomialPosterior:
    alpha: float
    beta: float

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def variance(self) -> float:
        a, b = self.alpha, self.beta
        n = a + b
        return a * b / (n * n * (n + 1.0))

    def credible_interval(self, level: float = DEFAULT_CI_LEVEL) -> tuple[float, float]:
        tail = 0.5 * (1.0 - level)
        lo = beta_quantile(tail, self.alpha, self.beta)
        hi = beta_quantile(1.0 - tail, self.alpha, self.beta)
        return lo, hi


def compute_posterior(
    successes: int,
    disputes: int,
    alpha0: float = DEFAULT_ALPHA0,
    beta0: float = DEFAULT_BETA0,
) -> BetaBinomialPosterior:
    """Given observed (successes, disputes) and a Beta(alpha0, beta0) prior,
    the posterior is Beta(alpha0 + disputes, beta0 + successes).

    Note: we treat ``disputes`` as the "success" event in the Beta-Binomial
    conjugacy — we're modelling probability of dispute, not settle.
    """
    if successes < 0 or disputes < 0:
        raise ValueError("counts must be non-negative")
    if alpha0 <= 0 or beta0 <= 0:
        raise ValueError("prior parameters must be > 0")
    return BetaBinomialPosterior(alpha=alpha0 + disputes, beta=beta0 + successes)


def compute_premium(
    successes: int,
    disputes: int,
    alpha0: float = DEFAULT_ALPHA0,
    beta0: float = DEFAULT_BETA0,
    ci_level: float = DEFAULT_CI_LEVEL,
) -> RiskPremiumResponse:
    post = compute_posterior(successes, disputes, alpha0=alpha0, beta0=beta0)
    lo, hi = post.credible_interval(level=ci_level)

    # Premium is UCB-driven: we charge based on plausible worst-case dispute
    # rate, not average. This is the whole point of a credible interval over
    # a point estimate.
    raw_premium_bps = hi * UCB_SLOPE_BPS
    clipped = int(min(MAX_PREMIUM_BPS, max(MIN_PREMIUM_BPS, round(raw_premium_bps))))
    should_refuse = raw_premium_bps > MAX_PREMIUM_BPS

    explanation = (
        f"Beta({post.alpha:.2f}, {post.beta:.2f}) posterior after "
        f"{disputes} disputes / {successes} clean. "
        f"E[p]={post.mean:.4f}, {int(ci_level*100)}% CI=[{lo:.4f}, {hi:.4f}]. "
        f"Charging UCB-driven premium of {clipped} bps."
    )
    if should_refuse:
        explanation += " Above MAX ceiling — escrow should be refused."

    return RiskPremiumResponse(
        alpha_post=post.alpha,
        beta_post=post.beta,
        posterior_mean=post.mean,
        posterior_variance=post.variance,
        ci_level=ci_level,
        ci_lower=lo,
        ci_upper=hi,
        premium_bps=clipped,
        premium_ratio=clipped / 10000.0,
        should_refuse=should_refuse,
        explanation=explanation,
    )


def batch_compute(
    items: Iterable[RiskPremiumRequest],
) -> list[RiskPremiumResponse]:
    """Vectorized helper for batch endpoint / backtests."""
    return [
        compute_premium(
            successes=r.successes,
            disputes=r.disputes,
            alpha0=r.alpha0,
            beta0=r.beta0,
            ci_level=r.ci_level,
        )
        for r in items
    ]
