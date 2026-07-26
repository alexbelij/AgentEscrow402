"""Tests for scripts/onchain_preflight.py (C5).

Covers the WASM export walker (LEB128 + section parse), the individual
check functions, and the end-to-end run against small fixtures. Every
fixture is bytes composed in-memory — no real WASM artefacts required.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "onchain_preflight.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("onchain_preflight", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register in sys.modules BEFORE exec_module so @dataclass can resolve
    # its owning module (dataclasses does sys.modules.get(cls.__module__)).
    sys.modules["onchain_preflight"] = mod
    spec.loader.exec_module(mod)
    return mod


PF = _load_module()


# --------------------------------------------------------------------------
# WASM fixture builders
# --------------------------------------------------------------------------


def _leb128_u32(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _wasm_with_exports(names: Iterable[str]) -> bytes:
    """Minimal valid WASM with an Export section listing `names`.

    Each export claims kind=0 (function) with index 0. That's not a
    fully-verifiable module (no Function/Type sections) but preflight
    only walks the Export section, so it suffices for testing the
    export enumerator.
    """
    names = list(names)
    export_entries = bytearray()
    export_entries += _leb128_u32(len(names))
    for name in names:
        name_bytes = name.encode("utf-8")
        export_entries += _leb128_u32(len(name_bytes))
        export_entries += name_bytes
        export_entries += b"\x00"       # kind=function
        export_entries += _leb128_u32(0)  # index 0

    section = bytearray()
    section.append(7)  # section id = Export
    section += _leb128_u32(len(export_entries))
    section += export_entries

    return b"\x00asm\x01\x00\x00\x00" + bytes(section)


# --------------------------------------------------------------------------
# WASM export walker
# --------------------------------------------------------------------------


class TestExportWalker:
    def test_empty_returns_no_exports(self) -> None:
        assert PF._walk_exports(b"\x00asm\x01\x00\x00\x00") == []

    def test_bad_magic_returns_empty(self) -> None:
        assert PF._walk_exports(b"not-a-wasm") == []

    def test_single_export(self) -> None:
        w = _wasm_with_exports(["call"])
        assert PF._walk_exports(w) == ["call"]

    def test_multi_export(self) -> None:
        w = _wasm_with_exports(["call", "_ep_release", "_ep_refund"])
        assert PF._walk_exports(w) == ["call", "_ep_release", "_ep_refund"]

    def test_leb128_multi_byte_length(self) -> None:
        # Force a > 127-byte name so the LEB128 reader takes 2 bytes.
        long_name = "a" * 200
        w = _wasm_with_exports([long_name])
        assert PF._walk_exports(w) == [long_name]


# --------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------


class TestSizeCheck:
    def test_all_below_ceiling(self, tmp_path: Path) -> None:
        p = tmp_path / "small.wasm"
        p.write_bytes(b"\x00" * 1024)  # 1 KiB
        result = PF._size_check([p])
        assert result.passed is True
        assert not result.findings

    def test_over_ceiling(self, tmp_path: Path) -> None:
        p = tmp_path / "huge.wasm"
        p.write_bytes(b"\x00" * (800 * 1024))  # 800 KiB > 700 KiB ceiling
        result = PF._size_check([p])
        assert result.passed is False
        assert len(result.findings) == 1
        assert "huge.wasm" in result.findings[0]
        assert "700" in result.findings[0]


class TestMagicCheck:
    def test_valid_magic(self, tmp_path: Path) -> None:
        p = tmp_path / "valid.wasm"
        p.write_bytes(b"\x00asm\x01\x00\x00\x00" + b"\x00" * 32)
        result = PF._magic_check([p])
        assert result.passed is True

    def test_truncated(self, tmp_path: Path) -> None:
        p = tmp_path / "truncated.wasm"
        p.write_bytes(b"\x00asm\x01\x00")  # missing last 2 bytes
        result = PF._magic_check([p])
        assert result.passed is False
        assert "magic mismatch" in result.findings[0]


class TestEntryPointsCheck:
    def test_packaged_needs_call(self) -> None:
        packaged = {"escrow_funder.wasm": {"exports": ["main", "malloc"]}}
        contracts: dict[str, dict] = {}
        result = PF._entrypoints_check(packaged, contracts)
        assert result.passed is False
        assert "missing 'call'" in result.findings[0]

    def test_packaged_with_call(self) -> None:
        packaged = {"escrow_funder.wasm": {"exports": ["call", "malloc"]}}
        result = PF._entrypoints_check(packaged, {})
        assert result.passed is True

    def test_contract_needs_ep_or_call(self) -> None:
        contracts = {"weird.wasm": {"exports": ["nothing_useful"]}}
        result = PF._entrypoints_check({}, contracts)
        assert result.passed is False
        assert "no _ep_" in result.findings[0]

    def test_contract_with_odra_ep(self) -> None:
        contracts = {"good.wasm": {"exports": ["_ep_release", "_ep_refund"]}}
        result = PF._entrypoints_check({}, contracts)
        assert result.passed is True

    def test_contract_with_only_call(self) -> None:
        contracts = {"stripped.wasm": {"exports": ["call"]}}
        result = PF._entrypoints_check({}, contracts)
        assert result.passed is True


# --------------------------------------------------------------------------
# Manifest check
# --------------------------------------------------------------------------


class TestManifestCheck:
    def test_missing_manifest_is_warning_not_failure(self, tmp_path: Path) -> None:
        result, parsed = PF._manifest_check(tmp_path / "does-not-exist.json", {})
        assert result.passed is True
        assert parsed is None
        assert "skipping" in result.detail

    def test_valid_manifest_passes(self, tmp_path: Path) -> None:
        manifest = {
            "contracts": {
                "escrow_manager_v9": {
                    "contract_hash": "hash-" + "aa" * 32,
                    "contract_package_hash": "hash-" + "bb" * 32,
                },
                "insurance_pool": {
                    "contract_hash": "hash-" + "cc" * 32,
                },
            }
        }
        path = tmp_path / "m.json"
        path.write_text(json.dumps(manifest))
        result, parsed = PF._manifest_check(path, {})
        assert result.passed is True, result.findings
        assert parsed == manifest

    def test_bare_hex_hash_accepted(self, tmp_path: Path) -> None:
        manifest = {"contracts": {"x": {"contract_hash": "ab" * 32}}}
        path = tmp_path / "m.json"
        path.write_text(json.dumps(manifest))
        result, _ = PF._manifest_check(path, {})
        assert result.passed is True

    def test_missing_contract_hash_fails(self, tmp_path: Path) -> None:
        manifest = {"contracts": {"x": {"description": "no hash"}}}
        path = tmp_path / "m.json"
        path.write_text(json.dumps(manifest))
        result, _ = PF._manifest_check(path, {})
        assert result.passed is False
        assert "missing contract_hash" in result.findings[0]

    def test_short_hash_fails(self, tmp_path: Path) -> None:
        manifest = {"contracts": {"x": {"contract_hash": "hash-ab"}}}
        path = tmp_path / "m.json"
        path.write_text(json.dumps(manifest))
        result, _ = PF._manifest_check(path, {})
        assert result.passed is False
        assert "length" in result.findings[0].lower()

    def test_non_hex_hash_fails(self, tmp_path: Path) -> None:
        manifest = {"contracts": {"x": {"contract_hash": "hash-" + "z" * 64}}}
        path = tmp_path / "m.json"
        path.write_text(json.dumps(manifest))
        result, _ = PF._manifest_check(path, {})
        assert result.passed is False
        assert "not hex" in result.findings[0]

    def test_duplicate_hash_flagged(self, tmp_path: Path) -> None:
        h = "hash-" + "dd" * 32
        manifest = {"contracts": {"a": {"contract_hash": h}, "b": {"contract_hash": h}}}
        path = tmp_path / "m.json"
        path.write_text(json.dumps(manifest))
        result, _ = PF._manifest_check(path, {})
        assert result.passed is False
        assert any("duplicate" in f for f in result.findings)

    def test_bad_json_fails(self, tmp_path: Path) -> None:
        path = tmp_path / "m.json"
        path.write_text("{ not: json")
        result, _ = PF._manifest_check(path, {})
        assert result.passed is False


# --------------------------------------------------------------------------
# End-to-end: run_preflight against a temp fixture layout
# --------------------------------------------------------------------------


class TestRunPreflight:
    def test_happy_layout(self, tmp_path: Path) -> None:
        packaged_dir = tmp_path / "casper_tx"
        contracts_dir = tmp_path / "target"
        packaged_dir.mkdir()
        contracts_dir.mkdir()

        (packaged_dir / "escrow_funder.wasm").write_bytes(_wasm_with_exports(["call"]))
        (contracts_dir / "escrow_manager.wasm").write_bytes(
            _wasm_with_exports(["_ep_release", "_ep_refund"])
        )
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {"contracts": {"escrow_manager": {"contract_hash": "hash-" + "aa" * 32}}}
            )
        )

        report = PF.run_preflight(
            packaged_dir=packaged_dir,
            contracts_dir=contracts_dir,
            manifest_path=manifest_path,
        )
        assert report.all_passed is True, [(c.name, c.findings) for c in report.checks]
        assert len(report.packaged_wasms) == 1
        assert len(report.contract_wasms) == 1

    def test_missing_call_in_packaged_fails(self, tmp_path: Path) -> None:
        packaged_dir = tmp_path / "casper_tx"
        contracts_dir = tmp_path / "target"
        packaged_dir.mkdir()
        contracts_dir.mkdir()

        (packaged_dir / "broken.wasm").write_bytes(_wasm_with_exports(["not_call"]))
        (contracts_dir / "ok.wasm").write_bytes(_wasm_with_exports(["_ep_x"]))

        report = PF.run_preflight(
            packaged_dir=packaged_dir,
            contracts_dir=contracts_dir,
            manifest_path=tmp_path / "no-manifest.json",
        )
        assert report.all_passed is False
        # entry_points check should fail.
        ep = next(c for c in report.checks if c.name == "entry_points")
        assert ep.passed is False
        assert any("missing 'call'" in f for f in ep.findings)

    def test_oversized_wasm_fails(self, tmp_path: Path) -> None:
        packaged_dir = tmp_path / "casper_tx"
        contracts_dir = tmp_path / "target"
        packaged_dir.mkdir()
        contracts_dir.mkdir()

        # Legal magic + 800 KiB of zeros → over 700 KiB ceiling.
        (packaged_dir / "huge.wasm").write_bytes(
            _wasm_with_exports(["call"]) + b"\x00" * (800 * 1024)
        )
        (contracts_dir / "small.wasm").write_bytes(_wasm_with_exports(["_ep_ok"]))

        report = PF.run_preflight(
            packaged_dir=packaged_dir,
            contracts_dir=contracts_dir,
            manifest_path=tmp_path / "no.json",
        )
        assert report.all_passed is False
        sz = next(c for c in report.checks if c.name == "size_ceiling")
        assert sz.passed is False

    def test_empty_dirs_fail_at_discovery(self, tmp_path: Path) -> None:
        packaged_dir = tmp_path / "casper_tx"
        contracts_dir = tmp_path / "target"
        packaged_dir.mkdir()
        contracts_dir.mkdir()

        report = PF.run_preflight(
            packaged_dir=packaged_dir,
            contracts_dir=contracts_dir,
            manifest_path=tmp_path / "no.json",
        )
        assert report.all_passed is False
        d = next(c for c in report.checks if c.name == "discovery")
        assert d.passed is False


# --------------------------------------------------------------------------
# Real-artefacts smoke — this file MUST also detect any regression on the
# actual WASMs shipped by main. If a future PR ships a bad wasm, this test
# catches it in the same run as the CI gate.
# --------------------------------------------------------------------------


class TestRealArtefacts:
    def test_current_main_wasms_pass(self) -> None:
        packaged = REPO_ROOT / "server" / "casper_tx"
        contracts_target = (
            REPO_ROOT / "contracts" / "target" / "wasm32-unknown-unknown" / "release"
        )
        manifest = REPO_ROOT / "deploy-out" / "onchain.json"

        if not packaged.exists() or not contracts_target.exists():
            import pytest

            pytest.skip("real wasm artefacts not present in this checkout")

        report = PF.run_preflight(
            packaged_dir=packaged,
            contracts_dir=contracts_target,
            manifest_path=manifest,
        )
        # If this fails, a real problem shipped to main — investigate before merging.
        failures = [(c.name, c.findings) for c in report.checks if not c.passed]
        assert report.all_passed is True, f"real-artefact preflight failed: {failures}"
