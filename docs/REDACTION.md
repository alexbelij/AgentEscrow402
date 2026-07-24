# AE402 — Redaction contract

## Threat model

Escrow dispute evidence (`DisputeEvidence.description`) is arbitrary
user-submitted text. Real-world claimants routinely paste:

- personal email addresses (`quentin@adspower.com`)
- phone numbers (`+1 (555) 123-4567`)
- accidentally-copied API keys / bearer tokens / JWTs
- credit-card-like digit strings

At the same time, arbitration reasoning returned by the LLM often echoes
those descriptions verbatim, and the console reads that reasoning back via
`GET /arbitration/history`.

Without a redaction layer, any of the following would leak PII / secrets to
an unauthenticated caller:

| Surface | Reads | Risk |
|---|---|---|
| `GET /arbitration/history` | `reasoning`, `risk_factors` | LLM re-emits raw description |
| Server log files | prompt (if debug-logged) | full evidence body written to disk |
| `analysis_hash` recompute | evidence content | not a leak, but must be verifiable |

## Module

Everything lives in `server/redaction.py`. Three public entry points:

### `hash_content(content, *, prefix="sha256", chars=12) -> str`

Deterministic short hash for arbitrary content. Format: `sha256:xxxxxxxxxxxx`.
Safe for public exposure — identifies content for third-party verification
without leaking it.

```python
>>> hash_content("hello world")
'sha256:b94d27b9934d'
```

### `redact_text(text, *, max_len=300) -> str`

Substitute known PII / secret patterns with hash-referenced tokens. Idempotent
(double-application is a no-op).

Patterns matched (in order — specific → generic):

| Pattern | Replacement token |
|---|---|
| `-----BEGIN…PRIVATE KEY-----` … `-----END…-----` PEM block | `<secret:sha256:xxxx>` |
| `Bearer <token>` / `api_key=<token>` / `token=<token>` | `<secret:sha256:xxxx>` |
| JWT (`eyJ…….…….`) | `<secret:sha256:xxxx>` |
| Prefixed keys (`sk-…`, `pk-…`, `AKIA…`, `xoxb-…`, `ghp-…`, `glpat-…`) | `<secret:sha256:xxxx>` |
| Long mixed-case base64 blob (40+ chars, incl. session cookies) | `<secret:sha256:xxxx>` |
| Email (RFC 5321 loose) | `<email:sha256:xxxx>` |
| Credit-card-like (13-19 digits) | `<cc:sha256:xxxx>` |
| Phone (10+ digits with separators; bare digit runs are treated as ids, not phones) | `<phone:sha256:xxxx>` |

Explicitly NOT redacted (public references, needed for the audit chain):

- Casper account keys (65-hex, `01`/`02` prefix)
- Escrow / dispute / block ids that are opaque hex or digit strings without separators
- `sha256:xxxx` hashes that redaction itself produces (idempotency)

Output is capped at `max_len` characters (truncated with `…`).

### `redact_evidence(evidence) -> dict`

Redact a single `DisputeEvidence` (pydantic model or plain dict) for public
trace exposure. Keeps the on-chain-visible fields (`escrow_id`, `claimant`,
`evidence_type`, `content_hash`, `timestamp`) and adds:

- `description`: `redact_text(raw, max_len=240)`
- `description_hash`: `hash_content(raw)` — a third party with the original
  can verify the hash matches.

### `redact_prompt_for_log(prompt) -> str`

Collapses an LLM arbitration prompt to metadata only:
`prompt.sha256=xxxxxxxxxxxx len=N`. Output is guaranteed < 200 chars, safe
for any log line.

## Integration points

Current call sites (2026-07-19):

- `server/ai_arbitration.py::ArbitrationAgent.analyze_dispute`
  - `reasoning` field of `ArbitrationRecommendation` is passed through
    `redact_text(..., max_len=300)` before storage & return.
  - Debug-level prompt log uses `redact_prompt_for_log`.

Not yet integrated (roadmap):

- `POST /arbitration/analyze` request path — currently the API accepts raw
  `description` in the request body and forwards to the LLM verbatim. This is
  intentional (the LLM needs the raw text to reason), but any *future* echo
  of the request body back in a response payload must call `redact_evidence`
  first.

## Verification

- Unit tests: `tests/test_redaction.py` (27 tests) — patterns, idempotency,
  hash-stability, hostile-input integration blob, PEM/base64 regression,
  Casper-key preservation, fixed-point on all patterns.
- Full suite: `python3 -m pytest tests/ -q --ignore=tests/property` → 477/477
  pass (2026-07-19).

## Guarantees

1. **Determinism.** Same input → same hash. Audit trails computed with
   `hash_content` remain stable across process restarts.
2. **Hash-preserving.** Every redaction token includes a `sha256:xxxx…`
   suffix, so a claimant with the original text can prove `hash == this`
   without the arbiter re-exposing the raw text.
3. **Idempotency.** `redact_text(redact_text(x)) == redact_text(x)`. Safe to
   compose or double-apply.
4. **Conservative.** When a pattern is ambiguous, we redact. False-positive
   redactions are acceptable (a legitimate phone-shaped id in evidence still
   gets hashed); false-negatives (a real key surviving) are not.

## What we do NOT redact

- Casper account keys (`01aaaa…` / `02aaaa…`) and escrow / contract hashes.
  These are on-chain public identifiers by design and callers (frontend,
  block explorer links, `content_hash`) depend on them being intact.
- Numeric amounts (`escrow_amount`, `confidence`, `suggested_split_pct`).
- Structural fields (`recommendation`, `risk_factors`) — those are enums.
