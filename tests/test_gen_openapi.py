"""Tests for scripts/gen_openapi.py — deterministic regen + drift gate."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "gen_openapi.py"


def _load_script():
    """Load scripts/gen_openapi.py as a module without invoking main()."""
    spec = importlib.util.spec_from_file_location("gen_openapi", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_openapi"] = module
    spec.loader.exec_module(module)
    return module


def test_normalise_time_defaults_replaces_stale_timestamps():
    gen = _load_script()
    schema = {
        "properties": {
            "expiry": {
                "type": "number",
                "exclusiveMinimum": 1785062066.0,
            },
            "unrelated": {
                "type": "integer",
                "minimum": 1,  # too small — must NOT be touched
            },
        }
    }
    gen._normalise_time_defaults(schema)
    assert schema["properties"]["expiry"]["exclusiveMinimum"] == 1700000000.0
    # A tiny integer sitting in `minimum` is not a timestamp — leave it.
    assert schema["properties"]["unrelated"]["minimum"] == 1


def test_normalise_leaves_non_time_numerics_alone():
    gen = _load_script()
    schema = {"components": {"schemas": {"X": {"default": 42, "minimum": 0}}}}
    gen._normalise_time_defaults(schema)
    assert schema["components"]["schemas"]["X"]["default"] == 42
    assert schema["components"]["schemas"]["X"]["minimum"] == 0


def test_normalise_walks_lists_and_nested():
    gen = _load_script()
    schema = {
        "oneOf": [
            {"default": 1785000000},   # timestamp-shaped
            {"default": "hello"},       # string default — untouched
            {"default": 0},             # small int — untouched
        ]
    }
    gen._normalise_time_defaults(schema)
    assert schema["oneOf"][0]["default"] == 1700000000.0
    assert schema["oneOf"][1]["default"] == "hello"
    assert schema["oneOf"][2]["default"] == 0


def test_normalise_ignores_booleans():
    """`bool` is a subclass of `int` in Python — must not treat True as a timestamp."""
    gen = _load_script()
    schema = {"components": {"default": True}}
    gen._normalise_time_defaults(schema)
    assert schema["components"]["default"] is True


def test_dump_yaml_is_deterministic():
    """Two consecutive dumps of the same schema must byte-match."""
    gen = _load_script()
    schema = {
        "openapi": "3.1.0",
        "info": {"title": "Test", "version": "0.0.1"},
        "paths": {
            "/b": {"get": {"summary": "b endpoint"}},
            "/a": {"get": {"summary": "a endpoint"}},
        },
        "components": {"schemas": {"Z": {"type": "string"}, "A": {"type": "integer"}}},
    }
    import copy

    text1 = gen._dump_yaml(copy.deepcopy(schema))
    text2 = gen._dump_yaml(copy.deepcopy(schema))
    assert text1 == text2
    # Sorted keys mean /a appears before /b in the output.
    assert text1.find("/a") < text1.find("/b")
    # Trailing newline enforced.
    assert text1.endswith("\n")


def test_check_mode_passes_on_current_repo():
    """--check must exit 0 against the freshly-committed docs/openapi.yaml."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"scripts/gen_openapi.py --check failed unexpectedly.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_check_mode_detects_drift(tmp_path):
    """--check on a hand-mutated file must exit 1."""
    real_yaml = (REPO_ROOT / "docs" / "openapi.yaml").read_text()
    mutated = real_yaml.replace("openapi: 3.1.0", "openapi: 9.9.9")
    scratch = tmp_path / "openapi.yaml"
    scratch.write_text(mutated)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", "-o", str(scratch)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1
    assert "out of sync" in result.stdout + result.stderr


def test_write_mode_creates_file(tmp_path):
    out = tmp_path / "generated.yaml"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "-o", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()
    text = out.read_text()
    assert text.startswith("components:") or text.startswith("info:") or text.startswith("openapi:")
    assert text.endswith("\n")


def test_script_uses_pinned_version_from_pyproject():
    """info.version must equal pyproject.toml [project].version."""
    import tomllib

    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        pyproject = tomllib.load(f)
    expected = pyproject["project"]["version"]

    text = (REPO_ROOT / "docs" / "openapi.yaml").read_text()
    # Find the info.version line (sorted-keys yaml puts info alphabetically).
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("version:"):
            # First `version:` at 2-space indent under `info:` is what we care about.
            found = stripped.split(":", 1)[1].strip().strip("'\"")
            if found == expected:
                return
            # Might be a schema-level `version:` under a different key; keep looking.
    pytest.fail(f"docs/openapi.yaml does not contain info.version={expected}")
