"""Regression guard: the generated frontend manifest must never drift from
``deploy-out/onchain.json``.

Before ``scripts/generate_frontend_manifest.py`` existed, contract hashes and
explorer links were hand-copied into several frontend files independently
(``TrustSignals.tsx``, ``Footer.tsx``, ``console/Contracts.tsx``,
``lib/api.ts``). That let a real, verified contract (the CEP-78 AETNFT test
NFT) go undetected as missing from the canonical manifest while it was
displayed as "verified on-chain evidence", and let another real, actively
used contract (the CEP-18 AETUSD test token) go missing from every trust/
evidence display entirely. See deploy-out/onchain.json's
``cep78_test_token_aetnft`` entry and server/config.py's
``cep18_aetusd_contract_hash``/``aetnft_contract_hash`` fields for the fix.

This test regenerates ``frontend/src/lib/manifest.generated.ts`` from the
current ``deploy-out/onchain.json`` into a temp file and diffs it against the
checked-in copy. A mismatch means someone edited the onchain.json manifest
(redeploy, new contract) without regenerating the frontend config, or edited
the generated file by hand.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR_PATH = REPO_ROOT / "scripts" / "generate_frontend_manifest.py"
CHECKED_IN_TS = REPO_ROOT / "frontend" / "src" / "lib" / "manifest.generated.ts"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_frontend_manifest", GENERATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_generated_manifest_matches_onchain_json():
    generator = _load_generator()
    fresh = generator.generate()
    checked_in = CHECKED_IN_TS.read_text()
    assert fresh == checked_in, (
        "frontend/src/lib/manifest.generated.ts is stale — re-run "
        "`python3 scripts/generate_frontend_manifest.py` and commit the result."
    )


def test_every_manifest_contract_has_a_64_char_hex_contract_hash():
    generator = _load_generator()
    import json

    manifest = json.loads((REPO_ROOT / "deploy-out" / "onchain.json").read_text())
    for key, contract in manifest["contracts"].items():
        contract_hash = contract["contract_hash"].removeprefix("hash-")
        assert len(contract_hash) == 64, f"{key}: contract_hash is not 64 hex chars"
        int(contract_hash, 16)  # raises ValueError if not valid hex
    assert generator  # generator imported and usable above
