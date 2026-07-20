# Lint baseline — Ruff + Black

**Status:** green as of `feat/ae-ruff-baseline-green`. Closes the P0 Gate 1
gap "Ruff baseline red (74+ warnings), CI gate not honest yet" from
`AE402_FINAL_TASKS_V2.md`.

## Config (in `pyproject.toml`)

```toml
[tool.ruff]
line-length = 120
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "W"]

[tool.ruff.lint.per-file-ignores]
"tests/test_business_logic.py" = ["E402"]

[tool.ruff.lint.isort]
known-first-party = ["server", "sdk"]

[tool.black]
line-length = 120
target-version = ["py311"]
```

The one narrow exception is `tests/test_business_logic.py` — a
deliberately section-organized "mega" test file where imports live next
to the block of tests that exercises them, not hoisted to the top.
Everything else is unfiltered.

## What was fixed (156 → 0)

Baseline at the top of this branch:

```
81  E501  line-too-long
31  I001  unsorted-imports
25  F401  unused-import
12  E402  module-import-not-at-top-of-file
 5  W293  blank-line-with-whitespace
 1  E401  multiple-imports-on-one-line
 1  F841  unused-variable
```

Resolution:

- `ruff check . --fix` cleared 61 (all I001, F401, W293, E401).
- `ruff format .` reformatted 37 files, killing 70 of 81 E501s and the
  remaining W293.
- 10 remaining E501s were **string literals**: OpenAPI contract-role
  descriptions in `server/app.py`, an SQL SELECT in `server/db.py`, two
  pydantic field descriptions in `server/insurance.py`, an error detail
  in `server/multi_asset.py`. All split via implicit string concatenation
  — no message text lost, no noqa cop-out.
- The one F841 was a `result = await ...` in
  `tests/test_ai_arbitration.py::test_history_tracking` that never got
  asserted on. Dropped the binding.
- E402 in `tests/test_business_logic.py` is the intentional design;
  handled at config level, not per-line.

Post-fix Black reformatted one more file (`server/db.py`) after the SQL
split; final state is Ruff + Black both clean.

## CI gate

`.github/workflows/ci.yml` now runs `ruff check .` and
`black --check --line-length 120 .` **before** the test suite. A PR that
adds a lint error fails CI — no more silent baseline drift.

## Regression discipline

If you catch yourself typing `# noqa: E501` because "the line is fine as
it is", split the string. Descriptions belong to users, and users skim
them narrower than 120 cols on average.

If you must add per-file ignores, put them next to the existing
`test_business_logic.py` entry in `pyproject.toml` with a comment
explaining why the file is structurally exempt — never on a whim.

## Verification

```bash
python3 -m ruff check .                          # All checks passed!
python3 -m black --check --line-length 120 .     # 58 files would be left unchanged.
python3 -m pytest -q                             # 450 passed
```
