"""Integration-test fixtures for the local NCTL Casper network.

These are NOT run by the default `pytest` invocation — they require a
locally-running NCTL container (see `docker-compose.casper-nctl.yml`) and
are gated by the `casper_net` pytest marker.

Usage:
    docker-compose -f docker-compose.casper-nctl.yml up -d
    ./scripts/nctl_keys.sh /tmp/nctl-keys
    NCTL_KEYS_DIR=/tmp/nctl-keys pytest tests/integration/ -m casper_net -v

If NCTL is not running, every test in this directory is skipped with a
clear reason instead of failing on connection errors.
"""

from __future__ import annotations

import os
import pathlib
import time

import httpx
import pytest

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

NCTL_RPC_URL = os.getenv("NCTL_RPC_URL", "http://127.0.0.1:11101/rpc")
NCTL_KEYS_DIR = pathlib.Path(os.getenv("NCTL_KEYS_DIR", "/tmp/nctl-keys"))
NCTL_CHAIN_NAME = os.getenv("NCTL_CHAIN_NAME", "casper-net-1")

# NCTL user-1..user-5 stable public key hex — matches PREDEFINED_ACCOUNTS=true.
# We only pin the fields the tests actually need; if a user account changes on
# the image side, the fixtures below will fetch the real values from the
# key files instead of trusting these constants blindly.
KNOWN_USERS = (1, 2, 3)


# ---------------------------------------------------------------------------
# Availability gate
# ---------------------------------------------------------------------------


def _nctl_reachable() -> tuple[bool, str]:
    """Return (ok, reason). Called once per session to decide whether to
    skip the whole integration suite."""
    if not NCTL_KEYS_DIR.exists():
        return False, f"NCTL keys dir not found: {NCTL_KEYS_DIR} — run scripts/nctl_keys.sh"
    faucet_pem = NCTL_KEYS_DIR / "faucet-secret_key.pem"
    if not faucet_pem.exists():
        return False, f"faucet secret key not found: {faucet_pem}"
    try:
        r = httpx.post(
            NCTL_RPC_URL,
            json={"jsonrpc": "2.0", "id": 1, "method": "info_get_status", "params": []},
            timeout=5.0,
        )
        r.raise_for_status()
        data = r.json()
        if "result" not in data:
            return False, f"info_get_status returned no result: {data!r}"
    except Exception as e:  # noqa: BLE001
        return False, f"NCTL RPC not reachable at {NCTL_RPC_URL}: {e}"
    return True, ""


_reachable, _reason = _nctl_reachable()


def pytest_collection_modifyitems(config, items):
    """Skip every casper_net-marked test if NCTL isn't up."""
    if _reachable:
        return
    skip = pytest.mark.skip(reason=f"NCTL unavailable: {_reason}")
    for item in items:
        if "casper_net" in item.keywords:
            item.add_marker(skip)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def nctl_rpc_url() -> str:
    return NCTL_RPC_URL


@pytest.fixture(scope="session")
def nctl_keys_dir() -> pathlib.Path:
    return NCTL_KEYS_DIR


@pytest.fixture(scope="session")
def faucet_pem_path(nctl_keys_dir: pathlib.Path) -> pathlib.Path:
    return nctl_keys_dir / "faucet-secret_key.pem"


@pytest.fixture(scope="session")
def faucet_public_key_hex(nctl_keys_dir: pathlib.Path) -> str:
    return (nctl_keys_dir / "faucet-public_key_hex").read_text().strip()


@pytest.fixture(scope="session")
def user_keys(nctl_keys_dir: pathlib.Path) -> dict[int, dict[str, str]]:
    """Return {1: {'pem_path': str, 'public_key_hex': str}, ...} for
    user-1..user-3. If a user file is missing, drop that user rather than
    failing the fixture — integration test bodies decide what they need."""
    users: dict[int, dict[str, str]] = {}
    for u in KNOWN_USERS:
        pem = nctl_keys_dir / f"user-{u}-secret_key.pem"
        pub = nctl_keys_dir / f"user-{u}-public_key_hex"
        if pem.exists() and pub.exists():
            users[u] = {
                "pem_path": str(pem),
                "public_key_hex": pub.read_text().strip(),
            }
    return users


@pytest.fixture(scope="session")
def wait_for_block():
    """Return a callable that blocks until NCTL produces at least one new
    block after `since_height` (defaults to the current head). Useful when
    a test wants to be sure a deploy has been included.
    """

    def _current_height() -> int:
        r = httpx.post(
            NCTL_RPC_URL,
            json={"jsonrpc": "2.0", "id": 1, "method": "info_get_status", "params": []},
            timeout=5.0,
        )
        r.raise_for_status()
        result = r.json().get("result", {})
        # Casper 2.0: last_added_block_info.height
        info = result.get("last_added_block_info") or {}
        return int(info.get("height", 0))

    def _wait(since_height: int | None = None, timeout: float = 90.0) -> int:
        start_height = since_height if since_height is not None else _current_height()
        deadline = time.time() + timeout
        while time.time() < deadline:
            h = _current_height()
            if h > start_height:
                return h
            time.sleep(2.0)
        raise TimeoutError(f"no new block after height={start_height} within {timeout}s")

    return _wait
