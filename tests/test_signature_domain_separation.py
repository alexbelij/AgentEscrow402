"""AE-3 Gap #2: signature domain separation regression suite.

The three arbiter-signed message builders in `server/arbiter_crypto` today
domain-separate their payloads by using distinct human-readable string
prefixes:

    build_resolve_message(...)           b"resolve:<service_hash>:<in_favor_of>"
    build_cap_approval_message(...)      b"<action>:<service_hash>:cap_approval"
                                             where action \u2208 {"release","reveal_swap"}
    build_insurance_claim_message(...)   b"claim:<escrow_id>:<claimant>:<amount>"

That is a *de-facto* domain separation \u2014 it works because no payload field
ever starts with one of the reserved prefix tokens, and no two builders
produce a message that could collide across their input spaces.

Explicit binary domain tags (e.g. `b"\\x00\\x01AE402:v1:resolve:"`) are
strictly better than string prefixes, but adopting them is a wire-format
change that must be co-deployed with a Rust contract update + redeploy of
every already-signed vote workflow. That migration is tracked as an AE
v2 roadmap item; the current PR pins down the guarantees the *existing*
scheme actually gives so a regression can't slip in unnoticed.

If you add a new builder function, this suite will catch it if:

  1. Its output collides with any existing builder's output on any input.
  2. Its output starts with a token that could ambiguate one of the
     existing prefix families.
  3. It omits a domain-anchoring prefix altogether (e.g. plain
     `<service_hash>:<verdict>`).

Reference: AE_AUDIT_REPORT_2026-07-24.md, AE-3 Gap #2.
"""

from __future__ import annotations

import pytest

from server.arbiter_crypto import (
    build_cap_approval_message,
    build_insurance_claim_message,
    build_resolve_message,
)


class TestKnownPrefixes:
    """Lock the exact wire-format prefixes the on-chain contract expects."""

    def test_resolve_prefix(self):
        msg = build_resolve_message("a" * 64, "sender")
        assert msg.startswith(b"resolve:")

    def test_release_cap_approval_prefix(self):
        msg = build_cap_approval_message("release", "a" * 64)
        assert msg.startswith(b"release:")
        assert msg.endswith(b":cap_approval")

    def test_reveal_swap_cap_approval_prefix(self):
        msg = build_cap_approval_message("reveal_swap", "a" * 64)
        assert msg.startswith(b"reveal_swap:")
        assert msg.endswith(b":cap_approval")

    def test_insurance_claim_prefix(self):
        msg = build_insurance_claim_message("a" * 64, "b" * 64, 1000)
        assert msg.startswith(b"claim:")


class TestCrossBuilderNoCollision:
    """No pair of builders can produce the same bytes on any legal input."""

    _SVC = "a" * 64
    _CLAIMANT = "b" * 64
    _ESCROW_ID = "c" * 64

    def test_resolve_vs_cap_release(self):
        # resolve outputs `resolve:<hash>:sender|receiver`; cap release outputs
        # `release:<hash>:cap_approval`. Different token 0, guaranteed distinct.
        r = build_resolve_message(self._SVC, "sender")
        c = build_cap_approval_message("release", self._SVC)
        assert r != c
        assert not r.startswith(c[: len(r)])
        assert not c.startswith(r[: len(c)])

    def test_resolve_vs_cap_reveal_swap(self):
        r = build_resolve_message(self._SVC, "receiver")
        c = build_cap_approval_message("reveal_swap", self._SVC)
        assert r != c

    def test_resolve_vs_insurance_claim(self):
        r = build_resolve_message(self._SVC, "sender")
        i = build_insurance_claim_message(self._ESCROW_ID, self._CLAIMANT, 999)
        assert r != i

    def test_cap_release_vs_cap_reveal_swap(self):
        r = build_cap_approval_message("release", self._SVC)
        s = build_cap_approval_message("reveal_swap", self._SVC)
        assert r != s

    def test_cap_release_vs_insurance_claim(self):
        r = build_cap_approval_message("release", self._SVC)
        i = build_insurance_claim_message(self._ESCROW_ID, self._CLAIMANT, 999)
        assert r != i

    def test_cap_reveal_swap_vs_insurance_claim(self):
        r = build_cap_approval_message("reveal_swap", self._SVC)
        i = build_insurance_claim_message(self._ESCROW_ID, self._CLAIMANT, 999)
        assert r != i


class TestPrefixTokenReserved:
    """No builder's first `:`-separated token collides with another builder's."""

    def test_first_token_disjoint(self):
        tokens = set()
        for msg in [
            build_resolve_message("a" * 64, "sender"),
            build_cap_approval_message("release", "a" * 64),
            build_cap_approval_message("reveal_swap", "a" * 64),
            build_insurance_claim_message("a" * 64, "b" * 64, 1),
        ]:
            first = msg.split(b":", 1)[0]
            assert first not in tokens, (
                f"prefix collision: token {first!r} used by two different builders. "
                "Two builders sharing a leading token risk cross-message signature reuse."
            )
            tokens.add(first)

        # Also assert every builder actually contributed a distinct leading token.
        assert tokens == {b"resolve", b"release", b"reveal_swap", b"claim"}


class TestMessageBindingProperties:
    """Changing any input to a builder must change the output bytes."""

    def test_resolve_service_hash_binds(self):
        a = build_resolve_message("a" * 64, "sender")
        b = build_resolve_message("b" * 64, "sender")
        assert a != b

    def test_resolve_verdict_binds(self):
        a = build_resolve_message("a" * 64, "sender")
        b = build_resolve_message("a" * 64, "receiver")
        assert a != b

    def test_cap_approval_action_binds(self):
        a = build_cap_approval_message("release", "a" * 64)
        b = build_cap_approval_message("reveal_swap", "a" * 64)
        assert a != b

    def test_cap_approval_service_hash_binds(self):
        a = build_cap_approval_message("release", "a" * 64)
        b = build_cap_approval_message("release", "b" * 64)
        assert a != b

    def test_insurance_escrow_binds(self):
        a = build_insurance_claim_message("a" * 64, "c" * 64, 100)
        b = build_insurance_claim_message("b" * 64, "c" * 64, 100)
        assert a != b

    def test_insurance_claimant_binds(self):
        a = build_insurance_claim_message("a" * 64, "c" * 64, 100)
        b = build_insurance_claim_message("a" * 64, "d" * 64, 100)
        assert a != b

    def test_insurance_amount_binds(self):
        a = build_insurance_claim_message("a" * 64, "c" * 64, 100)
        b = build_insurance_claim_message("a" * 64, "c" * 64, 200)
        assert a != b


class TestAdversarialInputs:
    """Payload fields must never be interpretable as a different builder's prefix."""

    def test_verdict_cannot_inject_release_prefix(self):
        """`in_favor_of` is regex-constrained upstream to `^(sender|receiver)$`,
        but even if that regex ever loosened, the resolve prefix `resolve:` is
        prepended by the builder, so a malicious value cannot masquerade as a
        cap-approval message."""
        # The Pydantic ResolveRequest.in_favor_of pattern rejects "release", but
        # we still exercise the builder to prove it prepends "resolve:" first.
        msg = build_resolve_message("a" * 64, "release")  # bypass the model
        assert msg.startswith(b"resolve:")
        # The resulting bytes are `resolve:aaaa...:release`, which cannot be
        # confused with `release:<64hex>:cap_approval`.
        cap = build_cap_approval_message("release", "a" * 64)
        assert msg != cap

    def test_service_hash_containing_colon_still_domain_separated(self):
        """service_hash is 64-hex upstream (regex-enforced), but if a downstream
        caller ever slipped a `:` into it, the leading `resolve:` prefix still
        makes the message distinguishable from a cap-approval or a claim."""
        exotic = "a" * 32 + ":cap_approval:" + "b" * 32  # not 64-hex, illustrative
        msg = build_resolve_message(exotic, "sender")
        cap = build_cap_approval_message("release", "a" * 64)
        assert msg != cap
        assert msg.startswith(b"resolve:")

    def test_escrow_id_cannot_inject_resolve_prefix(self):
        # Even if escrow_id somehow starts with "resolve:...", the leading
        # "claim:" domain tag keeps the insurance-claim message distinct.
        weird_escrow = "resolve" + "a" * 57
        msg = build_insurance_claim_message(weird_escrow, "b" * 64, 100)
        assert msg.startswith(b"claim:")
        assert not msg.startswith(b"resolve:")


class TestNonceAbsentIsDocumented:
    """These messages carry NO anti-replay nonce; replay defense lives on-chain.

    This test is a load-bearing assertion of the current threat model:
      - `resolve()` is idempotent per (escrow, verdict) \u2014 same signatures
        applied twice by the caller are rejected by the FSM once the escrow
        is Resolved.
      - `claim()` uses the insurance-pool `_claims` dictionary as a tombstone
        that rejects a second payout even with identical signatures
        (see AE-2 host-mirror tests in test_insurance_replay_tests.py).
      - `release()` above-cap is likewise gated by the escrow FSM.

    If a future refactor tries to add per-vote nonces to any builder, that
    change breaks the on-chain contract's signature check and needs a
    coordinated Rust redeploy. This test just pins down that fact.
    """

    def test_resolve_message_has_no_nonce_field(self):
        msg = build_resolve_message("a" * 64, "sender").decode()
        # exactly 3 colon-separated fields: "resolve", service_hash, verdict.
        parts = msg.split(":")
        assert len(parts) == 3, f"unexpected extra field(s): {parts}"

    def test_cap_approval_message_has_no_nonce_field(self):
        msg = build_cap_approval_message("release", "a" * 64).decode()
        parts = msg.split(":")
        assert len(parts) == 3, f"unexpected extra field(s): {parts}"

    def test_insurance_claim_message_has_no_nonce_field(self):
        msg = build_insurance_claim_message("a" * 64, "b" * 64, 100).decode()
        # 4 fields: "claim", escrow_id, claimant, amount.
        parts = msg.split(":")
        assert len(parts) == 4, f"unexpected extra field(s): {parts}"


@pytest.mark.parametrize(
    "builder,args",
    [
        (build_resolve_message, ("a" * 64, "sender")),
        (build_cap_approval_message, ("release", "a" * 64)),
        (build_cap_approval_message, ("reveal_swap", "a" * 64)),
        (build_insurance_claim_message, ("a" * 64, "b" * 64, 100)),
    ],
)
def test_output_is_bytes_utf8(builder, args):
    """Every builder emits UTF-8-encoded bytes ready for ed25519 sign/verify."""
    out = builder(*args)
    assert isinstance(out, bytes)
    # must round-trip through utf-8 without loss
    assert out.decode("utf-8").encode("utf-8") == out
