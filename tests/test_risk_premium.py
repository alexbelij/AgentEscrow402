"""Tests for Beta-Binomial risk-premium calculator."""

from __future__ import annotations

import pytest

from server.risk_premium import (
    DEFAULT_ALPHA0,
    DEFAULT_BETA0,
    MAX_PREMIUM_BPS,
    MIN_PREMIUM_BPS,
    RiskPremiumRequest,
    batch_compute,
    beta_quantile,
    compute_posterior,
    compute_premium,
)

# ---------------------------------------------------------------------------
# Beta quantile
# ---------------------------------------------------------------------------


def test_beta_quantile_median_known_values() -> None:
    # Beta(1, 1) is uniform → median = 0.5
    assert abs(beta_quantile(0.5, 1.0, 1.0) - 0.5) < 1e-6


def test_beta_quantile_symmetry() -> None:
    # Beta(2, 2) is symmetric around 0.5
    lo = beta_quantile(0.025, 2.0, 2.0)
    hi = beta_quantile(0.975, 2.0, 2.0)
    assert abs((lo + hi) - 1.0) < 1e-4, f"symmetry broken: {lo} + {hi} != 1"


def test_beta_quantile_extremes() -> None:
    assert beta_quantile(0.0, 1.0, 1.0) == 0.0
    assert beta_quantile(1.0, 1.0, 1.0) == 1.0


def test_beta_quantile_monotone() -> None:
    prev = -1.0
    for p in [0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99]:
        q = beta_quantile(p, 3.0, 7.0)
        assert q > prev, f"non-monotonic quantile at p={p}"
        prev = q


def test_beta_quantile_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        beta_quantile(-0.1, 1.0, 1.0)
    with pytest.raises(ValueError):
        beta_quantile(0.5, 0.0, 1.0)
    with pytest.raises(ValueError):
        beta_quantile(0.5, 1.0, -1.0)


# ---------------------------------------------------------------------------
# Conjugate posterior
# ---------------------------------------------------------------------------


def test_posterior_conjugate_update() -> None:
    # Prior Beta(0.2, 19.8) + observe 3 disputes / 97 clean
    # → Beta(0.2 + 3, 19.8 + 97) = Beta(3.2, 116.8)
    post = compute_posterior(successes=97, disputes=3)
    assert abs(post.alpha - 3.2) < 1e-9
    assert abs(post.beta - 116.8) < 1e-9
    # Posterior mean = 3.2 / 120 ~ 0.02667
    assert abs(post.mean - (3.2 / 120.0)) < 1e-9


def test_posterior_zero_observations_returns_prior() -> None:
    post = compute_posterior(successes=0, disputes=0)
    assert post.alpha == DEFAULT_ALPHA0
    assert post.beta == DEFAULT_BETA0
    # Prior mean ~ 1%
    assert abs(post.mean - (DEFAULT_ALPHA0 / (DEFAULT_ALPHA0 + DEFAULT_BETA0))) < 1e-9


def test_posterior_rejects_negative_counts() -> None:
    with pytest.raises(ValueError):
        compute_posterior(successes=-1, disputes=0)
    with pytest.raises(ValueError):
        compute_posterior(successes=0, disputes=-1)


def test_posterior_credible_interval_contains_mean() -> None:
    post = compute_posterior(successes=97, disputes=3)
    lo, hi = post.credible_interval(level=0.95)
    assert lo < post.mean < hi
    # Width should be modest given 100 observations
    assert (hi - lo) < 0.1


# ---------------------------------------------------------------------------
# Premium
# ---------------------------------------------------------------------------


def test_premium_zero_history_returns_prior_driven_low_premium() -> None:
    resp = compute_premium(successes=0, disputes=0)
    # With prior Beta(0.2, 19.8), UCB at 95% is roughly ~0.10-0.15.
    # UCB_SLOPE_BPS=10000 → raw ~ 1000-1500 bps → clipped MAX=2500. Should NOT refuse.
    assert MIN_PREMIUM_BPS <= resp.premium_bps <= MAX_PREMIUM_BPS
    assert resp.should_refuse is False


def test_premium_clean_history_lower_than_disputed_history() -> None:
    clean = compute_premium(successes=100, disputes=0)
    disputed = compute_premium(successes=100, disputes=20)
    assert clean.premium_bps < disputed.premium_bps
    assert clean.ci_upper < disputed.ci_upper


def test_premium_extreme_disputes_hits_ceiling() -> None:
    # 90 disputes / 10 clean — UCB will be near 1.0 → raw premium >> MAX_PREMIUM_BPS
    resp = compute_premium(successes=10, disputes=90)
    assert resp.premium_bps == MAX_PREMIUM_BPS
    assert resp.should_refuse is True


def test_premium_no_data_never_below_floor() -> None:
    # Even with impossibly good prior tuning, premium must not dip below floor.
    resp = compute_premium(successes=1000, disputes=0, alpha0=0.001, beta0=100.0)
    assert resp.premium_bps >= MIN_PREMIUM_BPS


def test_premium_ratio_matches_bps() -> None:
    resp = compute_premium(successes=50, disputes=5)
    assert abs(resp.premium_ratio - resp.premium_bps / 10000.0) < 1e-12


def test_premium_explanation_mentions_ci() -> None:
    resp = compute_premium(successes=100, disputes=3)
    assert "CI" in resp.explanation
    assert "bps" in resp.explanation


def test_premium_ci_level_affects_width() -> None:
    resp90 = compute_premium(successes=100, disputes=3, ci_level=0.90)
    resp99 = compute_premium(successes=100, disputes=3, ci_level=0.99)
    # 99% CI is wider → higher upper → higher premium.
    assert resp99.ci_upper > resp90.ci_upper
    assert resp99.premium_bps >= resp90.premium_bps


# ---------------------------------------------------------------------------
# Batch API
# ---------------------------------------------------------------------------


def test_batch_compute_preserves_order() -> None:
    reqs = [
        RiskPremiumRequest(successes=100, disputes=0),
        RiskPremiumRequest(successes=100, disputes=5),
        RiskPremiumRequest(successes=100, disputes=20),
    ]
    out = batch_compute(reqs)
    assert len(out) == 3
    # Monotonic in disputes
    assert out[0].premium_bps <= out[1].premium_bps <= out[2].premium_bps


def test_batch_empty_returns_empty() -> None:
    assert batch_compute([]) == []


# ---------------------------------------------------------------------------
# Numeric sanity — spot-checks against R/scipy analytic values
# ---------------------------------------------------------------------------


def test_beta_quantile_matches_reference_2_5_pct_beta_10_10() -> None:
    # scipy.stats.beta.ppf(0.025, 10, 10) ~= 0.28925
    q = beta_quantile(0.025, 10.0, 10.0)
    assert abs(q - 0.28925) < 5e-3


def test_beta_quantile_matches_reference_97_5_pct_beta_2_20() -> None:
    # High-precision reference (Numerical Recipes betainc CF, 500 iters,
    # matches scipy.stats.beta.ppf to 1e-6): beta.ppf(0.975, 2, 20) ~= 0.23816
    q = beta_quantile(0.975, 2.0, 20.0)
    assert abs(q - 0.23816) < 5e-3
