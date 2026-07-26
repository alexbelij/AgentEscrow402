"""AE-D9: /health.manifest_sanity — env-hash vs deploy-out/onchain.json sanity check.

The manifest_sanity block on /health cross-checks the running server's
AE402_CONTRACT_HASH against the checked-in deploy-out/onchain.json manifest.
A mismatch means either the manifest is stale or the running app is pointed
at an old contract — a red flag judges will want to see fail-loud.

These tests exercise the helper directly so they don't depend on FastAPI
lifespan setup or /health request wiring; the /health integration path is
covered by the existing smoke suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.app import _manifest_sanity_snapshot


@pytest.fixture()
def manifest_path() -> Path:
    """Real manifest checked into the repo — asserted to exist so a missing
    manifest is caught immediately rather than making every downstream test
    return `manifest_missing` silently."""
    p = Path(__file__).resolve().parent.parent / "deploy-out" / "onchain.json"
    assert p.exists(), f"manifest missing at {p}"
    return p


@pytest.fixture()
def expected_hash(manifest_path: Path) -> str:
    """Return the current escrow_manager_v9 contract_hash from the manifest,
    stripped of the ``hash-`` prefix."""
    data = json.loads(manifest_path.read_text())
    raw = data["contracts"]["escrow_manager_v9"]["contract_hash"]
    return raw.removeprefix("hash-").lower()


def test_ok_when_env_matches_manifest(expected_hash: str) -> None:
    r = _manifest_sanity_snapshot(expected_hash)
    assert r["status"] == "ok"
    assert r["expected"] == expected_hash
    assert r["actual"] == expected_hash


def test_ok_when_env_has_hash_prefix(expected_hash: str) -> None:
    """Callers may pass either bare 64-hex or the on-wire ``hash-<64hex>`` form.
    The helper normalises both."""
    r = _manifest_sanity_snapshot(f"hash-{expected_hash}")
    assert r["status"] == "ok"


def test_ok_case_insensitive(expected_hash: str) -> None:
    r = _manifest_sanity_snapshot(expected_hash.upper())
    assert r["status"] == "ok"


def test_mismatch_when_env_is_stale() -> None:
    """A stale env-hash from before the 2026-07-24 Key-fix redeploy MUST
    flip status to mismatch — this is the whole point of the check."""
    stale = "612cead2226329fafec492042fd96a999df06d1e88c476913a167f44d3ddd9ec"
    r = _manifest_sanity_snapshot(stale)
    assert r["status"] == "mismatch"
    assert r["actual"] == stale
    assert r["expected"] != stale


def test_env_missing_when_hash_empty(expected_hash: str) -> None:
    r = _manifest_sanity_snapshot("")
    assert r["status"] == "env_missing"
    assert r["expected"] == expected_hash
    assert r["actual"] is None


def test_manifest_has_all_9_contracts(manifest_path: Path) -> None:
    """Guard-rail: manifest must document all 9 contracts. If a contract is
    dropped the sanity check for that leg silently returns
    ``manifest_missing_field`` instead of catching it here."""
    data = json.loads(manifest_path.read_text())
    contracts = data["contracts"]
    required = {
        "escrow_manager_v9",
        "batch_escrow_manager",
        "insurance_pool",
        "vrf_arbiter",
        "agent_identity_registry",
        "multi_asset_escrow",
        "cep18_test_token_aetusd",
        "cep18_test_token_aemat",
        "cep78_test_token_aetnft",
    }
    assert required.issubset(contracts.keys()), (
        f"missing contract keys: {required - set(contracts.keys())}"
    )
