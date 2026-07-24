"""Unit contract tests: 1 CSPR ⇔ 1e9 motes across API surface.

These tests are the enforceable side of the CSPR/motes unit contract
declared in ``docs/CSPR_UNITS.md`` and the JS-side ``lib/format.ts``
boundary. They exercise every ``amount`` / ``*_motes`` field the frontend
reads or writes and assert that:

* whatever the frontend sends in as motes comes back out as the same
  integer motes (no accidental /1e9 or ×1e9 hop);
* aggregated stats (``total_volume``, insurance pool balances) sum
  motes-consistently across many escrows;
* the ``/estimate`` fee arithmetic is scale-invariant: 2% of 1 CSPR
  worth of motes equals ``0.02 CSPR`` in motes, without truncation.

A regression here means the mix-up patched in 65145bd has crept back
into a code path, or a new endpoint has declared "amount" without
specifying units.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.app import app, get_sandbox
from server.sandbox import SandboxStore

MOTES_PER_CSPR = 1_000_000_000


@pytest.fixture()
def client() -> TestClient:
    """Isolated sandbox per test — no leakage between assertions."""
    store = SandboxStore()
    app.dependency_overrides[get_sandbox] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_sandbox, None)


def _hex64(seed: str) -> str:
    """Turn an ASCII seed into a 64-char lowercase hex string."""
    import hashlib

    return hashlib.sha256(seed.encode()).hexdigest()


class TestUnitContractCreate:
    """create_escrow: motes in, motes out, single scale, insurance-fee-consistent.

    Backend behaviour (server/app.py::create_escrow): the request carries a
    *gross* amount, the server subtracts an insurance-fee cut (bps, integer
    floor division so net + fee == gross exactly), and persists the *net*.
    The unit contract we defend here is: every stored value is in the same
    unit as the input — motes — and the split is a lossless integer
    partition, never a /1e9 or *1e9 hop.
    """

    def test_one_cspr_split_conserves_motes(self, client: TestClient) -> None:
        service_hash = _hex64("unit1")
        gross = MOTES_PER_CSPR  # 1 CSPR expressed as 1e9 motes
        r = client.post(
            "/escrow",
            params={"sender": "a" * 64},
            json={
                "receiver": "b" * 64,
                "amount": gross,
                "service_hash": service_hash,
                "ttl": 3600,
            },
        )
        assert r.status_code == 200, r.text

        # /estimate is the authoritative fee split for the same gross.
        est = client.get("/estimate", params={"amount": gross}).json()
        assert est["gross_amount"] + 0 == gross
        assert est["net_amount"] + est["insurance_fee"] == gross, "insurance-fee split lost motes"

        stored = client.get(f"/escrow/{service_hash}").json()["amount"]
        # Stored amount must equal /estimate.net_amount for the same gross
        # — same unit, same arithmetic path. A silent /1e9 anywhere would
        # collapse this to 0 or an off-by-1e9 factor.
        assert stored == est["net_amount"]
        assert stored > gross // 2  # sanity: not a scale collapse

    def test_micro_and_mega_amounts_pass_through(self, client: TestClient) -> None:
        """Boundary values: 1 mote (smallest) and 1,000,000 CSPR (big).

        For 1 mote gross the fee (2% of 1 = floor(0.02) = 0) is 0 and net
        stays 1 — confirms the split degenerates safely at the smallest
        possible input without triggering unit conversion. For 1M CSPR
        the net is a large 64-bit-safe integer, no float precision loss.
        """
        cases = [("one_mote", 1, 1), ("mega", 1_000_000 * MOTES_PER_CSPR, None)]
        for label, gross, expected_net in cases:
            sh = _hex64(label)
            r = client.post(
                "/escrow",
                params={"sender": "a" * 64},
                json={
                    "receiver": "b" * 64,
                    "amount": gross,
                    "service_hash": sh,
                    "ttl": 600,
                },
            )
            assert r.status_code == 200, f"{label}: {r.text}"
            est = client.get("/estimate", params={"amount": gross}).json()
            stored = client.get(f"/escrow/{sh}").json()["amount"]
            assert stored == est["net_amount"], (
                f"{label}: stored motes ({stored}) diverge from "
                f"/estimate.net_amount ({est['net_amount']}) — a code path "
                f"changed units between create_escrow and /estimate."
            )
            if expected_net is not None:
                assert stored == expected_net, f"{label}: expected net {expected_net}, got {stored}"


class TestUnitContractEstimate:
    """/estimate arithmetic must be scale-invariant in motes."""

    def test_two_percent_of_one_cspr_is_002_cspr_in_motes(self, client: TestClient) -> None:
        # Default insurance_fee_bps is 200 (2%) per Config.
        r = client.get("/estimate", params={"amount": MOTES_PER_CSPR})
        assert r.status_code == 200
        body = r.json()
        # 2% fee → 0.02 CSPR = 20_000_000 motes; net = 0.98 CSPR.
        assert body["gross_amount"] == MOTES_PER_CSPR
        assert body["insurance_fee"] == 20_000_000
        assert body["net_amount"] == MOTES_PER_CSPR - 20_000_000

    def test_estimate_scales_linearly(self, client: TestClient) -> None:
        """Doubling the input doubles net and fee, exactly."""
        r1 = client.get("/estimate", params={"amount": MOTES_PER_CSPR})
        r10 = client.get("/estimate", params={"amount": 10 * MOTES_PER_CSPR})
        assert r1.status_code == 200 and r10.status_code == 200
        b1, b10 = r1.json(), r10.json()
        assert b10["insurance_fee"] == 10 * b1["insurance_fee"]
        assert b10["net_amount"] == 10 * b1["net_amount"]


class TestUnitContractAggregates:
    """Volume / stats aggregate in motes without unit hop."""

    def test_stats_total_volume_sums_motes(self, client: TestClient) -> None:
        sender = "a" * 64
        amounts_motes = [
            1 * MOTES_PER_CSPR,
            5 * MOTES_PER_CSPR,
            100 * MOTES_PER_CSPR,
        ]
        for i, m in enumerate(amounts_motes):
            r = client.post(
                "/escrow",
                params={"sender": sender},
                json={
                    "receiver": "b" * 64,
                    "amount": m,
                    "service_hash": _hex64(f"agg{i}"),
                    "ttl": 600,
                },
            )
            assert r.status_code == 200, r.text

        # /stats.total_volume aggregates the *stored* (post-insurance-fee)
        # amounts — same integer unit as each stored escrow. We derive the
        # expected sum by re-computing each net through /estimate; any
        # heterogeneous unit mix (one row in CSPR, another in motes) would
        # collapse the sum by a factor of ~1e9 and this assertion catches it.
        expected_net_sum = 0
        for m in amounts_motes:
            est = client.get("/estimate", params={"amount": m}).json()
            expected_net_sum += est["net_amount"]

        stats = client.get("/stats")
        assert stats.status_code == 200
        got = stats.json().get("total_volume")
        assert got == expected_net_sum, (
            f"total_volume unit contract broken: expected {expected_net_sum} "
            f"motes (sum of per-escrow net_amount), got {got}. A silent "
            f"switch to CSPR in any summand collapses this by ~1e9."
        )
        # Sanity: the sum must be on the order of tens of billions of motes,
        # not ~100 (which is what a stray /1e9 would produce).
        assert got > 10 * MOTES_PER_CSPR


class TestUnitContractInvariants:
    """Scale-invariance smoke: any transformation the frontend applies to a
    motes value at the display boundary must be reversible at the write
    boundary.
    """

    def test_motes_to_cspr_to_motes_is_identity(self) -> None:
        """This mirrors what ``motesToCspr`` and ``csprToMotes`` do in
        ``frontend/src/lib/format.ts``. Encoded here so a backend
        contributor changing the constant catches the JS side too.
        """
        for motes in [
            MOTES_PER_CSPR,
            10 * MOTES_PER_CSPR,
            123_456_789 * MOTES_PER_CSPR,
        ]:
            cspr = motes / MOTES_PER_CSPR
            back = round(cspr * MOTES_PER_CSPR)
            assert back == motes, f"Non-invertible round-trip for {motes}: /1e9 then *1e9 → {back}"


def test_frontend_never_guesses_legacy_cspr_from_a_motes_value() -> None:
    """A real small on-chain balance must never be displayed as whole CSPR.

    `1` always means one mote on the API/chain boundary. Historic demo data
    requires an explicit migration or marker; magnitude-based guessing turns
    legitimate small payments into a billion-fold display error.
    """
    from pathlib import Path

    formatter = (Path(__file__).parents[1] / "frontend/src/lib/format.ts").read_text()
    assert "LEGACY_CSPR_HEURISTIC_MAX" not in formatter
    assert "return n / MOTES_PER_CSPR;" in formatter
