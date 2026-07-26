"""Tests for the arbiter commit-reveal scheme (MEV resistance)."""

from __future__ import annotations

import secrets

import pytest

from server.arbiter_commit_reveal import (
    CommitRevealError,
    Reveal,
    build_commit,
    verify_reveal,
)


def _pubkey() -> str:
    return secrets.token_hex(33)


def _salt() -> str:
    return secrets.token_hex(16)


# --- Determinism --------------------------------------------------------- #


def test_same_inputs_same_commit() -> None:
    pk = _pubkey()
    salt = _salt()
    c1 = build_commit(verdict="claimant", salt_hex=salt, arbiter_pubkey_hex=pk)
    c2 = build_commit(verdict="claimant", salt_hex=salt, arbiter_pubkey_hex=pk)
    assert c1 == c2


def test_different_verdict_gives_different_commit() -> None:
    pk = _pubkey()
    salt = _salt()
    a = build_commit(verdict="claimant", salt_hex=salt, arbiter_pubkey_hex=pk)
    b = build_commit(verdict="respondent", salt_hex=salt, arbiter_pubkey_hex=pk)
    assert a.commit_hash_hex != b.commit_hash_hex


def test_different_salt_gives_different_commit() -> None:
    pk = _pubkey()
    a = build_commit(verdict="claimant", salt_hex=_salt(), arbiter_pubkey_hex=pk)
    b = build_commit(verdict="claimant", salt_hex=_salt(), arbiter_pubkey_hex=pk)
    assert a.commit_hash_hex != b.commit_hash_hex


def test_different_arbiter_gives_different_commit() -> None:
    salt = _salt()
    a = build_commit(
        verdict="claimant", salt_hex=salt, arbiter_pubkey_hex=_pubkey()
    )
    b = build_commit(
        verdict="claimant", salt_hex=salt, arbiter_pubkey_hex=_pubkey()
    )
    assert a.commit_hash_hex != b.commit_hash_hex


# --- Verify ------------------------------------------------------------- #


def test_reveal_matches_own_commit() -> None:
    pk = _pubkey()
    salt = _salt()
    c = build_commit(verdict="claimant", salt_hex=salt, arbiter_pubkey_hex=pk)
    reveal = Reveal(arbiter_pubkey_hex=pk, verdict="claimant", salt_hex=salt)
    assert verify_reveal(reveal=reveal, expected_commit_hex=c.commit_hash_hex)


def test_reveal_rejects_wrong_verdict() -> None:
    pk = _pubkey()
    salt = _salt()
    c = build_commit(verdict="claimant", salt_hex=salt, arbiter_pubkey_hex=pk)
    reveal = Reveal(arbiter_pubkey_hex=pk, verdict="respondent", salt_hex=salt)
    assert not verify_reveal(reveal=reveal, expected_commit_hex=c.commit_hash_hex)


def test_reveal_rejects_wrong_salt() -> None:
    pk = _pubkey()
    c = build_commit(verdict="claimant", salt_hex=_salt(), arbiter_pubkey_hex=pk)
    reveal = Reveal(
        arbiter_pubkey_hex=pk, verdict="claimant", salt_hex=_salt()
    )
    assert not verify_reveal(reveal=reveal, expected_commit_hex=c.commit_hash_hex)


def test_reveal_rejects_wrong_arbiter() -> None:
    salt = _salt()
    c = build_commit(
        verdict="claimant", salt_hex=salt, arbiter_pubkey_hex=_pubkey()
    )
    reveal = Reveal(
        arbiter_pubkey_hex=_pubkey(), verdict="claimant", salt_hex=salt
    )
    assert not verify_reveal(reveal=reveal, expected_commit_hex=c.commit_hash_hex)


def test_reveal_rejects_garbage_expected_hash() -> None:
    pk = _pubkey()
    salt = _salt()
    reveal = Reveal(arbiter_pubkey_hex=pk, verdict="claimant", salt_hex=salt)
    assert not verify_reveal(reveal=reveal, expected_commit_hex="deadbeef")


# --- Input validation --------------------------------------------------- #


def test_short_salt_is_rejected() -> None:
    with pytest.raises(CommitRevealError, match="salt must be at least"):
        build_commit(
            verdict="claimant", salt_hex="ab" * 8, arbiter_pubkey_hex=_pubkey()
        )


def test_invalid_verdict_is_rejected() -> None:
    with pytest.raises(CommitRevealError, match="invalid verdict"):
        build_commit(
            verdict="undecided", salt_hex=_salt(), arbiter_pubkey_hex=_pubkey()
        )


def test_empty_pubkey_is_rejected() -> None:
    with pytest.raises(CommitRevealError):
        build_commit(verdict="claimant", salt_hex=_salt(), arbiter_pubkey_hex="")


def test_invalid_hex_is_rejected() -> None:
    with pytest.raises(CommitRevealError):
        build_commit(
            verdict="claimant", salt_hex="xyz", arbiter_pubkey_hex=_pubkey()
        )


def test_valid_verdict_abstain() -> None:
    pk = _pubkey()
    salt = _salt()
    c = build_commit(verdict="abstain", salt_hex=salt, arbiter_pubkey_hex=pk)
    reveal = Reveal(arbiter_pubkey_hex=pk, verdict="abstain", salt_hex=salt)
    assert verify_reveal(reveal=reveal, expected_commit_hex=c.commit_hash_hex)
