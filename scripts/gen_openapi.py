#!/usr/bin/env python3
"""Regenerate ``docs/openapi.yaml`` from the live FastAPI app.

Produces a byte-stable YAML dump so we can gate PRs on drift: run this
script, `git diff --exit-code docs/openapi.yaml`, and any change to the
runtime schema without a matching commit fails CI.

Usage:
    python scripts/gen_openapi.py                # write docs/openapi.yaml
    python scripts/gen_openapi.py --check        # exit 1 if the file would change
    python scripts/gen_openapi.py -o /tmp/x.yaml # write elsewhere

Determinism:
- Keys sorted alphabetically.
- Uses PyYAML's `default_flow_style=False` and `sort_keys=True` — stable
  across Python 3.10+ and PyYAML 5+.
- Trailing newline enforced (some editors strip it; the check step
  tolerates that).
- ``info.version`` is pinned from ``pyproject.toml`` so a package bump
  produces exactly one line of diff, not a whole file churn.
"""

from __future__ import annotations

import argparse
import io
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "docs" / "openapi.yaml"


def _load_app_schema() -> dict:
    """Import the FastAPI app and pull its OpenAPI schema."""
    # Ensure repo root is on sys.path so `import server.app` works when
    # this script is invoked from a random cwd.
    sys.path.insert(0, str(REPO_ROOT))
    from server.app import app  # noqa: E402  (runtime import by design)

    schema = app.openapi()

    # Pin info.version from pyproject.toml so this file only churns when
    # someone bumps the package version — not because FastAPI re-derived
    # it from a routed dependency.
    try:
        with open(REPO_ROOT / "pyproject.toml", "rb") as f:
            pyproject = tomllib.load(f)
        pkg_version = pyproject["project"]["version"]
        schema.setdefault("info", {})["version"] = pkg_version
    except Exception:  # pragma: no cover — best-effort pinning
        pass

    return schema


# Fields whose default / minimum comes from `time.time()` at import time and
# so drifts every regen. We normalise them to a fixed sentinel so the yaml
# file only churns for real schema changes.
_TIME_DEPENDENT_NUMERIC_FIELDS = {
    "exclusiveMinimum",
    "minimum",
    "default",
}
_TIME_SENTINEL_MIN = 1_700_000_000  # ~2023-11-14, safely before any real deploy timestamp
_TIME_SENTINEL_MAX = 2_000_000_000  # ~2033 — anything between these is treated as "a runtime timestamp"


def _normalise_time_defaults(node):
    """Walk the schema; replace stale unix-time-ish numbers with a sentinel.

    Any float or int in the 1.7e9 .. 2.0e9 range inside a field named
    ``exclusiveMinimum`` / ``minimum`` / ``default`` is normalised to
    ``1700000000.0`` so the yaml file doesn't churn every regen just
    because the process clock moved a few ms.
    """
    if isinstance(node, dict):
        for k, v in list(node.items()):
            if (
                k in _TIME_DEPENDENT_NUMERIC_FIELDS
                and isinstance(v, (int, float))
                and not isinstance(v, bool)
                and _TIME_SENTINEL_MIN <= v <= _TIME_SENTINEL_MAX
            ):
                node[k] = float(_TIME_SENTINEL_MIN)
            else:
                _normalise_time_defaults(v)
    elif isinstance(node, list):
        for item in node:
            _normalise_time_defaults(item)


def _dump_yaml(schema: dict) -> str:
    """Deterministic YAML dump. Sorted keys, no flow-style shortcuts."""
    _normalise_time_defaults(schema)
    import yaml  # local import — script fails cleanly if PyYAML missing

    buf = io.StringIO()
    yaml.safe_dump(
        schema,
        buf,
        default_flow_style=False,
        sort_keys=True,
        allow_unicode=True,
        width=100_000,  # avoid arbitrary line wrapping mid-string
        indent=2,
    )
    text = buf.getvalue()
    if not text.endswith("\n"):
        text += "\n"
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "-o",
        "--out",
        default=str(DEFAULT_OUT),
        help=f"Output path (default: {DEFAULT_OUT.relative_to(REPO_ROOT)})",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if the file on disk differs from what we would write.",
    )
    args = ap.parse_args()

    schema = _load_app_schema()
    new_text = _dump_yaml(schema)

    out_path = Path(args.out)

    if args.check:
        try:
            current = out_path.read_text()
        except FileNotFoundError:
            print(f"::error::{out_path} does not exist; " "run `python scripts/gen_openapi.py` and commit it.")
            return 1
        # Tolerate trailing-newline drift (some editors strip it).
        try:
            display = out_path.relative_to(REPO_ROOT)
        except ValueError:
            display = out_path
        if current.rstrip("\n") == new_text.rstrip("\n"):
            print(f"[gen_openapi] OK — {display} matches live app.")
            return 0
        print(
            "::error::"
            f"{display} is out of sync with server/app.py. "
            "Run `python scripts/gen_openapi.py` locally and commit the diff."
        )
        # Show a compact diff-line summary in CI logs.
        import difflib

        diff = list(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=str(out_path.name) + " (on disk)",
                tofile=str(out_path.name) + " (from app)",
                n=1,
            )
        )
        # Cap the diff so a massive drift doesn't spam CI logs (first 60 lines is enough).
        sys.stderr.writelines(diff[:60])
        if len(diff) > 60:
            sys.stderr.write(f"... [{len(diff) - 60} more diff lines omitted]\n")
        return 1

    out_path.write_text(new_text)
    try:
        display = out_path.relative_to(REPO_ROOT)
    except ValueError:
        display = out_path
    print(f"[gen_openapi] wrote {display}  ({len(new_text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
