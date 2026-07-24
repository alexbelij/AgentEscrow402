"""Tests for the ae402 CLI.

Kept intentionally focused on the parts that don't require the network:
argument parsing, help output, and the local-only `compute-hash`
command. Network commands are covered end-to-end by the SDK's own
tests and the hosted service; running the CLI against a mocked backend
would be a poor return on complexity.
"""

from __future__ import annotations

import io
import json
import sys

import pytest

from agentescrow402_sdk import cli


def _run(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    try:
        code = cli.main(argv)
    except SystemExit as exc:  # argparse errors + _bail() use SystemExit
        code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


class TestHelp:
    def test_top_level_help(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            cli.main(["--help"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "AgentEscrow402 command-line client" in captured.out
        # Every command should be listed in the help.
        for cmd in (
            "health",
            "stats",
            "list-escrows",
            "create-escrow",
            "release",
            "refund",
            "dispute",
            "reputation",
            "compute-hash",
            "build-x402-header",
            "mcp-tools",
            "mcp-call",
        ):
            assert cmd in captured.out

    def test_no_command_prints_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            cli.main([])
        # argparse returns 2 for missing required subcommand.
        assert exc.value.code == 2


class TestComputeHashLocal:
    """Local command — exercises the CLI end-to-end without touching the
    network. Assert deterministic output for a fixed input."""

    def test_deterministic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        code, out, _ = _run(
            [
                "compute-hash",
                "--sender", "sender-x",
                "--receiver", "receiver-y",
                "--amount", "1000",
                "--nonce", "nonce-z",
            ],
            monkeypatch,
        )
        assert code == 0
        body = json.loads(out)
        assert "service_hash" in body
        assert len(body["service_hash"]) == 64
        assert all(c in "0123456789abcdef" for c in body["service_hash"])

    def test_repeated_call_same_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        argv = [
            "compute-hash",
            "--sender", "aa",
            "--receiver", "bb",
            "--amount", "42",
            "--nonce", "n",
        ]
        _, out_a, _ = _run(argv, monkeypatch)
        _, out_b, _ = _run(argv, monkeypatch)
        assert json.loads(out_a) == json.loads(out_b)


class TestArgParsing:
    def test_create_escrow_requires_receiver(self) -> None:
        with pytest.raises(SystemExit):
            cli._build_parser().parse_args(["create-escrow", "--amount", "100"])

    def test_dispute_requires_reason_hash(self) -> None:
        with pytest.raises(SystemExit):
            cli._build_parser().parse_args(["dispute", "--service-hash", "a" * 64])

    def test_mcp_call_mutually_exclusive_args(self) -> None:
        with pytest.raises(SystemExit):
            cli._build_parser().parse_args(
                [
                    "mcp-call",
                    "health_check",
                    "--arguments-json",
                    "{}",
                    "--arguments-file",
                    "/nowhere",
                ]
            )

    def test_global_flags_before_subcommand(self) -> None:
        parser = cli._build_parser()
        args = parser.parse_args(
            [
                "--api-url", "https://custom.example",
                "--sandbox",
                "--sender", "test-user",
                "health",
            ]
        )
        assert args.api_url == "https://custom.example"
        assert args.sandbox is True
        assert args.sender == "test-user"
        assert args.command == "health"


class TestSecretKeyHexNormalisation:
    def test_0x_prefix_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--secret-key-hex should accept both 0x-prefixed and bare hex."""
        # We construct args as if from argparse, then call _make_client.
        # A 32-byte all-zero seed is fine for the client constructor — no
        # network call is made, we just build the object and never use it.
        args_prefixed = cli._build_parser().parse_args(
            ["--secret-key-hex", "0x" + "00" * 32, "health"]
        )
        args_bare = cli._build_parser().parse_args(
            ["--secret-key-hex", "00" * 32, "health"]
        )
        # Both should build a client without raising.
        c1 = cli._make_client(args_prefixed)
        c2 = cli._make_client(args_bare)
        assert c1.sender == c2.sender  # same seed → same pubkey
        # Not touching the network.
        import asyncio
        asyncio.run(c1.close())
        asyncio.run(c2.close())
