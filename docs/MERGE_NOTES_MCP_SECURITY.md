# T27 — MCP Server Sanity & Security — Merge Notes

**Branch**: `feat/ae402-mcp-server-security`
**Scope**: **test-only**, no production code changes, no Render/infra changes.
**Merge order**: independent of the four other open PRs (SigNoz OTEL, arbiter-signing E2E, formal verification, VRF E2E). Any merge order works — file paths do not intersect.

---

## Why this exists

`sdk/mcp_server.py` exposes ~26 MCP tools to any MCP-compatible LLM
(Claude Desktop, Cursor, custom agents). This is a **direct external attack
surface**:

1. An LLM will happily pass through user-supplied strings as tool arguments.
2. Prompt-injection can smuggle malformed values that the LLM then hands
   to the MCP layer verbatim.
3. Error messages returned by MCP tools are read back by the LLM and can
   become instructions in a compromised transcript.

Before this PR: **zero tests** on the MCP layer. All ~26 tools relied on
integration-level backend tests to catch regressions — the MCP layer itself
(validators, size caps, URL construction, error envelope) was uncovered.

## What this locks (9 buckets, 101 test cases)

### Bucket A — schema & tool-registry sanity (6 tests)

- Tool count, unique names, snake_case pattern.
- `inputSchema` is a valid JSON-Schema object.
- Every `required` field is declared in `properties`.
- **`test_enum_declarations_declared_correctly`** freezes the set of
  declared `enum` surfaces (`list_escrows.status`,
  `submit_dispute_arbitration.category`). Adding a new enum without a
  matching handler validator now breaks this test on purpose.

### Bucket B — validator-level injection resistance (~40 tests)

Parametrised suites for `_validate_id`, `_validate_hash`, `_validate_amount`,
`_validate_limit`, `_safe_path`:

- Path traversal (`../../etc/passwd`)
- URL-separator injection (`/`, `?`, `#`, `&`, `=`, `+`)
- Newline / CR injection (`\n`, `\r`) — SMTP-style header injection surface
- NUL byte, whitespace-only
- SQL-injection shape, HTML/JS shape, unicode/emoji
- Off-by-one at length boundaries (63/64/65 for hashes, 128 for ids)
- `0x` prefix common LLM-mistake for hashes
- Whitespace-trim behaviour documented
- Uppercase → lowercase for hashes documented

### Bucket C — handle_tool injection (9 tests)

`handle_tool` is exercised with a monkey-patched `httpx.AsyncClient`;
malformed args must be refused **before any HTTP round-trip**:

- Bad sender in `create_escrow` → refused, zero HTTP calls
- Over-max amount → refused, zero HTTP calls
- Path traversal in `get_identity` → refused, zero HTTP calls
- TTL clamped in both directions before being POSTed
- Bad hash / bad reason_hash → refused, zero HTTP calls
- Well-formed hash → URL-encoded correctly into path

The **no-network guarantee** matters: if validation is accidentally moved
after the HTTP call, an attacker can amplify traffic into the backend via
the MCP layer.

### Bucket D — size / DoS caps (7 tests)

- `evidence_sender`/`evidence_receiver` truncated at 10 000 chars (was
  already in the code — now locked by test).
- `new_evidence` on appeals truncated at 10 000 chars.
- `public_key` truncated at 256 chars.
- `batch_release` / `batch_cancel`: one bad hash **poisons the whole
  pre-flight** — zero HTTP calls made.
- `list_escrows.limit` and `get_events.limit` clamped to `MAX_LIMIT`.

### Bucket E — error envelope discipline (5 tests)

Every error path must return the documented `{"error": "..."}` shape
without leaking backend URLs or stack traces:

- `HTTPStatusError` (500 from backend) → `{"error": "API request failed"}`,
  and the backend URL is **not** echoed back.
- `RequestError` (connection failure) → `{"error": "API connection error"}`,
  URL not echoed.
- Unknown tool → informational error, no HTTP call.
- Missing required arg → error, no HTTP call.
- Validation error path never reflects the target URL.

### Bucket F — positive-path wiring (10 tests)

One happy path per underexercised tool to prove URL/method/body/params
are correct. Regressions here mean an LLM would **misroute live money**:

- `release` / `refund` / `dispute` hit the right endpoints with the right
  bodies.
- `estimate_fee`, `health_check`, `get_stats`, `list_agents` — GET-only,
  no body.
- `elect_arbiter` body shape.
- `batch_release` body shape and query params.
- `claim_stream` URL-encodes the hash into the path.

### Bucket G — deterministic hash & x402 header (3 tests)

- `_hash(sender, receiver, amount, nonce)` is deterministic and 64-hex.
- Changing any input changes the hash.
- `build_x402_header` returns a 6-field `x402;version;amount;sh;ts;nonce`
  header, matches the returned `service_hash` and `nonce`, and **makes
  no HTTP call** (client-side helper).

### Bucket H — server wiring (2 tests)

- `build_server(api_url)` runs and returns a `Server`-like object.
- `SHA256_RE` is case-sensitive lowercased (matching the validator's
  lowercase behaviour); `ID_RE` rejects whitespace.

### Bucket I — documented gaps (2 tests, non-strict)

Two **real behaviour gaps** are documented as passing-today tests:

1. `list_escrows.status="banana"` is passed through to the backend even
   though the tool's `inputSchema` declares an enum of
   `[active|completed|disputed|expired]`.
2. `submit_dispute_arbitration.category="not_a_real_category"` is passed
   through even though the schema declares an enum.

**These are not strict assertions** — they document what the handler does
today so a follow-up PR to enforce the enums will have to flip these two
tests from "accepts" to "rejects with `Validation error`". That is the
canonical way to force the fix into a subsequent PR without silently
tightening behaviour here.

## Findings surfaced by the suite (not fixed here)

Enumerated so the follow-up PR knows what to close:

1. **Enum non-enforcement** (see Bucket I above) — 2 fields.
2. **`--transport sse` binds to `host="0.0.0.0"`** (all interfaces) —
   noted for the SSE runbook; not a code change here because the correct
   mitigation is deployment-level (reverse proxy / firewall), not a
   default-safe host bind.
3. **No idempotency-key surface on write tools** — an LLM can double-click
   `create_escrow`, `release_escrow`, `dispute_escrow`. Should be enforced
   at the API layer (which does have some replay guard) but the MCP layer
   could pass through an `Idempotency-Key` header. Deferred.
4. **`ValueError` messages reflect a small amount of attacker payload**
   (e.g. `int("PAYLOAD")` raises `"invalid literal for int() ..."` with
   `PAYLOAD` visible). Bucket E asserts this leak is bounded to Python's
   built-in exception messages and never contains a backend URL, so the
   surface is acceptable but noted.

## Verification (self)

```
cd /data/AgentEscrow402
python -m pytest tests/test_mcp_server_security.py -q          # 101 passed
python -m pytest tests/ -q                                      # 693 passed
```

Baseline before this PR: **592 tests** on `main`.
+5 from `feat/ae402-vrf-selection-e2e` (T26, independent PR).
+101 from this PR.
`693 == 592 + 101` (the 5 T26 tests live on their own branch, not on `main`
yet, so the two counters commute).

Zero regressions. Suite runs in ~1.4 s in isolation.

## Merge instructions for the merge-agent

1. **Confirm the branch is fast-forward from `main`** — no rebase required
   because the file is net-new.
2. **`git merge --no-ff feat/ae402-mcp-server-security`** into `main`.
3. **Do not touch Render**. This PR adds:
   - `tests/test_mcp_server_security.py`
   - `docs/MERGE_NOTES_MCP_SECURITY.md`
   No prod code, no config, no infra. `render.yaml` is unchanged.
4. **Post-merge check**: `python -m pytest tests/ -q` should show at least
   693 passing (may be higher once the other four PRs land).

## Files changed

- `tests/test_mcp_server_security.py` (+750 lines net-new)
- `docs/MERGE_NOTES_MCP_SECURITY.md` (this file)

Total: +2 files, ~+900 LOC (docs + tests).

## Follow-up ticket suggestions

- **T27a** — enforce declared enums in `handle_tool` for `list_escrows.status`
  and `submit_dispute_arbitration.category`; flip Bucket I tests from
  "accepts today" to "rejects with Validation error".
- **T27b** — default `--transport sse` to `127.0.0.1`, add explicit
  `--bind` flag for operators who want `0.0.0.0`.
- **T27c** — add `Idempotency-Key` pass-through header on the four write
  tools (`create_escrow`, `release_escrow`, `refund_escrow`,
  `dispute_escrow`).
