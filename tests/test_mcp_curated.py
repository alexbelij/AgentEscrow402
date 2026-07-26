"""Tests for the MCP curated whitelist (G)."""

from __future__ import annotations

from server.mcp_curated import (
    CURATED_TOOL_NAMES,
    CURATED_TOOLS,
    get_curated,
    is_curated,
)


# --- Shape & determinism ------------------------------------------------- #


def test_all_tools_have_required_fields() -> None:
    for t in CURATED_TOOLS:
        assert t.name
        assert t.status in ("stable", "beta", "internal")
        assert isinstance(t.mutates, bool)
        assert isinstance(t.requires_x402, bool)
        assert t.summary and len(t.summary) > 10


def test_names_are_unique() -> None:
    names = [t.name for t in CURATED_TOOLS]
    assert len(names) == len(set(names))


def test_frozenset_matches_list() -> None:
    assert CURATED_TOOL_NAMES == frozenset(t.name for t in CURATED_TOOLS)


# --- Membership --------------------------------------------------------- #


def test_is_curated_true_for_known() -> None:
    assert is_curated("create_escrow") is True
    assert is_curated("get_escrow_status") is True


def test_is_curated_false_for_random() -> None:
    assert is_curated("format_hard_drive") is False
    assert is_curated("") is False
    assert is_curated("CREATE_ESCROW") is False  # case sensitive


def test_get_curated_returns_object() -> None:
    t = get_curated("create_escrow")
    assert t is not None
    assert t.name == "create_escrow"
    assert t.mutates is True
    assert t.requires_x402 is True


def test_get_curated_none_for_unknown() -> None:
    assert get_curated("nonexistent") is None


# --- Safety invariants -------------------------------------------------- #


def test_all_mutating_tools_require_x402() -> None:
    """Any tool that mutates state MUST require X402 payment.

    This is the strong invariant that keeps the MCP surface safe: an
    LLM can't move money without a fresh, signed payment attached.
    """
    for t in CURATED_TOOLS:
        if t.mutates:
            assert t.requires_x402, f"{t.name} mutates but does not require X402"


def test_no_internal_tools_in_curated() -> None:
    """`internal` tools are for tests only; they must not leak into the LLM host."""
    for t in CURATED_TOOLS:
        assert t.status != "internal", (
            f"{t.name} is `internal` but is in the curated list — "
            "remove it or promote it to beta/stable first"
        )


def test_stable_tools_have_stable_summaries() -> None:
    """A stable tool's summary length must be within 20–200 chars.

    Prevents accidental "TODO" or gigantic prompt-injectable strings
    from landing in the curated list.
    """
    for t in CURATED_TOOLS:
        if t.status == "stable":
            assert 20 <= len(t.summary) <= 200, (
                f"{t.name}: summary is {len(t.summary)} chars"
            )
