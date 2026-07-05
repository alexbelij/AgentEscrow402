"""Shared test fixtures."""

from __future__ import annotations

import hashlib

import pytest

from server.config import Config
from server.sandbox import SandboxStore


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """server/app.py's in-process rate limiter (60 req/min per IP) is a
    module-global dict shared by every TestClient in the whole pytest
    session. Without resetting it, a large enough test suite (all
    TestClient calls share the same "testclient" IP) can legitimately trip
    429s that have nothing to do with what any individual test is
    checking. Clear it before every test so each test's own request count
    is what determines whether it hits the limit."""
    from server.app import _rate_limits

    _rate_limits.clear()
    yield
    _rate_limits.clear()


@pytest.fixture
def sandbox():
    return SandboxStore()


@pytest.fixture
def config():
    return Config(sandbox=True)


@pytest.fixture
def service_hash():
    return hashlib.sha256(b"test-escrow-001").hexdigest()


@pytest.fixture
def sender():
    return "account-hash-sender-001"


@pytest.fixture
def receiver():
    return "account-hash-receiver-002"
