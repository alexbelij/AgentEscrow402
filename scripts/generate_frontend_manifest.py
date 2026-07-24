#!/usr/bin/env python3
"""Generate the typed frontend manifest config from deploy-out/onchain.json.

`deploy-out/onchain.json` is the canonical, verified record of every deployed
contract (see docs/BUILD_AUDIT.md and scripts/audit_contract_artifact.py).
Before this script existed, contract hashes and explorer links were
hand-copied as string literals into three separate frontend files
(TrustSignals.tsx, Footer.tsx, console/Contracts.tsx) plus frontend/src/lib/api.ts
-- with no guarantee any of them matched the manifest, each other, or reality
(see the AETNFT/AETUSD drift fixed alongside this script).

This script writes frontend/src/lib/manifest.generated.ts, a single generated
file the frontend imports from instead of re-typing hashes. Run it any time
deploy-out/onchain.json changes (redeploy, new contract, hash update):

    python3 scripts/generate_frontend_manifest.py

CI enforces this file is never stale via
tests/test_manifest_frontend_config_sync.py, which re-runs this script into a
temp path and diffs it against the checked-in copy.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ONCHAIN_JSON = REPO_ROOT / "deploy-out" / "onchain.json"
OUTPUT_TS = REPO_ROOT / "frontend" / "src" / "lib" / "manifest.generated.ts"

HEADER = """// GENERATED FILE -- do not edit by hand.
// Source of truth: deploy-out/onchain.json
// Regenerate with: python3 scripts/generate_frontend_manifest.py
// Verified in CI by tests/test_manifest_frontend_config_sync.py
"""


def to_ts_key(manifest_key: str) -> str:
    """snake_case manifest key -> camelCase TS identifier."""
    parts = manifest_key.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def render(manifest: dict) -> str:
    lines = [HEADER, ""]
    lines.append(f'export const NETWORK = "{manifest["network"]}";')
    lines.append(f'export const MANIFEST_GENERATED_AT = "{manifest["generated_at"]}";')
    lines.append(f'export const API_URL = "{manifest["api_url"]}";')
    lines.append(f'export const FRONTEND_URL = "{manifest["frontend_url"]}";')
    lines.append("")
    lines.append("export interface ManifestContract {")
    lines.append("  key: string;")
    lines.append("  name: string;")
    lines.append("  contractHash: string;")
    lines.append("  contractPackageHash: string;")
    lines.append("  deployHash: string;")
    lines.append("  version: number;")
    lines.append("  explorer: string;")
    lines.append("}")
    lines.append("")
    lines.append("export const CONTRACTS: Record<string, ManifestContract> = {")
    for key, c in manifest["contracts"].items():
        ts_key = to_ts_key(key)
        contract_hash = c["contract_hash"].removeprefix("hash-")
        package_hash = c["contract_package_hash"].removeprefix("hash-")
        lines.append(f"  {ts_key}: {{")
        lines.append(f'    key: "{key}",')
        lines.append(f'    name: "{c["name"]}",')
        lines.append(f'    contractHash: "{contract_hash}",')
        lines.append(f'    contractPackageHash: "{package_hash}",')
        lines.append(f'    deployHash: "{c["deploy_hash"]}",')
        lines.append(f'    version: {c["version"]},')
        lines.append(f'    explorer: "{c["explorer"]}",')
        lines.append("  },")
    lines.append("};")
    lines.append("")
    lines.append("export const CONTRACT_COUNT = Object.keys(CONTRACTS).length;")
    lines.append("")
    return "\n".join(lines)


def generate(manifest_path: Path = ONCHAIN_JSON) -> str:
    manifest = json.loads(manifest_path.read_text())
    return render(manifest)


def main() -> None:
    ts_source = generate()
    OUTPUT_TS.write_text(ts_source)
    print(f"Wrote {OUTPUT_TS.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
