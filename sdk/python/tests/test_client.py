"""Client construction + payload-signing tests.

Full HTTP-level tests would need `pytest-httpx`; these focus on the parts
that are safe to test in isolation — identity generation and the x402
canonical payload (must match ``server/middleware.py``).
"""

from __future__ import annotations

from agentescrow402_sdk.client import X402_VERSION, EscrowClient, _canonical_payload


def test_generate_creates_a_valid_hex_sender():
    client = EscrowClient.generate("http://localhost:8000")
    assert len(client.sender) == 64
    # All hex.
    int(client.sender, 16)
    # Ed25519 pubkey → private_key is present.
    assert client._private_key is not None


def test_canonical_payload_shape():
    payload = _canonical_payload(
        version=X402_VERSION,
        escrow_hash="ab" * 32,
        amount=5000,
        sender="cd" * 32,
        timestamp=1700000000,
        nonce="deadbeef",
        method="POST",
        path="/escrow/release",
    )
    assert payload == (
        f"{X402_VERSION};" + "ab" * 32 + ";5000;" + "cd" * 32 + ";1700000000;deadbeef;POST;/escrow/release"
    ).encode("utf-8")


def test_base_url_is_stripped_of_trailing_slash():
    client = EscrowClient("http://localhost:8000/", sender="s")
    assert client._base == "http://localhost:8000"

    client2 = EscrowClient("http://localhost:8000///", sender="s")
    assert client2._base == "http://localhost:8000"


def test_sandbox_default_when_no_private_key():
    client = EscrowClient("http://localhost:8000", sender="s")
    assert client._sandbox is True

    client_signed = EscrowClient.generate("http://localhost:8000")
    assert client_signed._sandbox is False
