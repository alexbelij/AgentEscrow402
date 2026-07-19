"""Tests for server/config.py — Config.from_env() and its env-var wiring."""

from __future__ import annotations

import base64
import os

import pytest

from server.config import Config, get_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure none of the config-related env vars leak between tests."""
    for key in (
        "CASPER_PRIVATE_KEY_PATH",
        "DEPLOYER_KEY_B64",
        "SANDBOX",
        "CASPER_NODE_URL",
        "CASPER_CHAIN_NAME",
        "CASPER_CHAIN",
        "NOWNODES_API_KEY",
        "HOST",
        "PORT",
        "DEFAULT_TTL",
        "INSURANCE_FEE_BPS",
        "ESCROW_CONTRACT_HASH",
        "ALLOW_HOSTED_DEMO_IDENTITY",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


class TestConfigDefaults:
    def test_dataclass_defaults(self):
        cfg = Config()
        assert cfg.casper_chain_name == "casper-test"
        assert cfg.sandbox is True
        assert cfg.default_ttl == 300
        assert cfg.insurance_fee_bps == 200
        assert cfg.allow_hosted_demo_identity is False

    def test_is_frozen(self):
        cfg = Config()
        with pytest.raises(Exception):
            cfg.port = 1234  # type: ignore[misc]


class TestConfigFromEnv:
    def test_from_env_defaults_when_unset(self):
        cfg = Config.from_env()
        assert cfg.casper_private_key_path == ""
        assert cfg.sandbox is True
        assert cfg.port == 8000
        assert cfg.casper_chain_name == "casper-test"

    def test_from_env_reads_overrides(self, monkeypatch):
        monkeypatch.setenv("CASPER_NODE_URL", "https://node.example")
        monkeypatch.setenv("CASPER_CHAIN_NAME", "casper")
        monkeypatch.setenv("NOWNODES_API_KEY", "key123")
        monkeypatch.setenv("HOST", "127.0.0.1")
        monkeypatch.setenv("PORT", "9001")
        monkeypatch.setenv("SANDBOX", "false")
        monkeypatch.setenv("DEFAULT_TTL", "600")
        monkeypatch.setenv("INSURANCE_FEE_BPS", "150")
        monkeypatch.setenv("ESCROW_CONTRACT_HASH", "hash-abc")
        monkeypatch.setenv("ALLOW_HOSTED_DEMO_IDENTITY", "true")

        cfg = Config.from_env()

        assert cfg.casper_node_url == "https://node.example"
        assert cfg.casper_chain_name == "casper"
        assert cfg.nownodes_api_key == "key123"
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 9001
        assert cfg.sandbox is False
        assert cfg.default_ttl == 600
        assert cfg.insurance_fee_bps == 150
        assert cfg.contract_hash == "hash-abc"
        assert cfg.allow_hosted_demo_identity is True

    def test_from_env_falls_back_to_casper_chain_alias(self, monkeypatch):
        monkeypatch.setenv("CASPER_CHAIN", "casper-legacy")
        cfg = Config.from_env()
        assert cfg.casper_chain_name == "casper-legacy"

    def test_deployer_key_b64_decoded_to_tempfile(self, monkeypatch):
        raw = b"-----BEGIN PRIVATE KEY-----\nfakekeydata\n-----END PRIVATE KEY-----\n"
        monkeypatch.setenv("DEPLOYER_KEY_B64", base64.b64encode(raw).decode())

        cfg = Config.from_env()

        assert cfg.casper_private_key_path
        assert os.path.exists(cfg.casper_private_key_path)
        with open(cfg.casper_private_key_path, "rb") as f:
            assert f.read() == raw
        # Written with restrictive permissions (0o600).
        mode = os.stat(cfg.casper_private_key_path).st_mode & 0o777
        assert mode == 0o600
        os.remove(cfg.casper_private_key_path)

    def test_explicit_key_path_takes_precedence_over_b64(self, monkeypatch):
        monkeypatch.setenv("CASPER_PRIVATE_KEY_PATH", "/some/explicit/path.pem")
        monkeypatch.setenv("DEPLOYER_KEY_B64", base64.b64encode(b"ignored").decode())

        cfg = Config.from_env()

        assert cfg.casper_private_key_path == "/some/explicit/path.pem"


class TestGetConfig:
    def test_get_config_returns_config_instance(self):
        assert isinstance(get_config(), Config)
