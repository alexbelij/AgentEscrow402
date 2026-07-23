"""Tests for server/audit_log.py — AE-Audit (append-only Merkle-signed audit log).

Covers:
  1. Append-only hash chain: each entry links to the previous.
  2. Tampering with any past entry breaks `verify_chain`.
  3. Reordering entries breaks `verify_chain`.
  4. Genesis entry links to the well-defined GENESIS_HASH.
  5. Checkpoint Merkle root is deterministic and sensitive to entry changes.
  6. Signed checkpoint verifies against the correct entries/key.
  7. Signed checkpoint rejects wrong key, tampered signature, tampered root,
     wrong seq range, and mismatched entries.
  8. Canonical payload hashing is order-independent (dict key order).
  9. Empty-checkpoint edge cases mirror merkle_provenance's empty-batch root.
  10. AuditLog convenience wrapper: append/verify/checkpoint round trip.
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server.audit_log import (
    GENESIS_HASH,
    AuditLog,
    AuditLogEntry,
    compute_checkpoint_root,
    sign_checkpoint,
    verify_chain,
    verify_checkpoint_against_entries,
    verify_checkpoint_signature,
)


def _make_entry(seq: int, event_type: str, payload_hash: str, timestamp: int, prev_hash: str) -> AuditLogEntry:
    return AuditLogEntry(seq=seq, event_type=event_type, payload_hash=payload_hash, timestamp=timestamp, prev_hash=prev_hash)


class TestHashChain:
    def test_first_entry_links_to_genesis(self):
        log = AuditLog()
        entry = log.append("escrow_created", {"escrow_id": "a" * 64})
        assert entry.prev_hash == GENESIS_HASH
        assert entry.seq == 0

    def test_chain_links_sequentially(self):
        log = AuditLog()
        e0 = log.append("escrow_created", {"escrow_id": "a" * 64})
        e1 = log.append("escrow_released", {"escrow_id": "a" * 64})
        e2 = log.append("dispute_opened", {"escrow_id": "a" * 64})
        assert e1.prev_hash == e0.entry_hash
        assert e2.prev_hash == e1.entry_hash

    def test_verify_chain_true_for_untouched_log(self):
        log = AuditLog()
        for i in range(5):
            log.append("event", {"i": i})
        assert log.verify() is True
        assert verify_chain(log.entries) is True

    def test_entry_hash_is_deterministic(self):
        e1 = _make_entry(0, "event", "deadbeef", 1000, GENESIS_HASH)
        e2 = _make_entry(0, "event", "deadbeef", 1000, GENESIS_HASH)
        assert e1.entry_hash == e2.entry_hash

    def test_entry_hash_changes_with_any_field(self):
        base = _make_entry(0, "event", "deadbeef", 1000, GENESIS_HASH)
        variants = [
            _make_entry(1, "event", "deadbeef", 1000, GENESIS_HASH),
            _make_entry(0, "other_event", "deadbeef", 1000, GENESIS_HASH),
            _make_entry(0, "event", "cafebabe", 1000, GENESIS_HASH),
            _make_entry(0, "event", "deadbeef", 1001, GENESIS_HASH),
        ]
        for v in variants:
            assert v.entry_hash != base.entry_hash

    def test_constructing_entry_with_wrong_precomputed_hash_raises(self):
        with pytest.raises(ValueError):
            AuditLogEntry(
                seq=0,
                event_type="event",
                payload_hash="deadbeef",
                timestamp=1000,
                prev_hash=GENESIS_HASH,
                entry_hash="0" * 64,
            )


class TestTamperEvidence:
    def test_tampering_with_past_entry_payload_breaks_chain(self):
        log = AuditLog()
        log.append("escrow_created", {"amount": 100})
        log.append("escrow_released", {"amount": 100})
        entries = log.entries
        # Simulate an attacker rewriting entry 0's payload_hash without
        # recomputing downstream hashes -- entry 0 itself is now
        # internally inconsistent (its own entry_hash no longer matches
        # its fields), which is exactly the kind of forgery Ed25519
        # signing + hash-chaining is meant to catch. Constructing a
        # rewritten entry directly bypasses AuditLogEntry's own
        # self-check, mimicking an attacker editing serialized log data.
        tampered = object.__new__(AuditLogEntry)
        object.__setattr__(tampered, "seq", entries[0].seq)
        object.__setattr__(tampered, "event_type", entries[0].event_type)
        object.__setattr__(tampered, "payload_hash", "0" * 64)  # forged
        object.__setattr__(tampered, "timestamp", entries[0].timestamp)
        object.__setattr__(tampered, "prev_hash", entries[0].prev_hash)
        object.__setattr__(tampered, "entry_hash", entries[0].entry_hash)  # stale, now wrong
        tampered_chain = [tampered, entries[1]]
        assert verify_chain(tampered_chain) is False

    def test_deleting_a_middle_entry_breaks_chain(self):
        log = AuditLog()
        for i in range(4):
            log.append("event", {"i": i})
        entries = log.entries
        spliced = [entries[0], entries[2], entries[3]]  # drop entries[1]
        assert verify_chain(spliced) is False

    def test_reordering_entries_breaks_chain(self):
        log = AuditLog()
        for i in range(3):
            log.append("event", {"i": i})
        entries = log.entries
        reordered = [entries[1], entries[0], entries[2]]
        assert verify_chain(reordered) is False

    def test_wrong_genesis_hash_breaks_first_link(self):
        log = AuditLog()
        log.append("event", {"i": 0})
        assert verify_chain(log.entries, genesis_hash="0" * 64) is False


class TestCheckpointRoot:
    def test_root_deterministic(self):
        log = AuditLog()
        for i in range(5):
            log.append("event", {"i": i})
        root1 = compute_checkpoint_root(log.entries)
        root2 = compute_checkpoint_root(log.entries)
        assert root1 == root2

    def test_root_sensitive_to_entry_change(self):
        log_a = AuditLog()
        log_b = AuditLog()
        for i in range(4):
            log_a.append("event", {"i": i}, timestamp=1000 + i)
            log_b.append("event", {"i": i}, timestamp=1000 + i)
        # diverge log_b's last entry's timestamp
        assert compute_checkpoint_root(log_a.entries) == compute_checkpoint_root(log_b.entries)
        log_b.append("event", {"i": 999})
        assert compute_checkpoint_root(log_a.entries) != compute_checkpoint_root(log_b.entries)

    def test_empty_checkpoint_matches_merkle_provenance_empty_root(self):
        from server.merkle_provenance import compute_merkle_root

        assert compute_checkpoint_root([]) == compute_merkle_root([])

    def test_odd_and_even_sized_checkpoints_both_produce_roots(self):
        log = AuditLog()
        for i in range(3):
            log.append("event", {"i": i})
        odd_root = compute_checkpoint_root(log.entries)
        log.append("event", {"i": 3})
        even_root = compute_checkpoint_root(log.entries)
        assert odd_root != even_root
        assert isinstance(odd_root, str) and len(odd_root) == 64
        assert isinstance(even_root, str) and len(even_root) == 64


class TestSignedCheckpoint:
    def _key(self) -> Ed25519PrivateKey:
        return Ed25519PrivateKey.generate()

    def test_sign_and_verify_round_trip(self):
        log = AuditLog()
        for i in range(6):
            log.append("event", {"i": i})
        key = self._key()
        checkpoint = log.checkpoint(key)
        assert verify_checkpoint_signature(checkpoint) is True
        assert verify_checkpoint_against_entries(checkpoint, log.entries) is True

    def test_checkpoint_covers_correct_seq_range(self):
        log = AuditLog()
        for i in range(6):
            log.append("event", {"i": i})
        key = self._key()
        checkpoint = log.checkpoint(key)
        assert checkpoint.start_seq == 0
        assert checkpoint.end_seq == 5

    def test_partial_checkpoint_since_seq(self):
        log = AuditLog()
        for i in range(6):
            log.append("event", {"i": i})
        key = self._key()
        checkpoint = log.checkpoint(key, since_seq=3)
        assert checkpoint.start_seq == 3
        assert checkpoint.end_seq == 5
        partial_entries = [e for e in log.entries if e.seq >= 3]
        assert verify_checkpoint_against_entries(checkpoint, partial_entries) is True
        # verifying against the FULL entry list (wrong slice) must fail
        assert verify_checkpoint_against_entries(checkpoint, log.entries) is False

    def test_wrong_key_signature_rejected(self):
        log = AuditLog()
        for i in range(3):
            log.append("event", {"i": i})
        checkpoint = sign_checkpoint(self._key(), log.entries)
        # Re-sign with a different key but keep the original pubkey_hex
        # to simulate a forged signature under a claimed identity.
        forged_sig_checkpoint = sign_checkpoint(self._key(), log.entries)
        tampered = checkpoint.__class__(
            root=checkpoint.root,
            start_seq=checkpoint.start_seq,
            end_seq=checkpoint.end_seq,
            signature_hex=forged_sig_checkpoint.signature_hex,  # signature from a different key
            pubkey_hex=checkpoint.pubkey_hex,  # but claims the original pubkey
        )
        assert verify_checkpoint_signature(tampered) is False

    def test_tampered_root_rejected(self):
        log = AuditLog()
        for i in range(3):
            log.append("event", {"i": i})
        key = self._key()
        checkpoint = sign_checkpoint(key, log.entries)
        tampered = checkpoint.__class__(
            root="0" * 64,
            start_seq=checkpoint.start_seq,
            end_seq=checkpoint.end_seq,
            signature_hex=checkpoint.signature_hex,
            pubkey_hex=checkpoint.pubkey_hex,
        )
        assert verify_checkpoint_signature(tampered) is False

    def test_tampered_seq_range_rejected(self):
        log = AuditLog()
        for i in range(5):
            log.append("event", {"i": i})
        key = self._key()
        checkpoint = sign_checkpoint(key, log.entries)
        tampered = checkpoint.__class__(
            root=checkpoint.root,
            start_seq=checkpoint.start_seq,
            end_seq=checkpoint.end_seq + 1,  # claim coverage of one more entry
            signature_hex=checkpoint.signature_hex,
            pubkey_hex=checkpoint.pubkey_hex,
        )
        assert verify_checkpoint_signature(tampered) is False

    def test_verify_against_entries_fails_if_root_recompute_mismatches(self):
        log_a = AuditLog()
        log_b = AuditLog()
        for i in range(4):
            log_a.append("event", {"i": i})
            log_b.append("event", {"i": i * 2})  # different payloads
        key = self._key()
        checkpoint = sign_checkpoint(key, log_a.entries)
        assert verify_checkpoint_against_entries(checkpoint, log_b.entries) is False

    def test_sign_checkpoint_rejects_empty_entries(self):
        key = self._key()
        with pytest.raises(ValueError):
            sign_checkpoint(key, [])

    def test_malformed_hex_in_checkpoint_rejected_not_raised(self):
        log = AuditLog()
        log.append("event", {"i": 0})
        key = self._key()
        checkpoint = sign_checkpoint(key, log.entries)
        malformed = checkpoint.__class__(
            root=checkpoint.root,
            start_seq=checkpoint.start_seq,
            end_seq=checkpoint.end_seq,
            signature_hex="not-hex-at-all",
            pubkey_hex=checkpoint.pubkey_hex,
        )
        assert verify_checkpoint_signature(malformed) is False


class TestCanonicalPayloadHashing:
    def test_payload_hash_independent_of_key_order(self):
        log_a = AuditLog()
        log_b = AuditLog()
        entry_a = log_a.append("event", {"a": 1, "b": 2, "escrow_id": "x"})
        entry_b = log_b.append("event", {"escrow_id": "x", "b": 2, "a": 1})
        assert entry_a.payload_hash == entry_b.payload_hash

    def test_payload_hash_changes_with_value(self):
        log = AuditLog()
        e1 = log.append("event", {"amount": 100})
        log2 = AuditLog()
        e2 = log2.append("event", {"amount": 200})
        assert e1.payload_hash != e2.payload_hash


class TestAuditLogWrapper:
    def test_entries_property_returns_a_copy(self):
        log = AuditLog()
        log.append("event", {"i": 0})
        snapshot = log.entries
        log.append("event", {"i": 1})
        assert len(snapshot) == 1
        assert len(log.entries) == 2

    def test_full_workflow_append_checkpoint_verify(self):
        log = AuditLog()
        events = [
            ("escrow_created", {"escrow_id": "a" * 64, "amount": 1000}),
            ("dispute_opened", {"escrow_id": "a" * 64, "reason": "non-delivery"}),
            ("arbiter_elected", {"escrow_id": "a" * 64, "arbiter": "b" * 64}),
            ("escrow_resolved", {"escrow_id": "a" * 64, "verdict": "sender"}),
        ]
        for event_type, payload in events:
            log.append(event_type, payload)

        assert log.verify() is True

        key = Ed25519PrivateKey.generate()
        checkpoint = log.checkpoint(key)
        assert verify_checkpoint_against_entries(checkpoint, log.entries) is True
