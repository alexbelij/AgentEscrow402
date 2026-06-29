"""Shared test fixtures."""

from __future__ import annotations

import hashlib
import pytest

from server.config import Config
from server.sandbox import SandboxStore


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
