# Software Bill of Materials (SBOM)

CycloneDX SBOMs for every dependency graph in this repo, generated for the T14 hackathon deliverable.

| File | Ecosystem | Source |
|---|---|---|
| `python-sbom.json` | Python | `requirements.txt` (server + tests), via `cyclonedx-py requirements` |
| `frontend-sbom.json` | Node.js | `frontend/` (Vite/React judge & lab UI), via `@cyclonedx/cyclonedx-npm` |
| `server-casper-tx-sbom.json` | Node.js | `server/casper_tx/` (on-chain tx scripts), via `@cyclonedx/cyclonedx-npm` |
| `rust-contracts/*.cdx.json` | Rust | one CycloneDX doc per contract crate in `contracts/`, via `cargo cyclonedx --all` |

## Regenerating

```bash
# Python
pip install cyclonedx-bom
python -m cyclonedx_py requirements -i requirements.txt -o sbom/python-sbom.json --of json

# Node (frontend)
cd frontend && npx @cyclonedx/cyclonedx-npm --ignore-npm-errors --output-file ../sbom/frontend-sbom.json

# Node (casper_tx scripts)
cd server/casper_tx && npx @cyclonedx/cyclonedx-npm --ignore-npm-errors --output-file ../../sbom/server-casper-tx-sbom.json

# Rust (all contract crates)
cargo install cargo-cyclonedx
cd contracts && cargo cyclonedx --format json --all
# then move the generated *.cdx.json files from each crate dir into sbom/rust-contracts/
```

All formats use the CycloneDX 1.x JSON schema and can be scanned by any CycloneDX-compatible SCA tool
(Dependency-Track, Grype, OWASP Dependency-Check, Snyk, etc.).
