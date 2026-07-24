"""HTTP tests for ``server.telegram_api``.

Every test wires a :class:`~sdk.telegram_bridge.TelegramClient` backed by a
:class:`httpx.MockTransport`, so no real Telegram traffic ever leaves the
process.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sdk.telegram_bridge import TelegramClient
from server import telegram_api


def _make_client(handler) -> TelegramClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return TelegramClient(
        "test-token",
        http_client=http,
        sleep=lambda t: __import__("asyncio").sleep(0),
    )


def _make_app(client: TelegramClient | None = None, *, base_url: str | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(telegram_api.router)
    if client is not None:
        telegram_api.init_bridge(token="test-token", base_url=base_url, client=client)
    else:
        telegram_api.init_bridge(token=None)
    return TestClient(app)


# --------------------------------------------------------------------------- #
# Configuration & readiness
# --------------------------------------------------------------------------- #


class TestStatus:
    def test_status_when_disabled(self):
        client = _make_app(None)
        r = client.get("/telegram/status")
        assert r.status_code == 200
        body = r.json()
        assert body == {"ready": False, "configured": False, "active_subscriptions": 0}

    def test_status_when_enabled(self):
        seen: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        client = _make_app(_make_client(handler))
        r = client.get("/telegram/status")
        body = r.json()
        assert body["ready"] is True
        assert body["configured"] is True
        assert body["active_subscriptions"] == 0

    def test_subscribe_503_when_disabled(self):
        client = _make_app(None)
        r = client.post("/telegram/subscribe", json={"chat_id": 42})
        assert r.status_code == 503
        assert "TELEGRAM_BOT_TOKEN" in r.json()["detail"]

    def test_unsubscribe_503_when_disabled(self):
        client = _make_app(None)
        r = client.delete("/telegram/subscriptions/abc")
        assert r.status_code == 503

    def test_test_send_503_when_disabled(self):
        client = _make_app(None)
        r = client.post("/telegram/test", json={"chat_id": 1})
        assert r.status_code == 503


# --------------------------------------------------------------------------- #
# Subscribe / unsubscribe
# --------------------------------------------------------------------------- #


class TestSubscribe:
    def test_subscribe_wildcard(self):
        client = _make_app(_make_client(lambda r: httpx.Response(200, json={"ok": True, "result": {}})))
        r = client.post("/telegram/subscribe", json={"chat_id": 111})
        assert r.status_code == 201
        body = r.json()
        assert body["chat_id"] == 111
        assert body["filter"] == {"event_types": [], "service_hashes": [], "receivers": []}
        assert isinstance(body["sub_id"], str) and body["sub_id"]

    def test_subscribe_with_filter(self):
        client = _make_app(_make_client(lambda r: httpx.Response(200, json={"ok": True, "result": {}})))
        r = client.post(
            "/telegram/subscribe",
            json={
                "chat_id": 222,
                "filter": {
                    "event_types": ["escrow_released"],
                    "service_hashes": "abcd",
                    "receivers": ["alice", "bob"],
                },
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert body["filter"]["event_types"] == ["escrow_released"]
        assert body["filter"]["service_hashes"] == ["abcd"]
        assert sorted(body["filter"]["receivers"]) == ["alice", "bob"]

    def test_subscribe_rejects_zero_chat_id(self):
        client = _make_app(_make_client(lambda r: httpx.Response(200, json={"ok": True, "result": {}})))
        r = client.post("/telegram/subscribe", json={"chat_id": 0})
        assert r.status_code == 422

    def test_subscribe_rejects_invalid_filter(self):
        client = _make_app(_make_client(lambda r: httpx.Response(200, json={"ok": True, "result": {}})))
        r = client.post(
            "/telegram/subscribe",
            json={"chat_id": 1, "filter": {"event_types": 123}},
        )
        assert r.status_code == 422

    def test_subscribe_bumps_status_counter(self):
        client = _make_app(_make_client(lambda r: httpx.Response(200, json={"ok": True, "result": {}})))
        client.post("/telegram/subscribe", json={"chat_id": 1})
        client.post("/telegram/subscribe", json={"chat_id": 2})
        r = client.get("/telegram/status")
        assert r.json()["active_subscriptions"] == 2

    def test_unsubscribe_success(self):
        client = _make_app(_make_client(lambda r: httpx.Response(200, json={"ok": True, "result": {}})))
        sub = client.post("/telegram/subscribe", json={"chat_id": 1}).json()
        r = client.delete(f"/telegram/subscriptions/{sub['sub_id']}")
        assert r.status_code == 204
        assert r.content == b""

    def test_unsubscribe_unknown_id(self):
        client = _make_app(_make_client(lambda r: httpx.Response(200, json={"ok": True, "result": {}})))
        r = client.delete("/telegram/subscriptions/no-such-id")
        assert r.status_code == 404

    def test_list_subscriptions(self):
        client = _make_app(_make_client(lambda r: httpx.Response(200, json={"ok": True, "result": {}})))
        client.post("/telegram/subscribe", json={"chat_id": 1})
        client.post("/telegram/subscribe", json={"chat_id": 2})
        r = client.get("/telegram/subscriptions")
        body = r.json()
        assert len(body["subscriptions"]) == 2
        assert {s["chat_id"] for s in body["subscriptions"]} == {1, 2}

    def test_list_subscriptions_when_disabled(self):
        """The list endpoint is read-only and stays available."""

        client = _make_app(None)
        r = client.get("/telegram/subscriptions")
        assert r.status_code == 200
        assert r.json() == {"subscriptions": []}


# --------------------------------------------------------------------------- #
# Test-send
# --------------------------------------------------------------------------- #


class TestSmokeSend:
    def test_test_send_success(self):
        seen: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

        client = _make_app(_make_client(handler))
        r = client.post("/telegram/test", json={"chat_id": 999, "text": "hi!"})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert seen[0]["chat_id"] == 999
        # Message body must be MarkdownV2-escaped.
        assert "hi\\!" in seen[0]["text"]
        assert seen[0]["parse_mode"] == "MarkdownV2"

    def test_test_send_bubbles_permanent_error_as_502(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"ok": False, "description": "chat not found"})

        client = _make_app(_make_client(handler))
        r = client.post("/telegram/test", json={"chat_id": 999})
        assert r.status_code == 502
        assert "chat not found" in r.json()["detail"]

    def test_test_send_rejects_zero_chat_id(self):
        client = _make_app(_make_client(lambda r: httpx.Response(200, json={"ok": True, "result": {}})))
        r = client.post("/telegram/test", json={"chat_id": 0})
        assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure webhook env is off unless a test opts in."""

    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    yield


class TestWebhook:
    def test_webhook_503_without_secret_env(self):
        client = _make_app(_make_client(lambda r: httpx.Response(200, json={"ok": True, "result": {}})))
        r = client.post("/telegram/webhook/anything", json={"update_id": 1})
        assert r.status_code == 503

    def test_webhook_403_on_secret_mismatch(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "expected")
        client = _make_app(_make_client(lambda r: httpx.Response(200, json={"ok": True, "result": {}})))
        r = client.post("/telegram/webhook/wrong", json={"update_id": 1})
        assert r.status_code == 403

    def test_webhook_accepts_header_match(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "expected")
        client = _make_app(_make_client(lambda r: httpx.Response(200, json={"ok": True, "result": {}})))
        r = client.post(
            "/telegram/webhook/wrong",
            headers={"X-Telegram-Bot-Api-Secret-Token": "expected"},
            json={"update_id": 1, "message": {"chat": {"id": 1}, "text": "/status"}},
        )
        assert r.status_code == 200
        assert r.json()["handled"] is True

    def test_webhook_subscribe_command(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
        sends: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sends.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {}})

        client = _make_app(_make_client(handler))
        r = client.post(
            "/telegram/webhook/secret",
            json={
                "update_id": 1,
                "message": {"chat": {"id": 555}, "text": "/subscribe escrow_released"},
            },
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True, "handled": True, "command": "subscribe"}
        # It replied to the chat.
        assert sends and sends[0]["chat_id"] == 555
        # And it registered a subscription with the requested filter.
        subs = client.get("/telegram/subscriptions").json()["subscriptions"]
        assert len(subs) == 1
        assert subs[0]["filter"]["event_types"] == ["escrow_released"]

    def test_webhook_unsubscribe_command(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
        client = _make_app(_make_client(lambda r: httpx.Response(200, json={"ok": True, "result": {}})))
        # Register two subs for the same chat, plus one for another chat.
        client.post("/telegram/subscribe", json={"chat_id": 555})
        client.post("/telegram/subscribe", json={"chat_id": 555})
        client.post("/telegram/subscribe", json={"chat_id": 111})
        client.post(
            "/telegram/webhook/secret",
            json={"update_id": 1, "message": {"chat": {"id": 555}, "text": "/unsubscribe"}},
        )
        subs = client.get("/telegram/subscriptions").json()["subscriptions"]
        assert [s["chat_id"] for s in subs] == [111]

    def test_webhook_strips_bot_suffix(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
        client = _make_app(_make_client(lambda r: httpx.Response(200, json={"ok": True, "result": {}})))
        r = client.post(
            "/telegram/webhook/secret",
            json={"update_id": 1, "message": {"chat": {"id": 1}, "text": "/status@ae402_bot"}},
        )
        assert r.status_code == 200
        assert r.json()["command"] == "status"

    def test_webhook_ignores_non_command(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
        client = _make_app(_make_client(lambda r: httpx.Response(200, json={"ok": True, "result": {}})))
        r = client.post(
            "/telegram/webhook/secret",
            json={"update_id": 1, "message": {"chat": {"id": 1}, "text": "hello"}},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True, "handled": False}


# --------------------------------------------------------------------------- #
# Fan-out from broadcast
# --------------------------------------------------------------------------- #


class TestFanout:
    def test_fanout_delivers_to_matching(self):
        import asyncio

        sends: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sends.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {}})

        client = _make_app(_make_client(handler))
        client.post("/telegram/subscribe", json={"chat_id": 1})
        client.post(
            "/telegram/subscribe",
            json={"chat_id": 2, "filter": {"event_types": ["escrow_created"]}},
        )
        asyncio.new_event_loop().run_until_complete(
            telegram_api.fanout_event({"type": "escrow_released", "service_hash": "x"})
        )
        # Only chat 1 (wildcard) receives.
        assert [s["chat_id"] for s in sends] == [1]

    def test_fanout_noop_when_disabled(self):
        import asyncio

        _make_app(None)
        # No exception, no crash — the SSE fan-out must stay untouched.
        asyncio.new_event_loop().run_until_complete(
            telegram_api.fanout_event({"type": "escrow_released"})
        )
