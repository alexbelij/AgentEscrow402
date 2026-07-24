"""Property tests for :mod:`sdk.telegram_bridge`.

These tests never hit the real Telegram API. All I/O is fed through
:class:`httpx.MockTransport`, and time is virtualized via an injected sleep
function so retries execute instantly.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from sdk.telegram_bridge import (
    EventFormatter,
    SubscriptionFilter,
    SubscriptionRegistry,
    TelegramAPIError,
    TelegramBridge,
    TelegramClient,
    escape_markdown_v2,
)

# --------------------------------------------------------------------------- #
# MarkdownV2 escaping
# --------------------------------------------------------------------------- #


class TestEscapeMarkdownV2:
    """The escaper must neutralise every reserved MarkdownV2 metacharacter."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("", ""),
            (None, ""),
            ("plain text", "plain text"),
            ("dot.", "dot\\."),
            ("multi.dot.pattern", "multi\\.dot\\.pattern"),
            ("under_score", "under\\_score"),
            ("*bold*", "\\*bold\\*"),
            ("[link](url)", "\\[link\\]\\(url\\)"),
            ("hash `abc`", "hash \\`abc\\`"),
            ("pipe | table", "pipe \\| table"),
            ("!bang", "\\!bang"),
            ("backslash \\ inside", "backslash \\\\ inside"),
        ],
    )
    def test_reserved_chars_escaped(self, raw, expected):
        assert escape_markdown_v2(raw) == expected

    def test_non_string_coerced(self):
        assert escape_markdown_v2(42) == "42"
        assert escape_markdown_v2(True) == "True"

    def test_result_contains_no_unescaped_reserved(self):
        """No reserved char may appear un-preceded by a backslash."""

        raw = "".join(chr(c) for c in range(32, 127))
        out = escape_markdown_v2(raw)
        for i, ch in enumerate(out):
            if ch in "_*[]()~`>#+-=|{}.!":
                # Must be preceded by an odd number of backslashes.
                bs = 0
                j = i - 1
                while j >= 0 and out[j] == "\\":
                    bs += 1
                    j -= 1
                assert bs % 2 == 1, f"unescaped {ch!r} at {i} in {out!r}"


# --------------------------------------------------------------------------- #
# EventFormatter
# --------------------------------------------------------------------------- #


class TestEventFormatter:
    def test_known_event_uses_specific_label(self):
        f = EventFormatter()
        text, mode = f.format({"type": "escrow_released", "service_hash": "a" * 64})
        assert mode == "MarkdownV2"
        assert "Escrow released" in text
        # service_hash is displayed shortened and inside a code span.
        assert "`" in text
        assert "aaaaaaaaaaaaaaaa…" in text

    def test_unknown_event_falls_back_to_generic(self):
        f = EventFormatter()
        text, _ = f.format({"type": "brand_new_event"})
        assert "Event: brand\\_new\\_event" in text

    def test_amount_and_reason_included_when_present(self):
        f = EventFormatter()
        text, _ = f.format(
            {
                "type": "escrow_disputed",
                "service_hash": "deadbeef" * 8,
                "amount": 1234,
                "reason": "user requested refund",
            }
        )
        assert "amount" in text
        assert "reason" in text
        assert "user requested refund" in text

    def test_timestamp_rendered_when_int(self):
        f = EventFormatter()
        text, _ = f.format({"type": "escrow_created", "ts": 1_700_000_000})
        assert "2023" in text  # 2023-11-14T22:13:20Z

    def test_deterministic_output(self):
        """Formatting the same event twice yields byte-identical output."""

        f = EventFormatter()
        event = {"type": "escrow_released", "service_hash": "1234" * 16, "amount": 42}
        a, _ = f.format(event)
        b, _ = f.format(event)
        assert a == b

    def test_base_url_produces_link(self):
        f = EventFormatter(base_url="https://ae402.example.com/")
        text, _ = f.format(
            {"type": "escrow_released", "service_hash": "abc" * 20}
        )
        assert "[view escrow](https://ae402.example.com/escrows/" in text

    def test_no_base_url_no_link(self):
        f = EventFormatter()
        text, _ = f.format({"type": "escrow_released", "service_hash": "abc"})
        assert "view escrow" not in text

    def test_dangerous_field_values_are_escaped(self):
        """A malicious service_hash cannot escape its code span."""

        f = EventFormatter()
        text, _ = f.format({"type": "escrow_released", "service_hash": "abc`__*"})
        # Every metacharacter in the value must be escaped.
        assert "\\`" in text
        # The literal metachars must NOT appear without a preceding backslash.
        assert "abc`__*" not in text

    def test_missing_fields_are_skipped(self):
        f = EventFormatter()
        text, _ = f.format({"type": "connected"})
        # No 'hash', 'amount', etc. present.
        assert "hash:" not in text
        assert "amount:" not in text


# --------------------------------------------------------------------------- #
# SubscriptionFilter
# --------------------------------------------------------------------------- #


class TestSubscriptionFilter:
    def test_empty_filter_matches_any_event(self):
        f = SubscriptionFilter()
        assert f.matches({"type": "anything"})
        assert f.matches({})

    def test_event_type_filter_case_insensitive(self):
        f = SubscriptionFilter(event_types=frozenset({"escrow_released"}))
        assert f.matches({"type": "escrow_released"})
        assert f.matches({"type": "ESCROW_RELEASED"})
        assert not f.matches({"type": "escrow_created"})

    def test_event_type_filter_rejects_missing_type(self):
        f = SubscriptionFilter(event_types=frozenset({"x"}))
        assert not f.matches({})

    def test_service_hash_filter(self):
        f = SubscriptionFilter(service_hashes=frozenset({"deadbeef"}))
        assert f.matches({"type": "x", "service_hash": "deadbeef"})
        assert not f.matches({"type": "x", "service_hash": "other"})
        assert not f.matches({"type": "x"})

    def test_receiver_filter_matches_receiver_or_payee(self):
        f = SubscriptionFilter(receivers=frozenset({"alice"}))
        assert f.matches({"type": "x", "receiver": "alice"})
        assert f.matches({"type": "x", "payee": "alice"})
        assert not f.matches({"type": "x", "payee": "bob"})
        assert not f.matches({"type": "x"})

    def test_all_criteria_are_and_ed(self):
        f = SubscriptionFilter(
            event_types=frozenset({"escrow_released"}),
            service_hashes=frozenset({"h1"}),
            receivers=frozenset({"alice"}),
        )
        assert f.matches(
            {"type": "escrow_released", "service_hash": "h1", "receiver": "alice"}
        )
        # One criterion fails → whole filter fails.
        assert not f.matches(
            {"type": "escrow_created", "service_hash": "h1", "receiver": "alice"}
        )
        assert not f.matches(
            {"type": "escrow_released", "service_hash": "h2", "receiver": "alice"}
        )
        assert not f.matches(
            {"type": "escrow_released", "service_hash": "h1", "receiver": "bob"}
        )

    def test_from_dict_accepts_str_and_list(self):
        f = SubscriptionFilter.from_dict(
            {
                "event_types": "escrow_released",
                "service_hashes": ["h1", "h2"],
                "receivers": ["alice"],
            }
        )
        assert f.event_types == frozenset({"escrow_released"})
        assert f.service_hashes == frozenset({"h1", "h2"})
        assert f.receivers == frozenset({"alice"})

    def test_from_dict_rejects_invalid_shape(self):
        with pytest.raises(TypeError):
            SubscriptionFilter.from_dict({"event_types": 42})
        with pytest.raises(TypeError):
            SubscriptionFilter.from_dict({"service_hashes": [1, 2]})

    def test_from_dict_ignores_unknown_keys(self):
        f = SubscriptionFilter.from_dict({"nonsense": "value"})
        assert f == SubscriptionFilter()

    def test_from_dict_none_is_empty(self):
        assert SubscriptionFilter.from_dict(None) == SubscriptionFilter()

    def test_from_dict_normalises_empty_strings(self):
        """Empty strings inside the list are dropped, not stored."""

        f = SubscriptionFilter.from_dict({"receivers": ["alice", ""]})
        assert f.receivers == frozenset({"alice"})


# --------------------------------------------------------------------------- #
# SubscriptionRegistry
# --------------------------------------------------------------------------- #


class TestSubscriptionRegistry:
    def test_add_and_list(self):
        counter = {"n": 0}

        def gen():
            counter["n"] += 1
            return f"sub_{counter['n']}"

        reg = SubscriptionRegistry(id_generator=gen)
        s1 = reg.add(111, SubscriptionFilter())
        s2 = reg.add(222, SubscriptionFilter(event_types=frozenset({"x"})))
        assert [s.sub_id for s in reg.list()] == ["sub_1", "sub_2"]
        assert s1.chat_id == 111
        assert s2.filter.event_types == frozenset({"x"})

    def test_remove_returns_true_only_when_present(self):
        reg = SubscriptionRegistry()
        sub = reg.add(1, SubscriptionFilter())
        assert reg.remove(sub.sub_id) is True
        assert reg.remove(sub.sub_id) is False

    def test_matching_returns_only_matching_subs(self):
        reg = SubscriptionRegistry()
        wildcard = reg.add(1, SubscriptionFilter())
        typed = reg.add(2, SubscriptionFilter(event_types=frozenset({"escrow_released"})))
        assert set(s.sub_id for s in reg.matching({"type": "escrow_released"})) == {
            wildcard.sub_id,
            typed.sub_id,
        }
        assert reg.matching({"type": "other"}) == [wildcard]

    def test_chat_id_type_enforced(self):
        reg = SubscriptionRegistry()
        with pytest.raises(TypeError):
            reg.add("123", SubscriptionFilter())

    def test_clear(self):
        reg = SubscriptionRegistry()
        reg.add(1, SubscriptionFilter())
        reg.add(2, SubscriptionFilter())
        reg.clear()
        assert reg.list() == []

    def test_to_dict_is_stable(self):
        reg = SubscriptionRegistry()
        sub = reg.add(1, SubscriptionFilter(event_types=frozenset({"a"})))
        d = sub.to_dict()
        assert d["chat_id"] == 1
        assert d["filter"]["event_types"] == ["a"]


# --------------------------------------------------------------------------- #
# TelegramClient
# --------------------------------------------------------------------------- #


def _make_client(handler, *, sleep=None) -> TelegramClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return TelegramClient(
        "test-token",
        http_client=http,
        sleep=sleep or (lambda _t: asyncio.sleep(0)),
    )


class TestTelegramClient:
    def test_token_required(self):
        with pytest.raises(ValueError):
            TelegramClient("")

    def test_repr_hides_token(self):
        client = TelegramClient("SECRET-TOKEN-DO-NOT-LEAK")
        assert "SECRET" not in repr(client)
        assert "redacted" in repr(client)

    @pytest.mark.anyio
    async def test_send_message_success(self):
        seen: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

        client = _make_client(handler)
        try:
            result = await client.send_message(999, "hello", parse_mode="MarkdownV2")
        finally:
            await client.aclose()

        assert result == {"message_id": 42}
        assert seen[0]["chat_id"] == 999
        assert seen[0]["text"] == "hello"
        assert seen[0]["parse_mode"] == "MarkdownV2"
        assert seen[0]["disable_web_page_preview"] is True

    @pytest.mark.anyio
    async def test_permanent_4xx_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"ok": False, "description": "chat not found"})

        client = _make_client(handler)
        try:
            with pytest.raises(TelegramAPIError) as excinfo:
                await client.send_message(1, "x")
        finally:
            await client.aclose()
        assert excinfo.value.status_code == 400
        assert "chat not found" in excinfo.value.description

    @pytest.mark.anyio
    async def test_5xx_retries_then_succeeds(self):
        counter = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            counter["n"] += 1
            if counter["n"] < 3:
                return httpx.Response(503, json={"ok": False, "description": "busy"})
            return httpx.Response(200, json={"ok": True, "result": {}})

        client = _make_client(handler)
        try:
            await client.send_message(1, "x")
        finally:
            await client.aclose()
        assert counter["n"] == 3

    @pytest.mark.anyio
    async def test_5xx_retries_exhausted_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"ok": False, "description": "oops"})

        client = _make_client(handler)
        try:
            with pytest.raises(TelegramAPIError) as excinfo:
                await client.send_message(1, "x")
        finally:
            await client.aclose()
        assert excinfo.value.status_code == 500

    @pytest.mark.anyio
    async def test_429_honours_retry_after_body(self):
        counter = {"n": 0}
        seen_sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            seen_sleeps.append(seconds)

        def handler(request: httpx.Request) -> httpx.Response:
            counter["n"] += 1
            if counter["n"] == 1:
                return httpx.Response(
                    429,
                    json={
                        "ok": False,
                        "description": "Too Many Requests",
                        "parameters": {"retry_after": 2},
                    },
                )
            return httpx.Response(200, json={"ok": True, "result": {}})

        client = _make_client(handler, sleep=fake_sleep)
        try:
            await client.send_message(1, "x")
        finally:
            await client.aclose()
        assert 2.0 in seen_sleeps

    @pytest.mark.anyio
    async def test_429_falls_back_to_header(self):
        counter = {"n": 0}
        seen_sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            seen_sleeps.append(seconds)

        def handler(request: httpx.Request) -> httpx.Response:
            counter["n"] += 1
            if counter["n"] == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "3"},
                    json={"ok": False, "description": "TMR"},
                )
            return httpx.Response(200, json={"ok": True, "result": {}})

        client = _make_client(handler, sleep=fake_sleep)
        try:
            await client.send_message(1, "x")
        finally:
            await client.aclose()
        assert 3.0 in seen_sleeps

    @pytest.mark.anyio
    async def test_transport_error_retried(self):
        counter = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            counter["n"] += 1
            if counter["n"] < 2:
                raise httpx.ConnectError("boom", request=request)
            return httpx.Response(200, json={"ok": True, "result": {}})

        client = _make_client(handler)
        try:
            await client.send_message(1, "x")
        finally:
            await client.aclose()
        assert counter["n"] == 2

    @pytest.mark.anyio
    async def test_ok_false_2xx_still_raises(self):
        """Telegram 200 with ok=false is a permanent error."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": False, "description": "wat"})

        client = _make_client(handler)
        try:
            with pytest.raises(TelegramAPIError):
                await client.send_message(1, "x")
        finally:
            await client.aclose()


# --------------------------------------------------------------------------- #
# TelegramBridge
# --------------------------------------------------------------------------- #


class _StubClient:
    """In-memory replacement for :class:`TelegramClient` used by bridge tests."""

    def __init__(self, *, fail_for: set[int] | None = None) -> None:
        self.sent: list[tuple[int, str, str]] = []
        self.fail_for = fail_for or set()

    async def send_message(self, chat_id, text, *, parse_mode="MarkdownV2", disable_web_page_preview=True):
        if chat_id in self.fail_for:
            raise TelegramAPIError(500, "stub failure")
        self.sent.append((chat_id, text, parse_mode))


class TestTelegramBridge:
    @pytest.mark.anyio
    async def test_delivers_only_to_matching(self):
        reg = SubscriptionRegistry()
        wildcard = reg.add(111, SubscriptionFilter())
        typed = reg.add(222, SubscriptionFilter(event_types=frozenset({"escrow_released"})))
        client = _StubClient()
        bridge = TelegramBridge(client, reg)

        delivered = await bridge.dispatch({"type": "escrow_released", "service_hash": "x"})

        assert set(delivered) == {wildcard.sub_id, typed.sub_id}
        assert sorted(c for c, _t, _p in client.sent) == [111, 222]

    @pytest.mark.anyio
    async def test_skips_non_matching(self):
        reg = SubscriptionRegistry()
        reg.add(111, SubscriptionFilter(event_types=frozenset({"escrow_released"})))
        client = _StubClient()
        bridge = TelegramBridge(client, reg)

        delivered = await bridge.dispatch({"type": "escrow_created"})
        assert delivered == []
        assert client.sent == []

    @pytest.mark.anyio
    async def test_one_failure_does_not_block_others(self):
        reg = SubscriptionRegistry()
        good = reg.add(111, SubscriptionFilter())
        reg.add(222, SubscriptionFilter())
        client = _StubClient(fail_for={222})
        bridge = TelegramBridge(client, reg)

        delivered = await bridge.dispatch({"type": "escrow_released"})
        assert delivered == [good.sub_id]
        assert [c for c, _t, _p in client.sent] == [111]

    @pytest.mark.anyio
    async def test_formatter_called_once_per_dispatch(self):
        reg = SubscriptionRegistry()
        reg.add(111, SubscriptionFilter())
        reg.add(222, SubscriptionFilter())

        calls = {"n": 0}
        base = EventFormatter()

        class SpyFormatter(EventFormatter):
            def format(self, event):
                calls["n"] += 1
                return base.format(event)

        client = _StubClient()
        bridge = TelegramBridge(client, reg, formatter=SpyFormatter())
        await bridge.dispatch({"type": "escrow_released"})
        assert calls["n"] == 1

    @pytest.mark.anyio
    async def test_no_subscribers_short_circuits(self):
        reg = SubscriptionRegistry()
        client = _StubClient()
        bridge = TelegramBridge(client, reg)
        assert await bridge.dispatch({"type": "escrow_released"}) == []
        assert client.sent == []

    def test_max_concurrency_validated(self):
        with pytest.raises(ValueError):
            TelegramBridge(_StubClient(), SubscriptionRegistry(), max_concurrency=0)


# --------------------------------------------------------------------------- #
# Anyio fixture
# --------------------------------------------------------------------------- #


@pytest.fixture
def anyio_backend():
    return "asyncio"
