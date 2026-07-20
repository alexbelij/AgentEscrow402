# Risk analytics — regime-shift detection & Beta-Binomial pricing

Two lightweight online-learning primitives that live alongside the existing
IsolationForest anomaly scorer (`server/risk_scoring.py`).

## 1. Regime-shift detection

Two change-point detectors, both stateless-per-call so they slot naturally
into a stateless FastAPI worker.

### CUSUM (Cumulative Sum, Page 1954)

Classic two-sided variant. Tuned via `k` (slack in σ units) and `h` (alarm
threshold in σ units). Typical `k=0.5, h=5` → ARL₀ ≈ 200 under H₀.

Fires when the cumulative deviation from the assumed mean exceeds `h·σ`. Cheap,
tight false-alarm bounds, dead-simple ops story.

### Page-Hinkley (Page 1954, Hinkley 1971)

One-sided cumulative deviation with a running "minimum" reset. Standard in the
streaming-ML literature. Tuned via `delta` (magnitude of change we care about),
`threshold` (alarm level), and `alpha` (EWMA factor for the running mean).

Robust to gradual drift where CUSUM lags — great for slow trends in dispute
rate, oracle latency, or off-chain throughput.

### Endpoints

- `POST /risk/regime-shift/cusum` — run CUSUM over a stream, return per-step
  results + first-alarm index.
- `POST /risk/regime-shift/page-hinkley` — same, for Page-Hinkley.
- `POST /risk/regime-shift/benchmark` — side-by-side snapshot: which detector
  fired first, agreement ratio, full trajectory. Feed this to your operator
  dashboard.

Request shape (all three):

```json
{
  "values": [0.02, 0.03, 0.02, 0.15, 0.18, ...],
  "mu0": 0.02,
  "sigma": 0.01,
  "cusum_k": 0.5,
  "cusum_h": 5.0,
  "ph_delta": 0.005,
  "ph_threshold": 50.0,
  "ph_alpha": 1.0
}
```

Limits: max 10 000 samples per call (`HTTP 413` otherwise).

### When to use which

| Signal shape                          | Prefer          |
| ------------------------------------- | --------------- |
| Sudden mean shift (2σ+, sustained)    | CUSUM           |
| Slow linear drift                     | Page-Hinkley    |
| Bursty spikes (want two-sided alarms) | CUSUM           |
| Baseline unknown, EWMA-tracked        | Page-Hinkley (`alpha < 1`) |

In doubt: `/risk/regime-shift/benchmark` — run both, watch the agreement
ratio. High agreement → either works; disagreement → look at the trajectory
plot and pick the one that catches your specific attack shape earliest.

## 2. Beta-Binomial risk premium

Empirical-Bayes premium calculator. Given an agent's observed
`(successes, disputes)` and a workspace-wide prior, we compute the posterior
`Beta(α₀ + disputes, β₀ + successes)` and charge a **UCB-driven** premium
(basis points) — not the mean, the upper credible bound. Escrow prices tail
risk, not average risk.

### Prior tuning

Defaults: `α₀ = 0.2, β₀ = 19.8` — prior mean ≈ 1% dispute rate, weight-of-
evidence n=20. Change via request body if you have a stronger workspace-wide
prior; document changes in `ROADMAP.md`.

### Endpoint

- `POST /risk/premium` — single agent
- `POST /risk/premium/batch` — batched (up to 500 items)

Request shape:

```json
{ "successes": 100, "disputes": 3 }
```

Response:

```json
{
  "alpha_post": 3.2,
  "beta_post": 116.8,
  "posterior_mean": 0.0267,
  "posterior_variance": 0.0002,
  "ci_level": 0.95,
  "ci_lower": 0.0057,
  "ci_upper": 0.0668,
  "premium_bps": 668,
  "premium_ratio": 0.0668,
  "should_refuse": false,
  "explanation": "Beta(3.20, 116.80) posterior after 3 disputes / 100 clean. E[p]=0.0267, 95% CI=[0.0057, 0.0668]. Charging UCB-driven premium of 668 bps."
}
```

### Ceilings

- `MIN_PREMIUM_BPS = 5` — floor covers oracle + gas overhead
- `MAX_PREMIUM_BPS = 2500` — 25% ceiling; above this, `should_refuse = true`
  and the escrow declines the counterparty entirely

### No scipy dependency

The Beta-quantile is implemented via the Numerical Recipes continued-fraction
regularized incomplete beta — no `scipy` in the runtime image. Precision:
matches `scipy.stats.beta.ppf` to ~1e-6 for `α, β ∈ [0.1, 1000]`.

## Testing

```
python -m pytest tests/test_regime_shift.py tests/test_risk_premium.py tests/test_risk_analytics_api.py -q
```

49 tests, all passing. Backtests included: sudden shifts (2σ and 3σ),
gradual drift, unicode-safe, ceiling clipping, monotonicity in dispute count.
