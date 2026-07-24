"""Property tests for W3C VC 2.0 escrow receipts.

Coverage
--------
* JCS canonicalization: determinism, key order independence, type rejection
* did:key roundtrip (encode/decode)
* base58btc roundtrip
* Receipt issuance: schema completeness, deterministic output
* Signature verify: happy path
* Tamper detection: every leaf claim
* Structural rejection: missing fields, malformed proof, wrong DID method
* Cross-key verification (wrong issuer key -> reject)
* Expected-issuer mismatch
* Invalid inputs (bad amounts, unknown events, extra-claim collisions)
"""

from __future__ import annotations

import copy
import json

import pytest

from sdk.vc_receipts import (
    AE402_CONTEXT,
    ED25519_MULTICODEC,
    RECEIPT_TYPES,
    VC_CONTEXT_V2,
    IssuerKey,
    ProofMalformedError,
    ProofMissingError,
    SchemaError,
    SignatureInvalidError,
    VerificationError,
    _b58decode,
    _b58encode,
    _jcs_canonicalize,
    did_key_to_pubkey,
    issue_receipt,
    pubkey_to_did_key,
    receipt_summary,
    verify_receipt,
)

# ---------------------------------------------------------------------------
# base58btc
# ---------------------------------------------------------------------------


class TestBase58:
    def test_roundtrip_random(self):
        import os

        for _ in range(50):
            raw = os.urandom(1 + (os.urandom(1)[0] % 64))
            assert _b58decode(_b58encode(raw)) == raw

    def test_empty(self):
        assert _b58encode(b"") == ""
        assert _b58decode("") == b""

    def test_leading_zeros(self):
        assert _b58encode(b"\x00\x00\x01") == "112"
        assert _b58decode("112") == b"\x00\x00\x01"

    def test_known_vector(self):
        # bitcoin genesis-ish
        assert _b58encode(b"Hello World!") == "2NEpo7TZRRrLZSi2U"

    def test_invalid_char(self):
        with pytest.raises(ValueError, match="invalid base58"):
            _b58decode("0OIl")  # ambiguous chars excluded from alphabet


# ---------------------------------------------------------------------------
# JCS canonicalization
# ---------------------------------------------------------------------------


class TestJCS:
    def test_key_order_independence(self):
        a = {"b": 1, "a": 2}
        b = {"a": 2, "b": 1}
        assert _jcs_canonicalize(a) == _jcs_canonicalize(b)

    def test_deterministic(self):
        v = {"x": [1, 2, {"y": "z"}]}
        assert _jcs_canonicalize(v) == _jcs_canonicalize(v)

    def test_int_preserved(self):
        assert _jcs_canonicalize(1000) == b"1000"

    def test_float_rejected(self):
        with pytest.raises(TypeError, match="float"):
            _jcs_canonicalize({"x": 1.5})

    def test_bool_and_null(self):
        assert _jcs_canonicalize(True) == b"true"
        assert _jcs_canonicalize(False) == b"false"
        assert _jcs_canonicalize(None) == b"null"

    def test_unsupported_type(self):
        with pytest.raises(TypeError, match="unsupported type"):
            _jcs_canonicalize({"x": {1, 2}})

    def test_nested_key_order(self):
        a = {"outer": {"z": 1, "a": 2}, "top": [{"b": 1, "a": 2}]}
        b = {"top": [{"a": 2, "b": 1}], "outer": {"a": 2, "z": 1}}
        assert _jcs_canonicalize(a) == _jcs_canonicalize(b)


# ---------------------------------------------------------------------------
# did:key
# ---------------------------------------------------------------------------


class TestDidKey:
    def test_roundtrip(self):
        pk = b"\x11" * 32
        did = pubkey_to_did_key(pk)
        assert did.startswith("did:key:z")
        assert did_key_to_pubkey(did) == pk

    def test_encode_bad_pubkey_length(self):
        with pytest.raises(ValueError, match="32 bytes"):
            pubkey_to_did_key(b"\x11" * 31)

    def test_decode_not_did_key(self):
        with pytest.raises(ValueError, match="Not a did:key"):
            did_key_to_pubkey("did:web:example.com")

    def test_decode_wrong_multicodec(self):
        # base58btc of some 34 bytes with WRONG prefix
        payload = b"\x00\x00" + b"\xaa" * 32
        did = "did:key:z" + _b58encode(payload)
        with pytest.raises(ValueError, match="wrong multicodec"):
            did_key_to_pubkey(did)

    def test_multicodec_constant(self):
        assert ED25519_MULTICODEC == b"\xed\x01"


# ---------------------------------------------------------------------------
# IssuerKey
# ---------------------------------------------------------------------------


class TestIssuerKey:
    def test_from_seed(self):
        k = IssuerKey.from_seed(b"\x05" * 32)
        assert len(k.pubkey) == 32
        assert k.did.startswith("did:key:z")

    def test_from_seed_wrong_length(self):
        with pytest.raises(ValueError, match="32 bytes"):
            IssuerKey.from_seed(b"\x05" * 31)

    def test_from_seed_b64_and_b64url(self):
        import base64

        seed = b"\x07" * 32
        k1 = IssuerKey.from_seed_b64(base64.b64encode(seed).decode())
        k2 = IssuerKey.from_seed_b64(base64.urlsafe_b64encode(seed).decode().rstrip("="))
        assert k1.pubkey == k2.pubkey == IssuerKey.from_seed(seed).pubkey

    def test_generate_random(self):
        k1 = IssuerKey.generate()
        k2 = IssuerKey.generate()
        assert k1.pubkey != k2.pubkey

    def test_deterministic_from_seed(self):
        k1 = IssuerKey.from_seed(b"\x09" * 32)
        k2 = IssuerKey.from_seed(b"\x09" * 32)
        assert k1.pubkey == k2.pubkey
        assert k1.did == k2.did
        # signatures are deterministic under Ed25519
        assert k1.sign(b"hello") == k2.sign(b"hello")

    def test_seed_property(self):
        seed = b"\x0a" * 32
        assert IssuerKey.from_seed(seed).seed == seed


# ---------------------------------------------------------------------------
# Issuance
# ---------------------------------------------------------------------------


def _issuer():
    return IssuerKey.from_seed(b"\x01" * 32)


def _base_kwargs():
    return dict(
        event="release",
        service_hash="0xdeadbeef",
        escrow_id="0xdeadbeef",
        payer="payer_pk",
        receiver="receiver_pk",
        amount_motes=1_000_000,
        issuance_ts=1_700_000_000,
    )


class TestIssuance:
    def test_happy_release(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        assert vc["@context"] == [VC_CONTEXT_V2, AE402_CONTEXT]
        assert "VerifiableCredential" in vc["type"]
        assert "EscrowReleaseReceipt" in vc["type"]
        assert vc["issuer"] == _issuer().did
        assert vc["issuanceDate"] == "2023-11-14T22:13:20Z"
        subj = vc["credentialSubject"]
        assert subj["serviceHash"] == "0xdeadbeef"
        assert subj["event"] == "release"
        assert subj["amount"] == {"value": 1_000_000, "asset": "CSPR"}
        assert subj["id"] == "urn:ae402:escrow:0xdeadbeef"

    def test_deterministic(self):
        vc1 = issue_receipt(_issuer(), **_base_kwargs())
        vc2 = issue_receipt(_issuer(), **_base_kwargs())
        assert vc1 == vc2

    def test_different_events_different_types(self):
        for event, vc_type in RECEIPT_TYPES.items():
            kw = _base_kwargs()
            kw["event"] = event
            vc = issue_receipt(_issuer(), **kw)
            assert vc_type in vc["type"]
            assert vc["credentialSubject"]["event"] == event

    def test_unknown_event(self):
        kw = _base_kwargs()
        kw["event"] = "foo"
        with pytest.raises(ValueError, match="Unknown receipt event"):
            issue_receipt(_issuer(), **kw)

    def test_amount_must_be_int(self):
        kw = _base_kwargs()
        kw["amount_motes"] = 1.5
        with pytest.raises(TypeError, match="int"):
            issue_receipt(_issuer(), **kw)

    def test_amount_bool_rejected(self):
        kw = _base_kwargs()
        kw["amount_motes"] = True
        with pytest.raises(TypeError, match="int"):
            issue_receipt(_issuer(), **kw)

    def test_amount_negative(self):
        kw = _base_kwargs()
        kw["amount_motes"] = -1
        with pytest.raises(ValueError, match="non-negative"):
            issue_receipt(_issuer(), **kw)

    def test_amount_zero_allowed(self):
        kw = _base_kwargs()
        kw["amount_motes"] = 0
        vc = issue_receipt(_issuer(), **kw)
        assert vc["credentialSubject"]["amount"]["value"] == 0
        verify_receipt(vc)

    def test_service_hash_required(self):
        kw = _base_kwargs()
        kw["service_hash"] = ""
        with pytest.raises(ValueError, match="service_hash"):
            issue_receipt(_issuer(), **kw)

    def test_asset_default(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        assert vc["credentialSubject"]["amount"]["asset"] == "CSPR"

    def test_asset_custom(self):
        kw = _base_kwargs()
        kw["asset"] = "USDC"
        vc = issue_receipt(_issuer(), **kw)
        assert vc["credentialSubject"]["amount"]["asset"] == "USDC"

    def test_extra_claims(self):
        kw = _base_kwargs()
        kw["extra_claims"] = {"disputeId": "0xabc", "arbiterQuorum": 3}
        vc = issue_receipt(_issuer(), **kw)
        assert vc["credentialSubject"]["disputeId"] == "0xabc"
        assert vc["credentialSubject"]["arbiterQuorum"] == 3

    def test_extra_claims_collision(self):
        kw = _base_kwargs()
        kw["extra_claims"] = {"serviceHash": "override_attempt"}
        with pytest.raises(ValueError, match="collide"):
            issue_receipt(_issuer(), **kw)

    def test_extra_claims_collision_all_reserved(self):
        for reserved_key in ("id", "type", "serviceHash", "event", "payer", "receiver", "amount"):
            kw = _base_kwargs()
            kw["extra_claims"] = {reserved_key: "x"}
            with pytest.raises(ValueError, match="collide"):
                issue_receipt(_issuer(), **kw)

    def test_proof_shape(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        p = vc["proof"]
        assert p["type"] == "Ed25519Signature2020"
        assert p["proofPurpose"] == "assertionMethod"
        assert p["verificationMethod"].startswith(_issuer().did)
        assert p["proofValue"].startswith("z")

    def test_json_serializable(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        # must be JSON-serializable
        blob = json.dumps(vc)
        assert isinstance(blob, str)
        # and roundtrippable
        assert json.loads(blob) == vc


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


class TestVerify:
    def test_happy(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        assert verify_receipt(vc) is vc

    def test_expected_issuer_match(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        verify_receipt(vc, expected_issuer=_issuer().did)

    def test_expected_issuer_mismatch(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        other = IssuerKey.from_seed(b"\x02" * 32)
        with pytest.raises(VerificationError, match="issuer mismatch"):
            verify_receipt(vc, expected_issuer=other.did)

    def test_tamper_amount(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        vc["credentialSubject"]["amount"]["value"] = 999
        with pytest.raises(SignatureInvalidError):
            verify_receipt(vc)

    def test_tamper_payer(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        vc["credentialSubject"]["payer"] = "evil_pk"
        with pytest.raises(SignatureInvalidError):
            verify_receipt(vc)

    def test_tamper_service_hash(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        vc["credentialSubject"]["serviceHash"] = "0xdifferent"
        with pytest.raises(SignatureInvalidError):
            verify_receipt(vc)

    def test_tamper_event(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        vc["credentialSubject"]["event"] = "refund"
        with pytest.raises(SignatureInvalidError):
            verify_receipt(vc)

    def test_tamper_issuance_date(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        vc["issuanceDate"] = "1970-01-01T00:00:00Z"
        with pytest.raises(SignatureInvalidError):
            verify_receipt(vc)

    def test_wrong_signer(self):
        # issue with issuer A, then swap DID to issuer B — must fail
        vc = issue_receipt(_issuer(), **_base_kwargs())
        other = IssuerKey.from_seed(b"\x02" * 32)
        vc["issuer"] = other.did
        vc["proof"]["verificationMethod"] = f"{other.did}#{other.did.split(':')[-1]}"
        with pytest.raises(SignatureInvalidError):
            verify_receipt(vc)

    def test_missing_proof(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        del vc["proof"]
        with pytest.raises(ProofMissingError):
            verify_receipt(vc)

    def test_missing_context(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        del vc["@context"]
        with pytest.raises(SchemaError, match="@context"):
            verify_receipt(vc)

    def test_missing_type(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        del vc["type"]
        with pytest.raises(SchemaError, match="type"):
            verify_receipt(vc)

    def test_missing_issuer(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        del vc["issuer"]
        with pytest.raises(SchemaError, match="issuer"):
            verify_receipt(vc)

    def test_missing_issuance_date(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        del vc["issuanceDate"]
        with pytest.raises(SchemaError, match="issuanceDate"):
            verify_receipt(vc)

    def test_missing_subject(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        del vc["credentialSubject"]
        with pytest.raises(SchemaError, match="credentialSubject"):
            verify_receipt(vc)

    def test_context_wrong_shape(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        vc["@context"] = ["https://example.com/other"]  # missing VC v2
        with pytest.raises(SchemaError, match=VC_CONTEXT_V2):
            verify_receipt(vc)

    def test_type_wrong_shape(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        vc["type"] = ["OtherCredential"]
        with pytest.raises(SchemaError):
            verify_receipt(vc)

    def test_issuer_not_did_key(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        vc["issuer"] = "https://issuer.example.com"
        with pytest.raises(SchemaError, match="did:key"):
            verify_receipt(vc)

    def test_proof_wrong_type(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        vc["proof"]["type"] = "JsonWebSignature2020"
        with pytest.raises(ProofMalformedError, match="proof type"):
            verify_receipt(vc)

    def test_proof_wrong_purpose(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        vc["proof"]["proofPurpose"] = "authentication"
        with pytest.raises(ProofMalformedError, match="proofPurpose"):
            verify_receipt(vc)

    def test_proof_wrong_verification_method(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        vc["proof"]["verificationMethod"] = "did:key:zSOMEOTHER#kid"
        with pytest.raises(ProofMalformedError, match="verificationMethod"):
            verify_receipt(vc)

    def test_proof_value_not_multibase(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        vc["proof"]["proofValue"] = "notbase58encoded"
        with pytest.raises(ProofMalformedError):
            verify_receipt(vc)

    def test_proof_value_wrong_signature_length(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        # 32-byte signature — must be 64
        vc["proof"]["proofValue"] = "z" + _b58encode(b"\x00" * 32)
        with pytest.raises(ProofMalformedError, match="64 bytes"):
            verify_receipt(vc)

    def test_not_dict(self):
        with pytest.raises(SchemaError):
            verify_receipt("not a dict")  # type: ignore[arg-type]

    def test_deep_copy_no_side_effect(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        original = copy.deepcopy(vc)
        verify_receipt(vc)
        assert vc == original


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary(self):
        vc = issue_receipt(_issuer(), **_base_kwargs())
        s = receipt_summary(vc)
        assert s["issuer"] == _issuer().did
        assert s["event"] == "release"
        assert s["amount_motes"] == 1_000_000
        assert s["asset"] == "CSPR"
        assert s["service_hash"] == "0xdeadbeef"
        assert s["escrow_id"] == "0xdeadbeef"
        assert s["payer"] == "payer_pk"
        assert s["receiver"] == "receiver_pk"

    def test_summary_no_verify(self):
        # tampered receipt still summarizes (docstring says caller must verify first)
        vc = issue_receipt(_issuer(), **_base_kwargs())
        vc["credentialSubject"]["amount"]["value"] = 42
        s = receipt_summary(vc)
        assert s["amount_motes"] == 42  # summary reflects state; doesn't validate
