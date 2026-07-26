"""Test suite for the detached-signature envelope module.

Covers every failure mode the module *promises* to detect so a
regression cannot silently reopen an attack surface:

* Happy path (ed25519 + secp256k1).
* Cross-domain replay: same signature, different domain → rejected.
* Cross-purpose replay within one chain.
* Cross-chain replay within one purpose.
* Version drift.
* Timestamp too old / too far in the future.
* Nonce reuse (in-memory store).
* Nonce reuse (SQLite store surviving reconnection).
* Tampered payload.
* Tampered signature.
* Unknown purpose / unknown algorithm.
* Bad-format nonces.
* JSON canonicalization is deterministic (round-trip).
"""

from __future__ import annotations

import json
import os
import tempfile
import time

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server.signed_envelope import (
    DEFAULT_REPLAY_WINDOW_SECONDS,
    KNOWN_PURPOSES,
    DomainSeparator,
    PersistentNonceStore,
    SignedEnvelope,
    build_signing_bytes,
    sign_envelope_ed25519,
    verify_envelope,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fresh_ed25519() -> tuple[bytes, bytes]:
    sk = os.urandom(32)
    priv = Ed25519PrivateKey.from_private_bytes(sk)
    pk = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return sk, pk


def _sign_secp256k1(private_key: ec.EllipticCurvePrivateKey, message: bytes) -> str:
    """Produce a compact (r||s) secp256k1 signature over SHA-256(message)."""
    digest = __import__("hashlib").sha256(message).digest()
    der_sig = private_key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    r, s = utils.decode_dss_signature(der_sig)
    return r.to_bytes(32, "big").hex() + s.to_bytes(32, "big").hex()


@pytest.fixture
def domain() -> DomainSeparator:
    return DomainSeparator(
        protocol="AgentEscrow402",
        version="v1",
        chain_id="casper-testnet",
        purpose="escrow.deposit",
    )


@pytest.fixture
def keys() -> tuple[bytes, bytes]:
    return _fresh_ed25519()


@pytest.fixture
def payload() -> dict:
    return {
        "escrow_id": "0xabc",
        "amount_motes": 5_000_000_000,
        "sender": "acct-hash-A",
        "receiver": "acct-hash-B",
    }


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_happy_path_ed25519(domain, keys, payload):
    sk, pk = keys
    env = sign_envelope_ed25519(
        domain=domain,
        payload=payload,
        nonce="n-happy-1",
        timestamp=int(time.time()),
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    r = verify_envelope(env, expected_domain=domain)
    assert r.ok is True
    assert r.reason == "ok"


def test_happy_path_secp256k1(domain, payload):
    priv = ec.generate_private_key(ec.SECP256K1())
    pub_bytes = priv.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.CompressedPoint,
    )
    stub = SignedEnvelope(
        domain=domain,
        payload=payload,
        signer_pubkey_hex=pub_bytes.hex(),
        algorithm="secp256k1",
        nonce="n-secp-1",
        timestamp=int(time.time()),
        signature_hex="",
    )
    signing_bytes = build_signing_bytes(stub)
    sig_hex = _sign_secp256k1(priv, signing_bytes)
    env = SignedEnvelope(
        domain=stub.domain,
        payload=stub.payload,
        signer_pubkey_hex=stub.signer_pubkey_hex,
        algorithm=stub.algorithm,
        nonce=stub.nonce,
        timestamp=stub.timestamp,
        signature_hex=sig_hex,
    )
    r = verify_envelope(env, expected_domain=domain)
    assert r.ok, r


# ---------------------------------------------------------------------------
# Cross-domain replay
# ---------------------------------------------------------------------------


def test_cross_chain_replay_rejected(domain, keys, payload):
    sk, pk = keys
    env = sign_envelope_ed25519(
        domain=domain,
        payload=payload,
        nonce="n-xchain",
        timestamp=int(time.time()),
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    other = DomainSeparator(
        protocol=domain.protocol,
        version=domain.version,
        chain_id="casper-mainnet",  # attacker replays to mainnet
        purpose=domain.purpose,
    )
    r = verify_envelope(env, expected_domain=other)
    assert r.ok is False
    assert r.reason == "domain_mismatch"


def test_cross_purpose_replay_rejected(domain, keys, payload):
    sk, pk = keys
    env = sign_envelope_ed25519(
        domain=domain,
        payload=payload,
        nonce="n-xpurp1",
        timestamp=int(time.time()),
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    other = DomainSeparator(
        protocol=domain.protocol,
        version=domain.version,
        chain_id=domain.chain_id,
        purpose="escrow.release",  # attacker tries to release using a deposit sig
    )
    r = verify_envelope(env, expected_domain=other)
    assert r.ok is False
    assert r.reason == "domain_mismatch"


def test_version_drift_rejected(domain, keys, payload):
    sk, pk = keys
    env = sign_envelope_ed25519(
        domain=domain,
        payload=payload,
        nonce="n-vdrift",
        timestamp=int(time.time()),
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    other = DomainSeparator(
        protocol=domain.protocol,
        version="v2",  # verifier upgraded, sender not
        chain_id=domain.chain_id,
        purpose=domain.purpose,
    )
    r = verify_envelope(env, expected_domain=other)
    assert r.ok is False
    assert r.reason == "domain_mismatch"


def test_cross_protocol_replay_rejected(domain, keys, payload):
    """Same signature, sender pretends it was for a different protocol."""
    sk, pk = keys
    env = sign_envelope_ed25519(
        domain=domain,
        payload=payload,
        nonce="n-xproto",
        timestamp=int(time.time()),
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    other = DomainSeparator(
        protocol="CasperProver",  # sibling protocol tries to accept AE402 sig
        version=domain.version,
        chain_id=domain.chain_id,
        purpose=domain.purpose,
    )
    r = verify_envelope(env, expected_domain=other)
    assert r.ok is False
    assert r.reason == "domain_mismatch"


# ---------------------------------------------------------------------------
# Timestamp window
# ---------------------------------------------------------------------------


def test_timestamp_stale_rejected(domain, keys, payload):
    sk, pk = keys
    old_ts = int(time.time()) - DEFAULT_REPLAY_WINDOW_SECONDS - 5
    env = sign_envelope_ed25519(
        domain=domain,
        payload=payload,
        nonce="n-stale1",
        timestamp=old_ts,
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    r = verify_envelope(env, expected_domain=domain)
    assert r.ok is False
    assert r.reason == "timestamp_stale"


def test_timestamp_future_rejected(domain, keys, payload):
    sk, pk = keys
    future_ts = int(time.time()) + DEFAULT_REPLAY_WINDOW_SECONDS + 60
    env = sign_envelope_ed25519(
        domain=domain,
        payload=payload,
        nonce="n-future",
        timestamp=future_ts,
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    r = verify_envelope(env, expected_domain=domain)
    assert r.ok is False
    assert r.reason == "timestamp_future"


# ---------------------------------------------------------------------------
# Nonce store
# ---------------------------------------------------------------------------


def test_nonce_reuse_rejected_in_memory(domain, keys, payload):
    sk, pk = keys
    store = PersistentNonceStore.in_memory()
    ts = int(time.time())
    env = sign_envelope_ed25519(
        domain=domain,
        payload=payload,
        nonce="n-reuse1",
        timestamp=ts,
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    r1 = verify_envelope(env, expected_domain=domain, nonce_store=store)
    assert r1.ok, r1
    r2 = verify_envelope(env, expected_domain=domain, nonce_store=store)
    assert r2.ok is False
    assert r2.reason == "nonce_reused"


def test_nonce_store_survives_reconnect(domain, keys, payload):
    """A restart of the process must not re-open the replay window."""
    sk, pk = keys
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "nonces.sqlite")
        env = sign_envelope_ed25519(
            domain=domain,
            payload=payload,
            nonce="n-restart",
            timestamp=int(time.time()),
            private_key_bytes=sk,
            public_key_bytes=pk,
        )
        store_a = PersistentNonceStore(path)
        r = verify_envelope(env, expected_domain=domain, nonce_store=store_a)
        assert r.ok, r
        # simulate restart: brand-new instance, same file.
        store_b = PersistentNonceStore(path)
        r2 = verify_envelope(env, expected_domain=domain, nonce_store=store_b)
        assert r2.ok is False
        assert r2.reason == "nonce_reused"


def test_failed_verify_does_not_burn_nonce(domain, keys, payload):
    """A verification that fails on domain/timestamp/signature must NOT
    commit the nonce, otherwise a legitimate retry with the same nonce
    (e.g. after a chain glitch) would be locked out."""
    sk, pk = keys
    store = PersistentNonceStore.in_memory()

    # First attempt: wrong domain → fails.
    env = sign_envelope_ed25519(
        domain=domain,
        payload=payload,
        nonce="n-legit-retry",
        timestamp=int(time.time()),
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    wrong = DomainSeparator(
        protocol=domain.protocol,
        version=domain.version,
        chain_id="casper-mainnet",
        purpose=domain.purpose,
    )
    r_bad = verify_envelope(env, expected_domain=wrong, nonce_store=store)
    assert not r_bad.ok

    # Second attempt: correct domain, same nonce → MUST succeed.
    r_good = verify_envelope(env, expected_domain=domain, nonce_store=store)
    assert r_good.ok, r_good


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------


def test_tampered_payload_rejected(domain, keys, payload):
    sk, pk = keys
    env = sign_envelope_ed25519(
        domain=domain,
        payload=payload,
        nonce="n-tamper-p",
        timestamp=int(time.time()),
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    tampered_payload = dict(payload)
    tampered_payload["amount_motes"] = 9_999_999_999
    tampered = SignedEnvelope(
        domain=env.domain,
        payload=tampered_payload,
        signer_pubkey_hex=env.signer_pubkey_hex,
        algorithm=env.algorithm,
        nonce=env.nonce,
        timestamp=env.timestamp,
        signature_hex=env.signature_hex,
    )
    r = verify_envelope(tampered, expected_domain=domain)
    assert r.ok is False
    assert r.reason == "bad_signature"


def test_tampered_signature_rejected(domain, keys, payload):
    sk, pk = keys
    env = sign_envelope_ed25519(
        domain=domain,
        payload=payload,
        nonce="n-tamper-s",
        timestamp=int(time.time()),
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    # Flip a bit in the signature.
    flipped = bytearray.fromhex(env.signature_hex)
    flipped[0] ^= 0x01
    tampered = SignedEnvelope(
        domain=env.domain,
        payload=env.payload,
        signer_pubkey_hex=env.signer_pubkey_hex,
        algorithm=env.algorithm,
        nonce=env.nonce,
        timestamp=env.timestamp,
        signature_hex=flipped.hex(),
    )
    r = verify_envelope(tampered, expected_domain=domain)
    assert r.ok is False
    assert r.reason == "bad_signature"


def test_tampered_nonce_rejected(domain, keys, payload):
    sk, pk = keys
    env = sign_envelope_ed25519(
        domain=domain,
        payload=payload,
        nonce="n-original",
        timestamp=int(time.time()),
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    tampered = SignedEnvelope(
        domain=env.domain,
        payload=env.payload,
        signer_pubkey_hex=env.signer_pubkey_hex,
        algorithm=env.algorithm,
        nonce="n-different",
        timestamp=env.timestamp,
        signature_hex=env.signature_hex,
    )
    r = verify_envelope(tampered, expected_domain=domain)
    assert r.ok is False
    assert r.reason == "bad_signature"


# ---------------------------------------------------------------------------
# Format-level rejections
# ---------------------------------------------------------------------------


def test_unknown_purpose_rejected(domain, keys, payload):
    sk, pk = keys
    weird = DomainSeparator(
        protocol=domain.protocol,
        version=domain.version,
        chain_id=domain.chain_id,
        purpose="not.a.real.purpose",
    )
    env = sign_envelope_ed25519(
        domain=weird,
        payload=payload,
        nonce="n-unk-11",
        timestamp=int(time.time()),
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    r = verify_envelope(env, expected_domain=weird)
    assert r.ok is False
    assert r.reason == "unknown_purpose"


def test_bad_nonce_format_rejected(domain, keys, payload):
    sk, pk = keys
    # Too short.
    env = sign_envelope_ed25519(
        domain=domain,
        payload=payload,
        nonce="short",
        timestamp=int(time.time()),
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    r = verify_envelope(env, expected_domain=domain)
    assert r.ok is False
    assert r.reason == "nonce_bad_length"


def test_domain_forbids_control_chars():
    with pytest.raises(ValueError):
        DomainSeparator(
            protocol="AgentEscrow402",
            version="v1;bad",  # embedded separator character
            chain_id="casper-testnet",
            purpose="escrow.deposit",
        )


# ---------------------------------------------------------------------------
# Determinism / round-trip
# ---------------------------------------------------------------------------


def test_envelope_json_roundtrip(domain, keys, payload):
    sk, pk = keys
    env = sign_envelope_ed25519(
        domain=domain,
        payload=payload,
        nonce="n-roundtrip",
        timestamp=int(time.time()),
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    wire = env.to_json()
    obj = json.loads(wire)
    rehydrated = SignedEnvelope.from_dict(obj)
    r = verify_envelope(rehydrated, expected_domain=domain)
    assert r.ok, r


def test_canonical_payload_bytes_are_key_order_independent(domain, keys):
    """Two payloads with the same keys in different insertion order must
    serialize to identical bytes."""
    sk, pk = keys
    ts = int(time.time())
    p_a = {"a": 1, "b": 2, "c": 3}
    p_b = {"c": 3, "a": 1, "b": 2}
    env_a = sign_envelope_ed25519(
        domain=domain,
        payload=p_a,
        nonce="n-order-a",
        timestamp=ts,
        private_key_bytes=sk,
        public_key_bytes=pk,
    )
    env_b = SignedEnvelope(
        domain=env_a.domain,
        payload=p_b,
        signer_pubkey_hex=env_a.signer_pubkey_hex,
        algorithm=env_a.algorithm,
        nonce=env_a.nonce,
        timestamp=env_a.timestamp,
        signature_hex=env_a.signature_hex,
    )
    r = verify_envelope(env_b, expected_domain=domain)
    assert r.ok, r


def test_known_purposes_are_reasonable():
    """Sanity: the allow-list should include the core escrow lifecycle."""
    core = {"escrow.deposit", "escrow.release", "escrow.refund", "escrow.dispute"}
    assert core.issubset(KNOWN_PURPOSES)
