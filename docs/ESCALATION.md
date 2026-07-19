# Arbitration → VRF Panel Escalation (AE-A1.4)

`POST /arbitration/analyze` now auto-escalates certain LLM verdicts to a
VRF-elected human arbiter panel (`POST /elect` under the hood) before
returning to the caller. The response stays a flat
`ArbitrationRecommendation` — three new fields carry the escalation
outcome.

## Policy

| verdict.recommendation | verdict.confidence | Auto-escalate? |
|------------------------|--------------------|----------------|
| `favor_sender`         | any                | no             |
| `favor_receiver`       | any                | no             |
| `split`                | any                | no             |
| `escalate`             | `>= 0.30`          | no (human review path) |
| `escalate`             | `< 0.30`           | **yes** (LLM had no signal) |
| `abstain`              | any                | **yes** (LLM refused to judge) |

## Request

Two new optional fields on the existing request body:

```jsonc
{
  "dispute_id": "d123...",
  "sender_evidence": [...],
  "receiver_evidence": [...],
  "escrow_amount": 1000,

  // AE-A1.4 additions (all optional). Required only if you want the
  // response to auto-elect a panel on an abstain / low-conf-escalate
  // verdict; omit them and the verdict comes back with a machine-
  // readable escalation_reason instead.
  "sender_account":       "hex64 account hash",
  "receiver_account":     "hex64 account hash",
  "election_seed_hash":   "hex64 optional caller-supplied seed"
}
```

`sender_account` + `receiver_account` are needed because the VRF panel
must not elect either dispute party as their own arbiter. When both are
provided and the policy triggers, the endpoint calls the same election
code path as `POST /elect` with:

- `seed_hash` = caller's `election_seed_hash` if given, else
  `sha256(dispute_id + ':' + verdict.analysis_hash)` — deterministic but
  bound to a state the arbiter has already committed to.
- Party exclusion: both accounts are added to the exclusion set.

## Response

Flat `ArbitrationRecommendation` with three new fields:

```jsonc
{
  "dispute_id":          "...",
  "recommendation":      "abstain",           // unchanged
  "confidence":          0.1,                 // unchanged
  "reasoning":           "...",               // unchanged
  "risk_factors":        [...],               // unchanged
  "suggested_split_pct": 50.0,                // unchanged
  "analysis_hash":       "...",               // unchanged
  "provider":            "groq",              // unchanged

  // AE-A1.4 additions
  "escalated_to_panel": true,
  "panel_election": {                         // ElectArbiterResponse
    "dispute_id": "...",
    "elected_arbiter": {...},
    "committee": [...],
    "seed_hash": "...",
    "method": "local_csprng",
    ...
  },
  "escalation_reason": "abstain_verdict"      // machine-readable label
}
```

## `escalation_reason` values

| Reason                                  | Meaning |
|-----------------------------------------|---------|
| `null`                                  | No escalation policy match (or verdict was a normal decision). |
| `abstain_verdict`                       | Verdict was `abstain`; panel elected. |
| `low_confidence_escalate:<conf>`        | Verdict was `escalate` with confidence below 0.3; panel elected. |
| `prior_election_reused`                 | This dispute was already escalated earlier — same election surfaced (idempotent). |
| `missing_party_accounts: ...`           | Verdict warrants escalation but `sender_account`/`receiver_account` were absent. |
| `panel_election_failed_http_<code>`     | Panel election returned a non-409 HTTPException; verdict still returned. |
| `panel_election_failed:<ExceptionName>` | Panel election raised an unexpected exception; verdict still returned. |

## Guarantees

- **Never turns a 200 into a 5xx.** Any escalation failure (including
  panel-election exceptions) is recorded on `escalation_reason` and
  the flat verdict is returned with `escalated_to_panel: false`.
- **Idempotent per dispute.** Re-analysing the same `dispute_id` yields
  the same elected arbiter (via the underlying `_election_results`
  cache) and reports `prior_election_reused`.
- **Backwards compatible.** Clients that only read
  `recommendation`/`confidence` are unaffected; the three new fields
  are additive.
