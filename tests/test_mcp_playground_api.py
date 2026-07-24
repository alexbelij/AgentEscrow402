"""Tests for /mcp/* hosted playground endpoints."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from server.app import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


class TestMcpToolsCatalogue:
    def test_lists_all_shipped_tools(self, client: TestClient) -> None:
        r = client.get("/mcp/tools")
        assert r.status_code == 200
        body = r.json()
        assert body["name"]  # non-empty catalogue name
        # The bundled schema ships 26 tools; assert non-empty rather than
        # pin the count so adding a tool later doesn't break the suite.
        assert len(body["tools"]) >= 20
        names = {t["name"] for t in body["tools"]}
        assert "create_escrow" in names
        assert "release_escrow" in names
        assert "list_escrows" in names

    def test_every_tool_has_input_schema(self, client: TestClient) -> None:
        body = client.get("/mcp/tools").json()
        for t in body["tools"]:
            assert "name" in t
            assert "description" in t
            assert "inputSchema" in t
            schema = t["inputSchema"]
            # JSON Schema — at least a `type` field.
            assert isinstance(schema, dict)
            assert schema.get("type") in {"object", None}


class TestMcpToolCall:
    def test_call_unknown_tool_404(self, client: TestClient) -> None:
        r = client.post("/mcp/tools/does_not_exist/call", json={"arguments": {}})
        assert r.status_code == 404

    def test_call_health_check(self, client: TestClient) -> None:
        """health_check is a read tool with no arguments — the safest smoke
        test to prove the dispatcher actually reaches the underlying REST
        endpoint via the ASGI transport."""
        r = client.post("/mcp/tools/health_check/call", json={"arguments": {}})
        assert r.status_code == 200
        body = r.json()
        assert body["tool"] == "health_check"
        assert body["isError"] is False
        assert body["status"] == 200
        # Content is text-wrapped JSON — parse it back.
        inner = json.loads(body["content"][0]["text"])
        assert "status" in inner or "ok" in inner

    def test_call_get_stats(self, client: TestClient) -> None:
        r = client.post("/mcp/tools/get_stats/call", json={"arguments": {}})
        assert r.status_code == 200
        body = r.json()
        assert body["isError"] is False
        assert body["status"] == 200

    def test_call_estimate_fee_with_query_arg(self, client: TestClient) -> None:
        r = client.post(
            "/mcp/tools/estimate_fee/call",
            json={"arguments": {"amount": 10_000_000_000}},
        )
        assert r.status_code == 200
        body = r.json()
        # The REST endpoint may 200 or 400 depending on validation. What
        # matters here is the dispatcher passed the arg through.
        assert body["tool"] == "estimate_fee"
        assert body["status"] in {200, 400, 422}

    def test_missing_path_arg_returns_400(self, client: TestClient) -> None:
        # get_escrow needs `escrow_id`. Sending no args should 400 at the
        # dispatcher before any REST call.
        r = client.post("/mcp/tools/get_escrow/call", json={"arguments": {}})
        assert r.status_code == 400
        assert "escrow_id" in r.text

    def test_write_tool_dispatch_reaches_underlying_endpoint(self, client: TestClient) -> None:
        """create_escrow via the playground reaches POST /escrow with the
        same auth path as a direct HTTP call — no separate bypass path.

        The point of this test is *dispatch fidelity*, not that a write
        without an x402 header is rejected: whether the underlying endpoint
        allows a demo-flavoured call in the TestClient depends on
        middleware config; what we assert is that the tool call didn't
        short-circuit inside the playground module.
        """
        r = client.post(
            "/mcp/tools/create_escrow/call",
            json={
                "arguments": {
                    "receiver": "0" * 64,
                    "amount": 1_000_000,
                    "service_hash": "a" * 64,
                    "ttl": 300,
                }
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["tool"] == "create_escrow"
        # Anything except a playground-side dispatcher error (500).
        assert body["status"] != 500
