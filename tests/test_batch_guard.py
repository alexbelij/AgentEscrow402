"""Tests for `server.batch_guard` — the deterministic batch cap/quorum guard (T3.3)."""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server import arbiter_crypto, batch_guard as bg


# ── Helpers ────────────────────────────────────────────────────────────


def make_snap(sh: str, amount: int, status: str = "pending") -> bg.EscrowSnapshot:
    return bg.EscrowSnapshot(service_hash=sh, status=status, amount_motes=amount)


def make_arbiter() -> tuple[Ed25519PrivateKey, str]:
    sk = Ed25519PrivateKey.generate()
    pk_bytes = sk.public_key().public_bytes_raw()
    return sk, "01" + pk_bytes.hex()


def sign_cap_vote(sk: Ed25519PrivateKey, action: str, sh: str) -> str:
    msg = arbiter_crypto.build_cap_approval_message(action, sh)
    sig = sk.sign(msg)
    return "01" + sig.hex()


def hex64(prefix: str) -> str:
    # Build a canonical-looking service_hash so we can pass it around.
    body = (prefix * (64 // len(prefix) + 1))[:64]
    return body


# ── Structural checks ──────────────────────────────────────────────────


def test_empty_batch_rejected():
    d = bg.evaluate_batch(
        action="release",
        service_hashes=[],
        snapshots={},
        release_cap_motes=1_000,
        arbiter_registered=(),
        arbiter_threshold=1,
    )
    assert not d.admit
    assert d.first_reason == bg.CODE_EMPTY_BATCH


def test_oversize_batch_rejected():
    hashes = [hex64(chr(ord("a") + i % 6) + f"{i:02x}") for i in range(bg.MAX_BATCH_SIZE + 1)]
    # ensure unique hashes
    hashes = [f"{i:064x}" for i in range(bg.MAX_BATCH_SIZE + 1)]
    snaps = {sh: make_snap(sh, 10) for sh in hashes}
    d = bg.evaluate_batch(
        action="release",
        service_hashes=hashes,
        snapshots=snaps,
        release_cap_motes=1_000,
        arbiter_registered=(),
        arbiter_threshold=1,
    )
    assert not d.admit
    codes = [r.code for r in d.rejections]
    assert bg.CODE_BATCH_TOO_LARGE in codes


def test_unknown_action_rejected():
    sh = hex64("a")
    d = bg.evaluate_batch(
        action="terminate",
        service_hashes=[sh],
        snapshots={sh: make_snap(sh, 10)},
        release_cap_motes=1_000,
        arbiter_registered=(),
        arbiter_threshold=1,
    )
    assert not d.admit
    assert d.first_reason == bg.CODE_UNKNOWN_ACTION


def test_arbiter_list_length_mismatch_rejected():
    sh = hex64("a")
    d = bg.evaluate_batch(
        action="release",
        service_hashes=[sh],
        snapshots={sh: make_snap(sh, 10)},
        release_cap_motes=1_000,
        arbiter_registered=(),
        arbiter_threshold=1,
        arbiter_pubkeys=["01aa"],
        arbiter_signatures=[],
    )
    assert not d.admit
    assert bg.CODE_ARBITER_LIST_MISMATCH in [r.code for r in d.rejections]


def test_duplicate_service_hash_rejected():
    sh = hex64("d")
    d = bg.evaluate_batch(
        action="release",
        service_hashes=[sh, sh],
        snapshots={sh: make_snap(sh, 10)},
        release_cap_motes=1_000,
        arbiter_registered=(),
        arbiter_threshold=1,
    )
    assert not d.admit
    codes = [r.code for r in d.rejections]
    assert bg.CODE_DUPLICATE_SERVICE_HASH in codes


# ── Per-escrow checks ──────────────────────────────────────────────────


def test_missing_snapshot_rejected():
    sh = hex64("m")
    d = bg.evaluate_batch(
        action="release",
        service_hashes=[sh],
        snapshots={},
        release_cap_motes=1_000,
        arbiter_registered=(),
        arbiter_threshold=1,
    )
    assert not d.admit
    assert d.first_reason == bg.CODE_ESCROW_NOT_FOUND


def test_non_pending_rejected():
    sh = hex64("p")
    d = bg.evaluate_batch(
        action="release",
        service_hashes=[sh],
        snapshots={sh: make_snap(sh, 10, status="released")},
        release_cap_motes=1_000,
        arbiter_registered=(),
        arbiter_threshold=1,
    )
    assert not d.admit
    codes = [r.code for r in d.rejections]
    assert bg.CODE_ESCROW_NOT_PENDING in codes
    reason = next(r for r in d.rejections if r.code == bg.CODE_ESCROW_NOT_PENDING)
    assert reason.detail["actual_status"] == "released"


# ── Cap / quorum semantics ─────────────────────────────────────────────


def test_all_below_cap_admits_without_arbiter():
    hashes = [f"{i:064x}" for i in range(3)]
    snaps = {sh: make_snap(sh, 100) for sh in hashes}
    d = bg.evaluate_batch(
        action="release",
        service_hashes=hashes,
        snapshots=snaps,
        release_cap_motes=1_000,
        arbiter_registered=("01aa",),  # even with an arbiter set, no quorum needed
        arbiter_threshold=1,
    )
    assert d.admit
    assert not d.needs_quorum
    assert d.above_cap_hashes == ()


def test_above_cap_without_arbiter_registered_admits():
    """Legacy escape-hatch parity: same as inlined app.py logic — if the
    pod hasn't registered arbiters yet, above-cap batches still pass
    (contract on-chain guard is authoritative in live mode)."""
    sh = hex64("h")
    snaps = {sh: make_snap(sh, 10_000)}
    d = bg.evaluate_batch(
        action="release",
        service_hashes=[sh],
        snapshots=snaps,
        release_cap_motes=1_000,
        arbiter_registered=(),  # no arbiters registered
        arbiter_threshold=2,
    )
    assert d.admit
    assert not d.needs_quorum


def test_above_cap_quorum_shortfall_rejected():
    sh = hex64("q")
    _sk_a, pk_a = make_arbiter()
    _sk_b, pk_b = make_arbiter()
    d = bg.evaluate_batch(
        action="release",
        service_hashes=[sh],
        snapshots={sh: make_snap(sh, 10_000)},
        release_cap_motes=1_000,
        arbiter_registered=(pk_a, pk_b),
        arbiter_threshold=2,
        arbiter_pubkeys=[],
        arbiter_signatures=[],
    )
    assert not d.admit
    assert d.first_reason == bg.CODE_QUORUM_SHORTFALL
    assert d.needs_quorum


def test_above_cap_valid_quorum_admits():
    sh = hex64("v")
    sk_a, pk_a = make_arbiter()
    sk_b, pk_b = make_arbiter()
    d = bg.evaluate_batch(
        action="release",
        service_hashes=[sh],
        snapshots={sh: make_snap(sh, 10_000)},
        release_cap_motes=1_000,
        arbiter_registered=(pk_a, pk_b),
        arbiter_threshold=2,
        arbiter_pubkeys=[pk_a, pk_b],
        arbiter_signatures=[sign_cap_vote(sk_a, "release", sh), sign_cap_vote(sk_b, "release", sh)],
    )
    assert d.admit
    assert d.needs_quorum
    assert d.valid_arbiter_votes == 2


def test_vote_bound_to_one_escrow():
    """Vote for escrow A must NOT count toward escrow B in the same batch."""
    sh_a = hex64("a")
    sh_b = hex64("b")
    sk_1, pk_1 = make_arbiter()
    sk_2, pk_2 = make_arbiter()
    snaps = {sh_a: make_snap(sh_a, 10_000), sh_b: make_snap(sh_b, 10_000)}
    # Only sign for sh_a — sh_b should fail
    d = bg.evaluate_batch(
        action="release",
        service_hashes=[sh_a, sh_b],
        snapshots=snaps,
        release_cap_motes=1_000,
        arbiter_registered=(pk_1, pk_2),
        arbiter_threshold=2,
        arbiter_pubkeys=[pk_1, pk_2],
        arbiter_signatures=[sign_cap_vote(sk_1, "release", sh_a), sign_cap_vote(sk_2, "release", sh_a)],
    )
    assert not d.admit
    # sh_b is the one that must fail with quorum_shortfall
    q_reasons = [r for r in d.rejections if r.code == bg.CODE_QUORUM_SHORTFALL]
    assert q_reasons
    assert any(r.service_hash == sh_b for r in q_reasons)


def test_duplicate_pubkey_counts_once():
    """Same signer submitting twice must not double-count toward quorum."""
    sh = hex64("z")
    sk, pk = make_arbiter()
    _, pk_other = make_arbiter()
    sig = sign_cap_vote(sk, "release", sh)
    d = bg.evaluate_batch(
        action="release",
        service_hashes=[sh],
        snapshots={sh: make_snap(sh, 10_000)},
        release_cap_motes=1_000,
        arbiter_registered=(pk, pk_other),
        arbiter_threshold=2,
        arbiter_pubkeys=[pk, pk],
        arbiter_signatures=[sig, sig],
    )
    assert not d.admit
    assert d.first_reason == bg.CODE_QUORUM_SHORTFALL


def test_cancel_never_needs_quorum():
    sh = hex64("c")
    d = bg.evaluate_batch(
        action="cancel",
        service_hashes=[sh],
        snapshots={sh: make_snap(sh, 100_000)},
        release_cap_motes=1_000,
        arbiter_registered=("01aa", "01bb"),
        arbiter_threshold=2,
    )
    assert d.admit
    assert not d.needs_quorum


def test_forged_signature_ignored():
    sh = hex64("f")
    _sk_a, pk_a = make_arbiter()
    _sk_b, pk_b = make_arbiter()
    d = bg.evaluate_batch(
        action="release",
        service_hashes=[sh],
        snapshots={sh: make_snap(sh, 10_000)},
        release_cap_motes=1_000,
        arbiter_registered=(pk_a, pk_b),
        arbiter_threshold=2,
        arbiter_pubkeys=[pk_a, pk_b],
        arbiter_signatures=["01" + "00" * 64, "01" + "ff" * 64],
    )
    assert not d.admit
    assert d.first_reason == bg.CODE_QUORUM_SHORTFALL


def test_action_case_insensitive():
    sh = hex64("u")
    d = bg.evaluate_batch(
        action="RELEASE",
        service_hashes=[sh],
        snapshots={sh: make_snap(sh, 100)},
        release_cap_motes=1_000,
        arbiter_registered=(),
        arbiter_threshold=1,
    )
    assert d.admit
    assert d.action == "release"


def test_deterministic():
    """Same inputs → same output byte-for-byte (relied on by on-chain parity)."""
    sh = hex64("t")
    sk_a, pk_a = make_arbiter()
    sk_b, pk_b = make_arbiter()
    kw = dict(
        action="release",
        service_hashes=[sh],
        snapshots={sh: make_snap(sh, 10_000)},
        release_cap_motes=1_000,
        arbiter_registered=(pk_a, pk_b),
        arbiter_threshold=2,
        arbiter_pubkeys=[pk_a, pk_b],
        arbiter_signatures=[sign_cap_vote(sk_a, "release", sh), sign_cap_vote(sk_b, "release", sh)],
    )
    d1 = bg.evaluate_batch(**kw)
    d2 = bg.evaluate_batch(**kw)
    assert d1 == d2


def test_min_valid_votes_reported():
    """valid_arbiter_votes reports the tightest per-escrow bottleneck."""
    sh_a = hex64("g")
    sh_b = hex64("h")
    sk_1, pk_1 = make_arbiter()
    sk_2, pk_2 = make_arbiter()
    sk_3, pk_3 = make_arbiter()
    snaps = {sh_a: make_snap(sh_a, 10_000), sh_b: make_snap(sh_b, 10_000)}
    # sh_a has 3 valid votes, sh_b has 2 → bottleneck = 2 (equal to threshold)
    d = bg.evaluate_batch(
        action="release",
        service_hashes=[sh_a, sh_b],
        snapshots=snaps,
        release_cap_motes=1_000,
        arbiter_registered=(pk_1, pk_2, pk_3),
        arbiter_threshold=2,
        arbiter_pubkeys=[pk_1, pk_2, pk_3, pk_1, pk_2],
        arbiter_signatures=[
            sign_cap_vote(sk_1, "release", sh_a),
            sign_cap_vote(sk_2, "release", sh_a),
            sign_cap_vote(sk_3, "release", sh_a),
            sign_cap_vote(sk_1, "release", sh_b),
            sign_cap_vote(sk_2, "release", sh_b),
        ],
    )
    assert d.admit
    assert d.valid_arbiter_votes == 2  # bottleneck


def test_ordering_of_rejections_stable():
    """Rejections are returned in the order encountered."""
    hashes = [f"{i:064x}" for i in range(3)]
    snaps = {
        hashes[0]: make_snap(hashes[0], 10, status="released"),
        hashes[1]: make_snap(hashes[1], 10, status="cancelled"),
        # hashes[2] missing entirely
    }
    d = bg.evaluate_batch(
        action="release",
        service_hashes=hashes,
        snapshots=snaps,
        release_cap_motes=1_000,
        arbiter_registered=(),
        arbiter_threshold=1,
    )
    assert not d.admit
    codes = [r.code for r in d.rejections]
    # 2× not_pending then 1× not_found
    assert codes.count(bg.CODE_ESCROW_NOT_PENDING) == 2
    assert codes.count(bg.CODE_ESCROW_NOT_FOUND) == 1
