# OpenAPI Schema

The canonical HTTP API surface for AE402 lives at `docs/openapi.yaml`.
It is **generated** from the running FastAPI app (`server/app.py`) —
never edited by hand.

## Regenerating

After any change to route signatures, request/response models, or
Pydantic schemas anywhere under `server/`, regenerate the file:

```
python scripts/gen_openapi.py
git add docs/openapi.yaml
```

CI (`openapi-drift.yml`) runs `--check` on every PR touching `server/`
or the yaml itself and fails the PR if they've drifted. The error
message tells you exactly which command to run.

## Determinism

The generator is byte-stable across runs on the same commit — two
consecutive `python scripts/gen_openapi.py` produce identical files.
This matters because:

1. It lets us use `git diff --exit-code` as a drift signal — no false
   positives from map-key ordering flakiness.
2. SDK consumers can pin against a specific commit's yaml and trust
   that a rebuild produces the same client stubs.

Two normalisations make this work:

- **Sorted keys.** `yaml.safe_dump(..., sort_keys=True)` — schemas come
  out in alphabetical order regardless of how FastAPI walked them.
- **Time-dependent defaults are flattened to a sentinel.** Pydantic
  fields like `expiry_timestamp: float = Field(..., gt=time.time())`
  otherwise inject the current wall-clock into `exclusiveMinimum` on
  every run. The generator replaces any numeric in the
  `1.7e9 .. 2.0e9` unix-timestamp range inside `default` / `minimum` /
  `exclusiveMinimum` with a fixed `1700000000.0` sentinel. Real
  timestamp values in requests/responses are unaffected — this only
  touches schema metadata.

## What consumers should generate against

- **TypeScript** — `sdk-ts/` already has generated types under
  `sdk-ts/src/types.ts`. If those get out of date, regenerate with
  `openapi-typescript`:
  ```
  cd sdk-ts && npx openapi-typescript ../docs/openapi.yaml -o src/types.ts
  ```
- **Python** — the Python SDK talks to the API through `httpx` with
  hand-written type hints (see `sdk/client.py`). We do NOT
  auto-generate a Python client from openapi.yaml because Pydantic
  models under `server/models.py` are already the source of truth,
  and re-exporting them into the SDK gives us richer types than an
  openapi codegen would.
- **Third-party** — point any openapi-aware tool
  (`openapi-generator`, `datamodel-code-generator`, Postman import)
  at `docs/openapi.yaml` on `main`. The file is CI-guaranteed to
  match the deployed backend at that commit.

## Version pinning

`info.version` in the yaml is pinned to `[project].version` in
`pyproject.toml`. A package bump (see `docs/RELEASING.md`) produces
exactly one line of diff in the yaml — not a whole-file churn.

## Related

- `scripts/gen_openapi.py` — the generator.
- `.github/workflows/openapi-drift.yml` — the CI gate.
- `tests/test_gen_openapi.py` — unit + integration tests for the generator.
- `docs/RELEASING.md` — how SDKs get published.
