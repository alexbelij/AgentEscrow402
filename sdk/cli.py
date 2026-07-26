"""AgentEscrow402 CLI.

Thin, ergonomic wrapper over `sdk.client.EscrowClient`. The point is
end-to-end shell workflow: one binary a real integrator can pipe into
`jq`, drop into a Makefile, and use to inspect / drive escrows from
CI.

Design constraints:

- **No new API surface.** Every command is a 1:1 wrapper over an
  EscrowClient method. Adding a command must not require adding a
  method to the SDK — if a REST call isn't in the SDK yet, add it
  there first.
- **stdin / stdout are the API.** All output is JSON on stdout; errors
  land on stderr. Every command exits 0 on success, 1 on any error,
  and 2 on argument validation errors (argparse default).
- **Signed by default.** The CLI defaults to signed x402 mode (a real
  keypair, freshly generated or loaded from an env var) so a user does
  not accidentally hit production with `sandbox=True`. To use sandbox
  mode explicitly pass ``--sandbox``.

Usage:

    ae402 --help
    ae402 health
    ae402 list-escrows --limit 5
    ae402 create-escrow --receiver <64-hex> --amount 1000000
    ae402 release --service-hash <64-hex>

The identity key is loaded in this order:
  1. ``--secret-key-hex 0xNN...`` on the command line
  2. ``AE402_SECRET_KEY_HEX`` environment variable
  3. If neither, a fresh ephemeral key is generated for the run and
     the derived public key is printed on stderr so the caller can
     pin it if they want to reuse it later.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

# Deferred import so `--help` still works on a stripped-down deploy.
try:  # pragma: no cover - trivial import guard
    from sdk.client import EscrowClient
except ImportError:  # pragma: no cover
    EscrowClient = None  # type: ignore[assignment]


DEFAULT_BASE_URL = os.environ.get("AE402_API_URL", "https://agentescrow402-api-ywm8.onrender.com")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _emit(data: Any) -> None:
    """Serialise a result to stdout as pretty JSON."""
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")


def _bail(msg: str, code: int = 1) -> None:
    sys.stderr.write(f"ae402: {msg}\n")
    sys.exit(code)


def _make_client(args: argparse.Namespace) -> "EscrowClient":
    if EscrowClient is None:
        _bail("sdk.client.EscrowClient unavailable — install dependencies or run from repo root")
    base_url = args.api_url or DEFAULT_BASE_URL
    if args.sandbox:
        sender = args.sender or "cli-sandbox"
        return EscrowClient(base_url, sender=sender, sandbox=True, timeout=args.timeout)
    # Signed mode.
    secret_hex = args.secret_key_hex or os.environ.get("AE402_SECRET_KEY_HEX")
    if secret_hex:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        # Accept both "0x..." and bare hex.
        if secret_hex.startswith("0x") or secret_hex.startswith("0X"):
            secret_hex = secret_hex[2:]
        try:
            secret_bytes = bytes.fromhex(secret_hex)
        except ValueError as exc:  # noqa: BLE001
            _bail(f"--secret-key-hex is not valid hex: {exc}")
        if len(secret_bytes) != 32:
            _bail(f"--secret-key-hex must be 32 bytes ({len(secret_bytes)} given)")
        private_key = Ed25519PrivateKey.from_private_bytes(secret_bytes)
        client = EscrowClient(
            base_url=base_url,
            timeout=args.timeout,
            private_key=private_key,
            sandbox=False,
        )
    else:
        client = EscrowClient.generate(base_url, timeout=args.timeout)
        sys.stderr.write(
            "ae402: generated ephemeral identity for this run\n"
            f"       public key: {client.sender}\n"
            "       Set AE402_SECRET_KEY_HEX to pin an identity across runs.\n"
        )
    return client


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def _cmd_health(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        _emit(await client.health())
    finally:
        await client.close()


async def _cmd_stats(args: argparse.Namespace) -> None:
    # /stats is a plain GET — we hit it directly through the client's
    # own httpx to avoid duplicating a method for a one-off read.
    client = _make_client(args)
    try:
        r = await client._request("GET", "/stats")  # noqa: SLF001 — intentional
        _emit(r)
    finally:
        await client.close()


async def _cmd_list_escrows(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        params = {"limit": str(args.limit)}
        r = await client._request("GET", "/escrows", params=params)  # noqa: SLF001
        _emit(r)
    finally:
        await client.close()


async def _cmd_get_escrow(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        _emit(await client.get_escrow(args.service_hash))
    finally:
        await client.close()


async def _cmd_get_history(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        r = await client._request("GET", f"/escrow/{args.service_hash}/history")  # noqa: SLF001
        _emit(r)
    finally:
        await client.close()


async def _cmd_replay(args: argparse.Namespace) -> None:
    """Replay an escrow's lifecycle by combining /escrow/{h} and /escrow/{h}/history.

    Design: read-only, no server-side state change, no signatures. The point
    is to give a judge/operator a single command that reconstructs the full
    trajectory of an escrow (creation, transitions, terminal state) from
    what the backend already exposes. Output is deterministic JSON on
    stdout — pipe-friendly.
    """
    client = _make_client(args)
    try:
        escrow = await client.get_escrow(args.service_hash)
        history = await client._request("GET", f"/escrow/{args.service_hash}/history")  # noqa: SLF001
        events = history.get("events", []) if isinstance(history, dict) else []
        # Enrich each event with a delta_seconds from the create event, so
        # a reader can see the shape of the lifecycle at a glance.
        base_ts = events[0]["ts"] if events else None
        for ev in events:
            if base_ts is not None and isinstance(ev.get("ts"), (int, float)):
                ev["delta_seconds"] = ev["ts"] - base_ts
        replay = {
            "service_hash": args.service_hash,
            "current_state": escrow.get("status") if isinstance(escrow, dict) else None,
            "amount": escrow.get("amount") if isinstance(escrow, dict) else None,
            "receiver": escrow.get("receiver") if isinstance(escrow, dict) else None,
            "sender": escrow.get("sender") if isinstance(escrow, dict) else None,
            "events": events,
            "terminal": (events[-1]["action"] in ("released", "refunded", "expired", "disputed") if events else False),
        }
        _emit(replay)
    finally:
        await client.close()


async def _cmd_create_escrow(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        r = await client.create_escrow(
            receiver=args.receiver,
            amount=args.amount,
            ttl=args.ttl,
        )
        _emit(r)
    finally:
        await client.close()


async def _cmd_release(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        _emit(await client.release(args.service_hash))
    finally:
        await client.close()


async def _cmd_refund(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        _emit(await client.refund(args.service_hash))
    finally:
        await client.close()


async def _cmd_dispute(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        _emit(await client.dispute(args.service_hash, args.reason_hash))
    finally:
        await client.close()


async def _cmd_reputation(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        _emit(await client.get_reputation(args.agent))
    finally:
        await client.close()


async def _cmd_compute_hash(args: argparse.Namespace) -> None:
    """Local pure-function helper — no network, no client needed."""
    h = EscrowClient.compute_hash(  # type: ignore[union-attr]
        sender=args.sender,
        receiver=args.receiver,
        amount=args.amount,
        nonce=args.nonce,
    )
    _emit({"service_hash": h})


async def _cmd_build_x402_header(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        header = client.build_x402_header(
            escrow_hash=args.escrow_hash,
            amount=args.amount,
            method=args.method,
            path=args.path,
        )
        _emit({"X-Payment": header})
    finally:
        await client.close()


async def _cmd_mcp_tools(args: argparse.Namespace) -> None:
    """List the hosted MCP catalogue served at /mcp/tools."""
    client = _make_client(args)
    try:
        r = await client._request("GET", "/mcp/tools")  # noqa: SLF001
        if args.names_only:
            _emit([t["name"] for t in r.get("tools", [])])
        else:
            _emit(r)
    finally:
        await client.close()


async def _cmd_mcp_call(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        arguments: dict[str, Any] = {}
        if args.arguments_file:
            with open(args.arguments_file, encoding="utf-8") as fh:
                arguments = json.load(fh)
        elif args.arguments_json:
            arguments = json.loads(args.arguments_json)
        r = await client._request(  # noqa: SLF001
            "POST",
            f"/mcp/tools/{args.tool}/call",
            json_body={"arguments": arguments},
        )
        _emit(r)
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Argparse wiring
# ---------------------------------------------------------------------------


def _add_global_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-url", help=f"AE402 API base URL (default: env AE402_API_URL or {DEFAULT_BASE_URL})")
    parser.add_argument("--sandbox", action="store_true", help="Use sandbox mode (unsigned ?sender=)")
    parser.add_argument("--sender", help="Sender identity when --sandbox (default: cli-sandbox)")
    parser.add_argument("--secret-key-hex", help="Ed25519 secret key seed as hex; overrides env AE402_SECRET_KEY_HEX")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout in seconds (default: 30)")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ae402", description="AgentEscrow402 command-line client")
    _add_global_args(p)
    sub = p.add_subparsers(dest="command", required=True)

    # health
    sp = sub.add_parser("health", help="Ping /health")
    sp.set_defaults(func=_cmd_health)

    # stats
    sp = sub.add_parser("stats", help="Global backend stats")
    sp.set_defaults(func=_cmd_stats)

    # list-escrows
    sp = sub.add_parser("list-escrows", help="List recent escrows")
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=_cmd_list_escrows)

    # get-escrow
    sp = sub.add_parser("get-escrow", help="Fetch one escrow by service_hash")
    sp.add_argument("--service-hash", required=True)
    sp.set_defaults(func=_cmd_get_escrow)

    # get-history
    sp = sub.add_parser("get-history", help="Lifecycle history for an escrow")
    sp.add_argument("--service-hash", required=True)
    sp.set_defaults(func=_cmd_get_history)

    # replay
    sp = sub.add_parser(
        "replay",
        help="Reconstruct an escrow's full lifecycle from server-side history",
    )
    sp.add_argument("--service-hash", required=True)
    sp.set_defaults(func=_cmd_replay)

    # create-escrow
    sp = sub.add_parser("create-escrow", help="Create a new escrow (x402-signed)")
    sp.add_argument("--receiver", required=True, help="Receiver public key (64-hex)")
    sp.add_argument("--amount", type=int, required=True, help="Motes")
    sp.add_argument("--ttl", type=int, default=300, help="Time-to-live seconds (default 300)")
    sp.set_defaults(func=_cmd_create_escrow)

    # release / refund
    for cmd, help_msg, fn in (
        ("release", "Release an escrow", _cmd_release),
        ("refund", "Refund an escrow", _cmd_refund),
    ):
        sp = sub.add_parser(cmd, help=help_msg)
        sp.add_argument("--service-hash", required=True)
        sp.set_defaults(func=fn)

    # dispute (needs reason_hash)
    sp = sub.add_parser("dispute", help="Open a dispute on an escrow")
    sp.add_argument("--service-hash", required=True)
    sp.add_argument("--reason-hash", required=True, help="SHA-256 hash of the evidence bundle (64-hex)")
    sp.set_defaults(func=_cmd_dispute)

    # reputation
    sp = sub.add_parser("reputation", help="Fetch reputation for an agent public key")
    sp.add_argument("--agent", required=True)
    sp.set_defaults(func=_cmd_reputation)

    # compute-hash (local)
    sp = sub.add_parser("compute-hash", help="Compute a service hash locally (no network)")
    sp.add_argument("--sender", required=True)
    sp.add_argument("--receiver", required=True)
    sp.add_argument("--amount", type=int, required=True)
    sp.add_argument("--nonce", required=True)
    sp.set_defaults(func=_cmd_compute_hash)

    # build-x402-header
    sp = sub.add_parser("build-x402-header", help="Print a signed X-Payment header (no network call)")
    sp.add_argument("--escrow-hash", required=True)
    sp.add_argument("--amount", type=int, required=True)
    sp.add_argument("--method", default="POST")
    sp.add_argument("--path", default="/escrow")
    sp.set_defaults(func=_cmd_build_x402_header)

    # MCP catalogue
    sp = sub.add_parser("mcp-tools", help="List MCP tool catalogue (hosted playground)")
    sp.add_argument("--names-only", action="store_true", help="Print only tool names, one per line")
    sp.set_defaults(func=_cmd_mcp_tools)

    # MCP call
    sp = sub.add_parser("mcp-call", help="Invoke a hosted MCP tool")
    sp.add_argument("tool", help="Tool name — see `ae402 mcp-tools --names-only`")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--arguments-json", help="Arguments as an inline JSON object")
    g.add_argument("--arguments-file", help="Arguments from a JSON file")
    sp.set_defaults(func=_cmd_mcp_call)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        asyncio.run(args.func(args))
    except KeyboardInterrupt:
        _bail("interrupted", code=130)
    except Exception as exc:  # noqa: BLE001
        _bail(f"{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
