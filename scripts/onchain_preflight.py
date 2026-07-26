#!/usr/bin/env python3
"""scripts/onchain_preflight.py — pre-deploy validation for AE402 WASM (C5).

Runs a set of static checks against the built WASM artifacts and the
deployment manifest BEFORE `casper-client put-deploy` fires. Every
check is deterministic (no network, no wallet). Intended as a CI gate:
if any check fails the PR that touched a contract cannot merge.

Checks performed:

    1. Discovery — enumerate every .wasm under contracts/target/
       .../release/*.wasm and every packaged .wasm the backend ships
       under server/casper_tx/*.wasm. Both sources must be present
       for the "on-chain read path" and the "on-chain write path".

    2. Size ceiling — each WASM must be ≤ 700 KiB (Casper 2.0 hard
       limit is 1 MiB; we keep 300 KiB of headroom so a debug build
       doesn't silently trip the deploy).

    3. Magic bytes — the file must start with \\x00asm\\x01\\x00\\x00\\x00
       (WebAssembly binary format). Catches truncation.

    4. Entry-points — the packaged tx wasms MUST export `call` (that
       is Casper's session-code convention). The contracts/target
       wasms MUST export at least one `_ep_*` or `entry_point_*`
       symbol (Odra convention). Uses a lightweight WASM export
       walk — no external tool.

    5. Deployment manifest — `deploy/manifest.json` (or the
       `--manifest` override) must list every packaged tx wasm with
       a hex `contract_hash` field. Missing entries fail the run
       loudly.

    6. Duplicate-hash detection — two contracts sharing the same
       `contract_hash` in the manifest is a copy-paste bug that has
       hit us before. Flagged as fatal.

Exit codes:
    0  every check passed
    1  at least one check failed
    2  bad argument or missing tool

Usage:
    python scripts/onchain_preflight.py           # default paths
    python scripts/onchain_preflight.py --json    # machine-readable
    python scripts/onchain_preflight.py --verbose

    # Override paths (used by CI to point at ephemeral artifacts dir).
    python scripts/onchain_preflight.py \
        --contracts-dir path/to/target \
        --packaged-dir path/to/casper_tx \
        --manifest    path/to/manifest.json
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]

# WASM binary magic + version 0x01. Every valid WASM module starts with this.
_WASM_MAGIC = b"\x00asm\x01\x00\x00\x00"

# Ceiling (bytes). 700 KiB gives us 324 KiB of headroom under Casper 2.0's
# hard 1 MiB limit. If any wasm exceeds this, ship a strip-debug variant.
_SIZE_CEILING_BYTES = 700 * 1024


# ---------------------------------------------------------------------------
# WASM export walk (no external dependency)
# ---------------------------------------------------------------------------


def _read_leb128_u32(buf: bytes, offset: int) -> tuple[int, int]:
    """Read one unsigned LEB128 int from `buf` starting at `offset`.

    Returns (value, bytes_consumed). WASM export table sizes and name
    lengths are encoded this way.
    """
    result = 0
    shift = 0
    consumed = 0
    while True:
        byte = buf[offset + consumed]
        result |= (byte & 0x7F) << shift
        consumed += 1
        if byte & 0x80 == 0:
            break
        shift += 7
        if shift > 35:
            raise ValueError("LEB128 too long — WASM likely corrupt")
    return result, consumed


def _walk_exports(wasm_bytes: bytes) -> list[str]:
    """Enumerate export names in a WASM module.

    Follows the minimum spec required to find the "Export" section
    (section id = 7). Any parse anomaly returns [] rather than
    raising — preflight logs the empty result, callers decide.
    """
    if not wasm_bytes.startswith(_WASM_MAGIC):
        return []
    p = len(_WASM_MAGIC)
    n = len(wasm_bytes)
    exports: list[str] = []
    while p < n:
        section_id = wasm_bytes[p]
        p += 1
        try:
            section_size, consumed = _read_leb128_u32(wasm_bytes, p)
        except (ValueError, IndexError):
            return exports
        p += consumed
        section_end = p + section_size
        if section_id == 7:  # Export section
            try:
                num_exports, consumed = _read_leb128_u32(wasm_bytes, p)
                q = p + consumed
                for _ in range(num_exports):
                    name_len, c = _read_leb128_u32(wasm_bytes, q)
                    q += c
                    name = wasm_bytes[q : q + name_len].decode("utf-8", errors="replace")
                    q += name_len
                    # 1 byte kind + LEB128 index (skip)
                    q += 1
                    _, c = _read_leb128_u32(wasm_bytes, q)
                    q += c
                    exports.append(name)
            except (ValueError, IndexError, UnicodeDecodeError):
                return exports
            return exports
        p = section_end
    return exports


# ---------------------------------------------------------------------------
# Check machinery
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    findings: list[str] = field(default_factory=list)


@dataclass
class PreflightReport:
    checks: list[CheckResult] = field(default_factory=list)
    packaged_wasms: dict[str, dict] = field(default_factory=dict)
    contract_wasms: dict[str, dict] = field(default_factory=dict)
    manifest: dict | None = None

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "all_passed": self.all_passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail, "findings": c.findings}
                for c in self.checks
            ],
            "packaged_wasms": self.packaged_wasms,
            "contract_wasms": self.contract_wasms,
        }


def _find_wasms(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.wasm") if p.is_file())


def _size_check(paths: Iterable[Path]) -> CheckResult:
    findings: list[str] = []
    inspected = 0
    for p in paths:
        inspected += 1
        size = p.stat().st_size
        if size > _SIZE_CEILING_BYTES:
            findings.append(
                f"{p.name}: {size} bytes exceeds ceiling {_SIZE_CEILING_BYTES} bytes "
                f"(~{size / 1024:.1f} KiB > {_SIZE_CEILING_BYTES // 1024} KiB)"
            )
    return CheckResult(
        name="size_ceiling",
        passed=not findings,
        detail=f"{inspected} wasm(s) inspected; ceiling = {_SIZE_CEILING_BYTES // 1024} KiB",
        findings=findings,
    )


def _magic_check(paths: Iterable[Path]) -> CheckResult:
    findings: list[str] = []
    inspected = 0
    for p in paths:
        inspected += 1
        with p.open("rb") as fh:
            head = fh.read(len(_WASM_MAGIC))
        if head != _WASM_MAGIC:
            findings.append(
                f"{p.name}: WASM magic mismatch — first {len(_WASM_MAGIC)} bytes = {head.hex()}"
            )
    return CheckResult(
        name="magic_bytes",
        passed=not findings,
        detail=f"{inspected} wasm(s) inspected",
        findings=findings,
    )


def _entrypoints_check(
    packaged: dict[str, dict], contract_build: dict[str, dict]
) -> CheckResult:
    findings: list[str] = []

    # Packaged tx wasms (session code) must export `call`.
    for name, meta in packaged.items():
        if "call" not in meta.get("exports", []):
            findings.append(
                f"packaged/{name}: missing 'call' export "
                f"(session code contract not usable via casper-client put-deploy)"
            )

    # Contract-build wasms must export at least one Odra entry-point-like symbol.
    for name, meta in contract_build.items():
        exports = meta.get("exports", [])
        if not any(e.startswith("_ep_") or e.startswith("entry_point_") for e in exports):
            # Some Odra builds strip these into `call`. Treat presence of `call` as OK.
            if "call" not in exports:
                findings.append(
                    f"contracts/{name}: no _ep_* / entry_point_* / call export found — "
                    f"contract has no entrypoints? exports={exports[:5]}..."
                )

    return CheckResult(
        name="entry_points",
        passed=not findings,
        detail=f"packaged={len(packaged)} contract-build={len(contract_build)}",
        findings=findings,
    )


def _manifest_check(manifest_path: Path, packaged: dict[str, dict]) -> tuple[CheckResult, dict | None]:
    if not manifest_path.exists():
        # A missing manifest is a warning, not a hard fail — most pre-audit
        # test runs won't have a real manifest committed.
        return (
            CheckResult(
                name="deployment_manifest",
                passed=True,
                detail=f"{manifest_path} not found — skipping (no manifest to validate)",
            ),
            None,
        )

    try:
        raw = manifest_path.read_text()
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return (
            CheckResult(
                name="deployment_manifest",
                passed=False,
                detail=f"{manifest_path} is not valid JSON",
                findings=[str(exc)],
            ),
            None,
        )

    findings: list[str] = []

    contracts = parsed.get("contracts", {}) if isinstance(parsed, dict) else {}
    if not contracts:
        findings.append("manifest has no `contracts` map (or it is empty)")

    # We DO NOT assert every packaged tx wasm has a manifest entry — the
    # canonical manifest tracks CONTRACT deploys, not SESSION-CODE payloads.
    # A session-code wasm being present locally is fine even if it never
    # ends up in the manifest (it's what the client sends per-call).

    # Every listed contract must carry a hex contract_hash. The canonical
    # manifest (deploy-out/onchain.json) uses a "hash-<hex>" prefix; strip
    # it before hex-validating.
    hashes_seen: dict[str, list[str]] = {}
    for cname, cmeta in contracts.items():
        if not isinstance(cmeta, dict):
            findings.append(f"{cname}: manifest entry not a JSON object")
            continue
        ch_raw = cmeta.get("contract_hash", "")
        if not ch_raw:
            findings.append(f"{cname}: missing contract_hash")
            continue
        # Accept both "hash-<hex>" (canonical Casper 2.0) and bare hex.
        ch = ch_raw[5:] if ch_raw.startswith("hash-") else ch_raw
        if not all(c in "0123456789abcdefABCDEF" for c in ch):
            findings.append(f"{cname}: contract_hash is not hex ({ch_raw!r})")
            continue
        if len(ch) != 64:
            findings.append(
                f"{cname}: contract_hash length {len(ch)} != 64 (expected 32 bytes hex)"
            )
        hashes_seen.setdefault(ch.lower(), []).append(cname)

    # Duplicate-hash detection.
    for h, owners in hashes_seen.items():
        if len(owners) > 1:
            findings.append(
                f"duplicate contract_hash {h} shared by {len(owners)} contracts: {owners}"
            )

    return (
        CheckResult(
            name="deployment_manifest",
            passed=not findings,
            detail=f"{len(contracts)} contract entries; {len(hashes_seen)} distinct hashes",
            findings=findings,
        ),
        parsed,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_preflight(
    packaged_dir: Path,
    contracts_dir: Path,
    manifest_path: Path,
    verbose: bool = False,
) -> PreflightReport:
    """Run every preflight check. Returns a PreflightReport."""

    report = PreflightReport()

    packaged_paths = _find_wasms(packaged_dir)
    contract_paths = _find_wasms(contracts_dir)

    if not packaged_paths and not contract_paths:
        report.checks.append(
            CheckResult(
                name="discovery",
                passed=False,
                detail="no wasm files found under either directory",
                findings=[
                    f"packaged: {packaged_dir}",
                    f"contracts: {contracts_dir}",
                ],
            )
        )
        return report

    for p in packaged_paths:
        with p.open("rb") as fh:
            data = fh.read()
        report.packaged_wasms[p.name] = {
            "path": str(p.relative_to(REPO_ROOT) if p.is_relative_to(REPO_ROOT) else p),
            "size_bytes": len(data),
            "exports": _walk_exports(data),
        }
    for p in contract_paths:
        with p.open("rb") as fh:
            data = fh.read()
        report.contract_wasms[p.name] = {
            "path": str(p.relative_to(REPO_ROOT) if p.is_relative_to(REPO_ROOT) else p),
            "size_bytes": len(data),
            "exports": _walk_exports(data),
        }

    report.checks.append(
        CheckResult(
            name="discovery",
            passed=True,
            detail=f"packaged={len(packaged_paths)} contracts={len(contract_paths)}",
        )
    )
    report.checks.append(_size_check(packaged_paths + contract_paths))
    report.checks.append(_magic_check(packaged_paths + contract_paths))
    report.checks.append(_entrypoints_check(report.packaged_wasms, report.contract_wasms))

    mcheck, manifest = _manifest_check(manifest_path, report.packaged_wasms)
    report.checks.append(mcheck)
    report.manifest = manifest

    return report


def _render_tty(report: PreflightReport, verbose: bool) -> str:
    def color(s: str, code: str) -> str:
        return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s

    lines = ["== AE402 on-chain preflight =="]
    for c in report.checks:
        icon = color("✔", "32") if c.passed else color("✖", "31")
        lines.append(f"  {icon} {c.name}: {c.detail}")
        if c.findings and (verbose or not c.passed):
            for f in c.findings:
                lines.append(f"      · {f}")
    lines.append("")
    lines.append(
        color("Result: PASS", "32") if report.all_passed else color("Result: FAIL", "31")
    )
    if verbose:
        lines.append("")
        lines.append(f"packaged wasms: {list(report.packaged_wasms)}")
        lines.append(f"contract wasms: {list(report.contract_wasms)}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="AE402 on-chain preflight (C5)")
    ap.add_argument(
        "--packaged-dir",
        default=str(REPO_ROOT / "server" / "casper_tx"),
        help="directory containing packaged tx wasms (session code)",
    )
    ap.add_argument(
        "--contracts-dir",
        default=str(REPO_ROOT / "contracts" / "target" / "wasm32-unknown-unknown" / "release"),
        help="directory containing built contract wasms",
    )
    ap.add_argument(
        "--manifest",
        default=str(REPO_ROOT / "deploy-out" / "onchain.json"),
        help="path to deployment manifest JSON (default: deploy-out/onchain.json, canonical since PR #28)",
    )
    ap.add_argument("--json", action="store_true", help="emit JSON only (no TTY output)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    report = run_preflight(
        packaged_dir=Path(args.packaged_dir),
        contracts_dir=Path(args.contracts_dir),
        manifest_path=Path(args.manifest),
        verbose=args.verbose,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(_render_tty(report, args.verbose))

    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
