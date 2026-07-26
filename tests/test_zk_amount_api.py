"""API-level tests for /zk/* endpoints (W.2)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import app

client = TestClient(app)


def test_generators_endpoint():
    r = client.get("/zk/generators")
    assert r.status_code == 200
    d = r.json()
    assert "G" in d and "H" in d
    assert d["curve"] == "secp256k1"
    assert d["amount_bits"] == 64
    assert d["G"] != d["H"]


def test_prove_verify_roundtrip_small_bits():
    r = client.post("/zk/prove", json={"amount": 42, "transcript": "escrow-1", "bits": 8})
    assert r.status_code == 200, r.text
    proof_body = r.json()
    assert "commitment" in proof_body
    assert "blinding" in proof_body
    assert len(proof_body["blinding"]) == 64  # 32 bytes hex

    v = client.post(
        "/zk/verify",
        json={
            "commitment": proof_body["commitment"],
            "range_proof": proof_body["range_proof"],
            "transcript": "escrow-1",
        },
    )
    assert v.status_code == 200
    assert v.json()["valid"] is True
    assert v.json()["bits"] == 8


def test_verify_wrong_transcript_fails():
    r = client.post("/zk/prove", json={"amount": 100, "transcript": "escrow-1", "bits": 8})
    body = r.json()
    v = client.post(
        "/zk/verify",
        json={
            "commitment": body["commitment"],
            "range_proof": body["range_proof"],
            "transcript": "escrow-2",
        },
    )
    assert v.status_code == 200
    assert v.json()["valid"] is False


def test_open_commitment():
    r = client.post("/zk/prove", json={"amount": 500, "bits": 16})
    assert r.status_code == 200, r.text
    body = r.json()
    o = client.post(
        "/zk/open",
        json={
            "commitment": body["commitment"],
            "amount": 500,
            "blinding": body["blinding"],
        },
    )
    assert o.status_code == 200
    assert o.json()["valid"] is True

    # Wrong amount
    o_bad = client.post(
        "/zk/open",
        json={
            "commitment": body["commitment"],
            "amount": 501,
            "blinding": body["blinding"],
        },
    )
    assert o_bad.json()["valid"] is False


def test_aggregate_endpoint():
    # Prove three commitments to 10, 20, 30.
    commits = []
    for amt in (10, 20, 30):
        r = client.post("/zk/prove", json={"amount": amt, "bits": 8})
        commits.append(r.json()["commitment"])

    a = client.post(
        "/zk/aggregate",
        json={
            "commitments": [{"commitment": c} for c in commits],
        },
    )
    assert a.status_code == 200
    d = a.json()
    assert d["count"] == 3
    # Aggregate is deterministic given the same commitments (order matters).
    a2 = client.post(
        "/zk/aggregate",
        json={
            "commitments": [{"commitment": c} for c in commits],
        },
    )
    assert a2.json()["aggregate"] == d["aggregate"]


def test_prove_rejects_out_of_range():
    r = client.post("/zk/prove", json={"amount": 256, "bits": 8})
    assert r.status_code == 400
    assert "fit" in r.json()["detail"].lower() or "must" in r.json()["detail"].lower()


def test_prove_rejects_negative():
    r = client.post("/zk/prove", json={"amount": -1, "bits": 8})
    # Pydantic ge=0 catches it → 422
    assert r.status_code == 422


def test_transcript_hex_and_utf8():
    # Both hex and utf-8 transcripts should round-trip.
    r_hex = client.post("/zk/prove", json={"amount": 7, "transcript": "0xdeadbeef", "bits": 8})
    v_hex = client.post(
        "/zk/verify",
        json={
            "commitment": r_hex.json()["commitment"],
            "range_proof": r_hex.json()["range_proof"],
            "transcript": "0xdeadbeef",
        },
    )
    assert v_hex.json()["valid"] is True

    r_utf = client.post("/zk/prove", json={"amount": 7, "transcript": "hello", "bits": 8})
    v_utf = client.post(
        "/zk/verify",
        json={
            "commitment": r_utf.json()["commitment"],
            "range_proof": r_utf.json()["range_proof"],
            "transcript": "hello",
        },
    )
    assert v_utf.json()["valid"] is True
