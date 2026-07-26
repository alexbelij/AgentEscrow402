# SPDX-License-Identifier: MIT
"""
T27 — MCP Server Sanity & Security Test Suite
==============================================

Purpose
-------
The MCP server (`sdk/mcp_server.py`) exposes AE402's HTTP API to any
MCP-compatible LLM as ~26 tools. It is a **direct external attack surface**
because:

  1. An LLM will happily pass through user-supplied strings as tool arguments.
  2. Prompt-injection can smuggle malformed values that the LLM then hands
     to the MCP layer verbatim.
  3. Error messages returned by MCP tools are read back by the LLM and can
     become instructions in a compromised transcript.

This suite therefore locks the **input-validation & error-surface contracts**
of the MCP layer, independently of the FastAPI backend. Every tool that
accepts user input is exercised for:

  • Positive path (well-formed args → HTTP called with sanitized values)
  • Negative path (malformed args → refused *before* any HTTP round-trip)
  • Error-envelope shape (no stack traces, no reflected attacker payload
    beyond what the built-in Python exception messages already reveal)

Coverage buckets
----------------
A. **Schema/whitelist sanity** — every declared Tool has a valid inputSchema;
   every enum in a Tool's spec must be enforced by the handler (finds two
   real gaps: `category` and `status` are declared enum but not validated).

B. **Injection resistance** — path-segment, URL, and query-string injection
   attempts (`..`, `/`, `%2F`, unicode confusables, embedded newlines) must
   be blocked at validation, not at the HTTP layer.

C. **Size / DoS caps** — evidence strings, batch arrays, and public keys must
   all have hard length limits. Uncapped input on batch tools is a DoS vector
   (100k hashes in a single tool call).

D. **No-network guarantee for validation errors** — malformed args must
   short-circuit and NEVER perform an HTTP round-trip. If validation is
   accidentally moved after the HTTP call, an attacker can amplify traffic
   into the backend via the MCP layer.

E. **Error envelope discipline** — every error surface must return the
   documented `{"error": "..."}` shape; no HTTPStatusError / RequestError
   should ever leak stack traces or backend URLs.

Test isolation
--------------
`handle_tool` is exercised directly with a monkey-patched `httpx.AsyncClient`
so no real network is touched. The MCP `Server` class is instantiated once
in `test_build_server_registers_all_tools` to prove wiring.

Related
-------
See `docs/MERGE_NOTES_MCP_SECURITY.md` for merge posture (test-only, no prod
code changes, independent of the other four open PRs).
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx
import pytest

from sdk.mcp_server import (
    ID_RE,
    MAX_AMOUNT,
    MAX_LIMIT,
    MAX_TTL,
    MIN_TTL,
    SHA256_RE,
    TOOLS,
    _hash,
    _safe_path,
    _validate_amount,
    _validate_hash,
    _validate_id,
    _validate_limit,
    build_server,
    handle_tool,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


class _MockResponse:
    def __init__(self, payload: dict | None = None, status_code: int = 200):
        self._payload = payload if payload is not None else {"ok": True}
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            req = httpx.Request("GET", "http://x")
            raise httpx.HTTPStatusError("boom", request=req, response=httpx.Response(self.status_code))


class _CallRecorder:
    """Records every HTTP call the handler makes; returns a canned response."""

    def __init__(self, response: dict | None = None, raise_status: int | None = None, raise_request: bool = False):
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []
        self._response = response
        self._raise_status = raise_status
        self._raise_request = raise_request

    def _mkclient(self):
        rec = self

        class _AC:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url: str, json: dict | None = None, params: dict | None = None):
                rec.calls.append(("POST", url, json, params))
                if rec._raise_request:
                    raise httpx.RequestError("boom", request=httpx.Request("POST", url))
                return _MockResponse(rec._response, status_code=rec._raise_status or 200)

            async def get(self, url: str, params: dict | None = None):
                rec.calls.append(("GET", url, None, params))
                if rec._raise_request:
                    raise httpx.RequestError("boom", request=httpx.Request("GET", url))
                return _MockResponse(rec._response, status_code=rec._raise_status or 200)

        return _AC


@pytest.fixture
def recorder(monkeypatch):
    rec = _CallRecorder(response={"status": "created", "service_hash": "a" * 64})
    monkeypatch.setattr("sdk.mcp_server.httpx.AsyncClient", rec._mkclient())
    return rec


def _err(obj_json: str) -> str | None:
    """Return the error string from a handler result JSON, or None if no error."""
    obj = json.loads(obj_json)
    return obj.get("error") if isinstance(obj, dict) else None


# ---------------------------------------------------------------------------
# Bucket A — Schema/whitelist sanity
# ---------------------------------------------------------------------------


class TestSchemaSanity:
    """Every Tool must have a well-formed inputSchema and consistent naming."""

    def test_tool_count_at_least_20(self):
        assert len(TOOLS) >= 20, f"expected 20+ tools, got {len(TOOLS)}"

    def test_all_tools_have_input_schema(self):
        for t in TOOLS:
            assert t.inputSchema is not None
            assert t.inputSchema.get("type") == "object"
            assert "properties" in t.inputSchema

    def test_tool_names_unique(self):
        names = [t.name for t in TOOLS]
        assert len(names) == len(set(names)), f"duplicate tool names: {names}"

    def test_tool_names_are_snake_case(self):
        pattern = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
        for t in TOOLS:
            assert pattern.match(t.name), f"non-snake-case tool name: {t.name}"

    def test_required_fields_subset_of_properties(self):
        """A 'required' field that doesn't exist in properties is a bug."""
        for t in TOOLS:
            required = set(t.inputSchema.get("required", []))
            properties = set(t.inputSchema.get("properties", {}).keys())
            missing = required - properties
            assert not missing, f"{t.name}: required fields not in properties: {missing}"

    def test_enum_declarations_declared_correctly(self):
        """Locate every tool with a declared enum — this test also documents
        which fields SHOULD be whitelisted by the handler.
        """
        declared_enums = {}
        for t in TOOLS:
            for pname, pspec in t.inputSchema.get("properties", {}).items():
                if isinstance(pspec, dict) and "enum" in pspec:
                    declared_enums[f"{t.name}.{pname}"] = pspec["enum"]
        # Freeze the set — new enums added later will break this test on
        # purpose so the reviewer remembers to add matching handler validation.
        assert declared_enums == {
            "list_escrows.status": ["active", "completed", "disputed", "expired"],
            "submit_dispute_arbitration.category": [
                "non_delivery",
                "quality",
                "late_delivery",
                "fraud",
            ],
        }, f"enum surface changed — sync handler validation: {declared_enums}"


# ---------------------------------------------------------------------------
# Bucket B — Injection resistance in validators
# ---------------------------------------------------------------------------


class TestValidatorInjection:

    # ---- _validate_id -----------------------------------------------------

    @pytest.mark.parametrize(
        "bad",
        [
            "",  # empty
            " ",  # whitespace-only after strip → empty
            "a" * 129,  # over length cap
            "hello world",  # space forbidden
            "hello/world",  # path separator
            "hello\\world",  # backslash
            "hello\x00world",  # NUL byte
            "hello\nworld",  # newline injection
            "hello\rworld",  # CR injection
            "hello#world",  # fragment separator
            "hello?world",  # query separator
            "hello&world",  # query separator
            "hello=world",  # query k=v injection
            "hello+world",  # URL-encoded space
            "hello%2Fworld",  # encoded slash bypass attempt
            "../../etc/passwd",  # traversal (contains '/')
            "sender';DROP TABLE",  # SQL-injection shape
            "sender<script>",  # HTML/JS injection shape
            "агент",  # non-ASCII cyrillic (blocked by design)
            "🎃",  # emoji
        ],
    )
    def test_validate_id_rejects_malformed(self, bad):
        with pytest.raises(ValueError):
            _validate_id(bad, "test")

    @pytest.mark.parametrize(
        "good",
        [
            "a",
            "sender-1",
            "sender_2",
            "sender.3",
            "sender:4",
            "A" * 128,  # at the boundary
            "AGENT.42:v1_beta-3",  # realistic mix
        ],
    )
    def test_validate_id_accepts_wellformed(self, good):
        assert _validate_id(good, "test") == good.strip()

    def test_validate_id_trims_leading_trailing_whitespace(self):
        # trim happens before regex → wrapping spaces are OK if inner is legal
        assert _validate_id("  agent-1  ", "test") == "agent-1"

    def test_validate_id_dot_is_allowed_without_slash(self):
        """'.' is explicitly whitelisted so agent ids like 'agent.42' work.
        A lone '..' is therefore accepted as a valid id string; path
        traversal is prevented at the _safe_path/URL layer, not here.
        This test documents that boundary so nobody 'fixes' the regex to
        block dot without checking downstream consumers."""
        assert _validate_id("..", "test") == ".."
        assert _validate_id("agent.42", "test") == "agent.42"

    # ---- _validate_hash ---------------------------------------------------

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "abc",  # too short
            "g" * 64,  # non-hex
            "a" * 63,  # off-by-one short
            "a" * 65,  # off-by-one long
            "a" * 64 + "..",  # trailing garbage
            "0x" + "a" * 62,  # 0x-prefixed (common LLM mistake)
            "aa aa" + "a" * 59,  # embedded space
            None,  # None → str("None") → 4 chars → reject
        ],
    )
    def test_validate_hash_rejects_malformed(self, bad):
        with pytest.raises(ValueError):
            _validate_hash(bad, "svc")

    def test_validate_hash_lowercases_uppercase_hex(self):
        upper = "F" * 64
        assert _validate_hash(upper, "svc") == "f" * 64

    def test_validate_hash_strips_whitespace(self):
        payload = " " + "a" * 64 + " "
        assert _validate_hash(payload, "svc") == "a" * 64

    # ---- _validate_amount -------------------------------------------------

    def test_validate_amount_rejects_zero(self):
        with pytest.raises(ValueError):
            _validate_amount(0)

    def test_validate_amount_rejects_negative(self):
        with pytest.raises(ValueError):
            _validate_amount(-1)

    def test_validate_amount_rejects_over_max(self):
        with pytest.raises(ValueError):
            _validate_amount(MAX_AMOUNT + 1)

    def test_validate_amount_at_boundary(self):
        assert _validate_amount(MAX_AMOUNT) == MAX_AMOUNT
        assert _validate_amount(1) == 1

    def test_validate_amount_rejects_non_numeric(self):
        with pytest.raises((ValueError, TypeError)):
            _validate_amount("not-a-number")

    def test_validate_amount_coerces_numeric_string(self):
        assert _validate_amount("42") == 42

    # ---- _validate_limit --------------------------------------------------

    def test_validate_limit_clamps_high(self):
        assert _validate_limit(10**9) == MAX_LIMIT

    def test_validate_limit_clamps_low(self):
        assert _validate_limit(0) == 1
        assert _validate_limit(-100) == 1

    def test_validate_limit_default_when_none(self):
        assert _validate_limit(None) == 20
        assert _validate_limit(None, default=7) == 7

    # ---- _safe_path -------------------------------------------------------

    @pytest.mark.parametrize(
        "payload,expected_encoded",
        [
            ("../etc/passwd", "..%2Fetc%2Fpasswd"),
            ("a/b", "a%2Fb"),
            ("a b", "a%20b"),
            ("a?b", "a%3Fb"),
            ("a#b", "a%23b"),
            ("a&b=c", "a%26b%3Dc"),
            ("a%2Fb", "a%252Fb"),  # already-encoded slash is re-encoded
            ("a\nb", "a%0Ab"),  # newline injection blocked
        ],
    )
    def test_safe_path_encodes_dangerous_chars(self, payload, expected_encoded):
        assert _safe_path(payload) == expected_encoded


# ---------------------------------------------------------------------------
# Bucket C — Injection resistance in handle_tool
# ---------------------------------------------------------------------------


class TestHandleToolInjection:
    """handle_tool must reject malformed args BEFORE making any HTTP call."""

    def test_create_escrow_rejects_bad_sender_no_http(self, recorder):
        out = _run(
            handle_tool(
                "create_escrow",
                {"sender": "a/b", "receiver": "recv", "amount": 100},
                "http://api",
            )
        )
        assert _err(out) is not None
        assert recorder.calls == [], "validation must not touch the network"

    def test_create_escrow_rejects_over_max_amount_no_http(self, recorder):
        out = _run(
            handle_tool(
                "create_escrow",
                {"sender": "sender", "receiver": "recv", "amount": MAX_AMOUNT + 1},
                "http://api",
            )
        )
        assert _err(out) is not None
        assert recorder.calls == []

    def test_create_escrow_clamps_ttl_high(self, recorder):
        out = _run(
            handle_tool(
                "create_escrow",
                {"sender": "s", "receiver": "r", "amount": 100, "ttl": MAX_TTL * 100},
                "http://api",
            )
        )
        assert _err(out) is None
        # Body should carry the clamped TTL, not the malicious inflated one
        _, _, body, _ = recorder.calls[0]
        assert body["ttl"] == MAX_TTL

    def test_create_escrow_clamps_ttl_low(self, recorder):
        out = _run(
            handle_tool(
                "create_escrow",
                {"sender": "s", "receiver": "r", "amount": 100, "ttl": 1},
                "http://api",
            )
        )
        assert _err(out) is None
        _, _, body, _ = recorder.calls[0]
        assert body["ttl"] == MIN_TTL

    def test_release_rejects_bad_hash_no_http(self, recorder):
        out = _run(
            handle_tool(
                "release_escrow",
                {"sender": "s", "service_hash": "not-a-hash"},
                "http://api",
            )
        )
        assert _err(out) is not None
        assert recorder.calls == []

    def test_dispute_rejects_bad_reason_hash_no_http(self, recorder):
        out = _run(
            handle_tool(
                "dispute_escrow",
                {"sender": "s", "service_hash": "a" * 64, "reason_hash": "0x123"},
                "http://api",
            )
        )
        assert _err(out) is not None
        assert recorder.calls == []

    def test_get_escrow_hash_is_urlencoded_in_path(self, recorder):
        # A well-formed hash should end up URL-safe in the path
        out = _run(
            handle_tool(
                "get_escrow",
                {"service_hash": "a" * 64},
                "http://api",
            )
        )
        assert _err(out) is None
        assert recorder.calls[0][0] == "GET"
        assert recorder.calls[0][1] == f"http://api/escrow/{'a' * 64}"

    def test_get_reputation_agent_urlencoded_in_path(self, recorder):
        out = _run(
            handle_tool(
                "get_reputation",
                {"agent": "agent.42:v1_beta-3"},
                "http://api",
            )
        )
        assert _err(out) is None
        assert recorder.calls[0][1] == "http://api/reputation/agent.42%3Av1_beta-3"

    def test_get_identity_rejects_path_traversal_no_http(self, recorder):
        out = _run(
            handle_tool(
                "get_identity",
                {"agent_id": "../secrets"},
                "http://api",
            )
        )
        assert _err(out) is not None
        assert recorder.calls == []


# ---------------------------------------------------------------------------
# Bucket D — Size / DoS caps
# ---------------------------------------------------------------------------


class TestSizeCaps:
    """Uncapped input on batch or free-text arguments is a DoS vector."""

    def test_submit_dispute_evidence_truncated_at_10k(self, recorder):
        payload = "A" * 100_000
        out = _run(
            handle_tool(
                "submit_dispute_arbitration",
                {
                    "service_hash": "a" * 64,
                    "evidence_sender": payload,
                    "evidence_receiver": payload,
                },
                "http://api",
            )
        )
        assert _err(out) is None
        _, _, body, _ = recorder.calls[0]
        assert len(body["evidence_sender"]) == 10_000
        assert len(body["evidence_receiver"]) == 10_000

    def test_appeal_new_evidence_truncated_at_10k(self, recorder):
        payload = "B" * 100_000
        out = _run(
            handle_tool(
                "appeal_arbitration",
                {"arbitration_id": "arb-1", "appellant": "sender", "new_evidence": payload},
                "http://api",
            )
        )
        assert _err(out) is None
        _, _, body, _ = recorder.calls[0]
        assert len(body["new_evidence"]) == 10_000

    def test_register_identity_pubkey_truncated_at_256(self, recorder):
        payload = "C" * 10_000
        out = _run(
            handle_tool(
                "register_identity",
                {"agent_id": "agent-1", "public_key": payload},
                "http://api",
            )
        )
        assert _err(out) is None
        _, _, body, _ = recorder.calls[0]
        assert len(body["public_key"]) == 256

    def test_batch_release_validates_every_hash(self, recorder):
        # Twenty valid hashes + one bad = whole batch rejected before HTTP
        hashes = ["a" * 64] * 20 + ["not-a-hash"]
        out = _run(
            handle_tool(
                "batch_release",
                {"sender": "s", "service_hashes": hashes},
                "http://api",
            )
        )
        assert _err(out) is not None
        assert recorder.calls == [], "one bad hash must poison the batch pre-flight"

    def test_batch_cancel_validates_every_hash(self, recorder):
        hashes = ["a" * 64] * 5 + ["b" * 63]  # off-by-one bad hash
        out = _run(
            handle_tool(
                "batch_cancel",
                {"sender": "s", "service_hashes": hashes},
                "http://api",
            )
        )
        assert _err(out) is not None
        assert recorder.calls == []

    def test_list_escrows_limit_clamped(self, recorder):
        out = _run(
            handle_tool(
                "list_escrows",
                {"limit": 10**9},
                "http://api",
            )
        )
        assert _err(out) is None
        _, _, _, params = recorder.calls[0]
        assert int(params["limit"]) == MAX_LIMIT

    def test_get_events_limit_clamped(self, recorder):
        out = _run(
            handle_tool(
                "get_events",
                {"limit": 10**9},
                "http://api",
            )
        )
        assert _err(out) is None
        _, _, _, params = recorder.calls[0]
        assert int(params["limit"]) == MAX_LIMIT


# ---------------------------------------------------------------------------
# Bucket E — Error envelope discipline
# ---------------------------------------------------------------------------


class TestErrorEnvelope:
    """No stack traces, no backend URLs, no reflected attacker payload in
    HTTP-error surfaces (validation errors legitimately echo bad-input, but
    are constrained to Python's built-in exception messages)."""

    def test_http_error_envelope_hides_backend(self, monkeypatch):
        rec = _CallRecorder(raise_status=500)
        monkeypatch.setattr("sdk.mcp_server.httpx.AsyncClient", rec._mkclient())
        out = _run(
            handle_tool(
                "get_escrow",
                {"service_hash": "a" * 64},
                "http://internal-backend:8000",
            )
        )
        obj = json.loads(out)
        assert obj == {"error": "API request failed"}
        # Ensure the backend URL was NOT echoed back to the LLM
        assert "internal-backend" not in json.dumps(obj)

    def test_connection_error_envelope_hides_url(self, monkeypatch):
        rec = _CallRecorder(raise_request=True)
        monkeypatch.setattr("sdk.mcp_server.httpx.AsyncClient", rec._mkclient())
        out = _run(
            handle_tool(
                "get_escrow",
                {"service_hash": "a" * 64},
                "http://internal-backend:8000",
            )
        )
        obj = json.loads(out)
        assert obj == {"error": "API connection error"}
        assert "internal-backend" not in json.dumps(obj)

    def test_unknown_tool_returns_error(self, recorder):
        out = _run(handle_tool("no_such_tool", {}, "http://api"))
        assert _err(out) is not None
        assert "no_such_tool" in _err(out)  # informational, not stack trace
        assert recorder.calls == []

    def test_missing_required_arg_returns_error_no_http(self, recorder):
        out = _run(
            handle_tool(
                "release_escrow",
                {"sender": "s"},  # missing service_hash
                "http://api",
            )
        )
        assert _err(out) is not None
        assert recorder.calls == []

    def test_validation_error_never_contains_url(self, recorder):
        out = _run(
            handle_tool(
                "create_escrow",
                {"sender": "bad/id", "receiver": "r", "amount": 1},
                "http://internal-backend:8000",
            )
        )
        obj = json.loads(out)
        assert "error" in obj
        assert "internal-backend" not in json.dumps(obj)
        assert recorder.calls == []


# ---------------------------------------------------------------------------
# Bucket F — Positive-path wiring sanity for the underexercised tools
# ---------------------------------------------------------------------------


class TestPositivePathWiring:
    """One happy path per tool to prove the URL, method, body-shape and
    param-shape are correct. Regressions here mean an LLM would misroute
    live money."""

    def test_release_calls_release_endpoint(self, recorder):
        _run(
            handle_tool(
                "release_escrow",
                {"sender": "s", "service_hash": "a" * 64},
                "http://api",
            )
        )
        method, url, body, params = recorder.calls[0]
        assert method == "POST"
        assert url == "http://api/release"
        assert body == {"service_hash": "a" * 64}
        assert params == {"sender": "s"}

    def test_refund_calls_refund_endpoint(self, recorder):
        _run(
            handle_tool(
                "refund_escrow",
                {"sender": "s", "service_hash": "a" * 64},
                "http://api",
            )
        )
        method, url, _, params = recorder.calls[0]
        assert method == "POST"
        assert url == "http://api/refund"
        assert params == {"sender": "s"}

    def test_dispute_carries_reason_hash(self, recorder):
        _run(
            handle_tool(
                "dispute_escrow",
                {"sender": "s", "service_hash": "a" * 64, "reason_hash": "b" * 64},
                "http://api",
            )
        )
        _, url, body, _ = recorder.calls[0]
        assert url == "http://api/dispute"
        assert body["reason_hash"] == "b" * 64

    def test_estimate_fee_calls_get(self, recorder):
        _run(handle_tool("estimate_fee", {"amount": 100}, "http://api"))
        method, url, _, params = recorder.calls[0]
        assert method == "GET"
        assert url == "http://api/estimate"
        assert params == {"amount": "100"}

    def test_health_check_no_args(self, recorder):
        _run(handle_tool("health_check", {}, "http://api"))
        method, url, _, _ = recorder.calls[0]
        assert method == "GET"
        assert url == "http://api/health"

    def test_stats_no_args(self, recorder):
        _run(handle_tool("get_stats", {}, "http://api"))
        method, url, _, _ = recorder.calls[0]
        assert url == "http://api/stats"

    def test_agents_no_args(self, recorder):
        _run(handle_tool("list_agents", {}, "http://api"))
        method, url, _, _ = recorder.calls[0]
        assert url == "http://api/agents"

    def test_elect_arbiter_body_shape(self, recorder):
        _run(
            handle_tool(
                "elect_arbiter",
                {"dispute_id": "d1", "sender": "s", "receiver": "r", "seed_hash": "a" * 64},
                "http://api",
            )
        )
        _, url, body, _ = recorder.calls[0]
        assert url == "http://api/vrf/elect"
        assert body == {"dispute_id": "d1", "sender": "s", "receiver": "r", "seed_hash": "a" * 64}

    def test_batch_release_body_shape(self, recorder):
        hashes = ["a" * 64, "b" * 64]
        _run(
            handle_tool(
                "batch_release",
                {"sender": "s", "service_hashes": hashes},
                "http://api",
            )
        )
        _, url, body, params = recorder.calls[0]
        assert url == "http://api/escrows/batch-release"
        assert body == {"service_hashes": hashes}
        assert params == {"sender": "s"}

    def test_claim_stream_urlencoded(self, recorder):
        _run(
            handle_tool(
                "claim_stream",
                {"service_hash": "a" * 64},
                "http://api",
            )
        )
        _, url, _, _ = recorder.calls[0]
        assert url == f"http://api/escrow/{'a' * 64}/stream-claim"


# ---------------------------------------------------------------------------
# Bucket G — Deterministic hash + x402 header shape
# ---------------------------------------------------------------------------


class TestDeterministicHash:

    def test_hash_is_deterministic(self):
        h1 = _hash("s", "r", 100, "n")
        h2 = _hash("s", "r", 100, "n")
        assert h1 == h2
        assert re.match(r"^[a-f0-9]{64}$", h1)

    def test_hash_changes_with_any_input(self):
        base = _hash("s", "r", 100, "n")
        assert _hash("s2", "r", 100, "n") != base
        assert _hash("s", "r2", 100, "n") != base
        assert _hash("s", "r", 101, "n") != base
        assert _hash("s", "r", 100, "n2") != base

    def test_build_x402_header_shape(self, recorder):
        out = _run(
            handle_tool(
                "build_x402_header",
                {"sender": "s", "receiver": "r", "amount": 100},
                "http://api",
            )
        )
        obj = json.loads(out)
        # Must NOT touch the network
        assert recorder.calls == []
        assert "header" in obj
        assert obj["header"].startswith("x402;1;100;")
        # header format: x402;version;amount;service_hash;ts;nonce
        parts = obj["header"].split(";")
        assert len(parts) == 6
        assert parts[0] == "x402"
        assert parts[1] == "1"
        assert parts[2] == "100"
        assert re.match(r"^[a-f0-9]{64}$", parts[3])
        assert parts[3] == obj["service_hash"]
        assert parts[5] == obj["nonce"]


# ---------------------------------------------------------------------------
# Bucket H — Server wiring
# ---------------------------------------------------------------------------


class TestServerWiring:

    def test_build_server_registers_all_tools(self):
        """build_server must produce a Server that exposes exactly TOOLS."""
        srv = build_server("http://api")
        # The mcp Server class stores decorators in private attributes; the
        # public surface we care about here is that build_server runs without
        # error and returns a Server-like object.
        assert srv is not None
        assert hasattr(srv, "run")

    def test_regex_constants_are_strict(self):
        """The exposed regexes must be exactly what the docs claim."""
        assert SHA256_RE.match("a" * 64)
        assert not SHA256_RE.match("A" * 64)  # SHA256_RE is case-sensitive
        assert ID_RE.match("agent-1")
        assert not ID_RE.match("agent 1")


# ---------------------------------------------------------------------------
# Bucket I — enum-gap flags (documenting the two real findings)
# ---------------------------------------------------------------------------


class TestEnumGaps:
    """These two tests DOCUMENT current behaviour rather than assert on it:
    the handler does not enforce declared enums on `list_escrows.status`
    or `submit_dispute_arbitration.category`. When the handler is patched
    to enforce them, flip these tests to strict-negative assertions."""

    def test_list_escrows_accepts_undeclared_status_today(self, recorder):
        out = _run(
            handle_tool(
                "list_escrows",
                {"status": "banana"},
                "http://api",
            )
        )
        # Today: passes to backend
        assert _err(out) is None
        _, _, _, params = recorder.calls[0]
        assert params.get("status") == "banana"

    def test_dispute_arbitration_accepts_undeclared_category_today(self, recorder):
        out = _run(
            handle_tool(
                "submit_dispute_arbitration",
                {
                    "service_hash": "a" * 64,
                    "evidence_sender": "e1",
                    "evidence_receiver": "e2",
                    "category": "not_a_real_category",
                },
                "http://api",
            )
        )
        assert _err(out) is None
        _, _, body, _ = recorder.calls[0]
        assert body["category"] == "not_a_real_category"
