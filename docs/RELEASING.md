# Releasing the AgentEscrow402 SDKs

This document is the owner runbook for publishing new SDK versions. Both
SDKs (Python `agentescrow402` on PyPI, TypeScript `@ae402/sdk` on npm)
version independently — you can ship a Python-only patch without moving
the TS SDK, and vice versa.

## TL;DR (happy path)

**Python SDK — 0.2.0 → 0.2.1 (patch):**

1. Bump `version` in `pyproject.toml`.
2. Add a section to `CHANGELOG.md` mentioning `0.2.1`.
3. Commit, open PR, get review, merge to `main`.
4. Locally: `git tag py-sdk-v0.2.1 && git push origin py-sdk-v0.2.1`.
5. GitHub Actions runs `sdk-publish.yml`, uploads to **TestPyPI** and
   attaches an sdist+wheel artifact. Nothing lands on real PyPI yet.
6. Smoke-test:
   ```
   pip install -i https://test.pypi.org/simple/ \
                --extra-index-url https://pypi.org/simple/ \
                agentescrow402==0.2.1
   python -c "from sdk import EscrowClient; print(EscrowClient)"
   ```
7. Go to **Actions → SDK Publish → Run workflow**, pick `target=python`,
   type `publish` in the confirm box, click **Run**.
8. The job runs `pypa/gh-action-pypi-publish@release/v1` via **Trusted
   Publishing** (OIDC — no long-lived token in the repo). Done.

**TypeScript SDK — 0.1.0 → 0.1.1 (patch):**

1. Bump `version` in `sdk-ts/package.json`.
2. Add a section to `CHANGELOG.md` mentioning `0.1.1`.
3. Merge to `main`.
4. `git tag ts-sdk-v0.1.1 && git push origin ts-sdk-v0.1.1`.
5. GitHub Actions runs `npm publish --dry-run` and attaches the `.tgz`.
6. Smoke-test locally: `npm install ./ae402-sdk-0.1.1.tgz` in a
   scratch project.
7. Manual dispatch with `target=typescript`, `confirm=publish`. Done.

## Version semantics

We follow [SemVer](https://semver.org). For **both** SDKs specifically:

- **Patch** (`0.2.0 → 0.2.1`): bug fix, docs, added optional parameter
  with default, tightened validation that only rejects previously-broken
  inputs. Client code compiles/works unchanged.
- **Minor** (`0.2.0 → 0.3.0`): new endpoint wrapper, new optional
  argument, new module, expanded types. Old code continues to work.
- **Major** (`0.2.0 → 1.0.0`): removed method, changed method signature,
  reordered positional args, renamed public symbol, changed default
  behavior in a way clients notice. **Requires** a `docs/UPGRADE_PATH.md`
  entry.

**API surface = anything imported from `sdk/__init__.py` (Python) or the
`exports` block in `sdk-ts/package.json` (TypeScript).** Private helpers
(`_prefix`, files not re-exported) are not part of the versioned surface.

## Pre-flight checklist (before pushing the tag)

- [ ] `pytest -q` passes locally (or CI is green on `main`).
- [ ] `pyproject.toml` version matches the tag you're about to push.
- [ ] `sdk-ts/package.json` version matches for the TS tag path.
- [ ] `CHANGELOG.md` has an entry for the new version.
- [ ] No breaking changes without a matching `docs/UPGRADE_PATH.md`
      entry (see also `docs/POST_HACKATHON_ROADMAP.md`).
- [ ] Public API additions have at least one doctest or example in the
      module docstring.

The `sdk-publish.yml` workflow re-checks (1), (2), (3) and errors out
early if any of them drift, so a corrupt tag can never publish garbage.

## Recovering from a bad release

**Rule zero: you cannot delete a version from PyPI or npm.** You can
only *yank* it, which hides it from resolvers but leaves a tombstone. So:

1. **Yank the bad version.**
   - PyPI: `Manage → Releases → Options → Yank` (or `twine` API).
   - npm:  `npm deprecate @ae402/sdk@0.1.1 "yanked: <reason>"`.
2. **Ship a fixed patch immediately** (`0.2.2` / `0.1.2`) with the fix
   and a CHANGELOG note pointing at the yank reason.
3. Never re-use the yanked version number — it's burned.

If the bug is only in the tarball (packaging error, missing file), you
still bump the patch — you cannot re-upload the same version.

## Environment / secrets

The publish workflow needs these repo secrets configured in
`Settings → Secrets and variables → Actions`:

- `TEST_PYPI_TOKEN` — TestPyPI API token (project-scoped, `pypi-`
  prefix). Only used for the dry-run TestPyPI upload. Optional — the
  job skips this step with a warning if unset.
- `NPM_TOKEN` — npm automation token with `Publish` access on
  `@ae402/sdk`. Required for `target=typescript, confirm=publish`.

**PyPI production publishing does NOT use a token.** It uses
[Trusted Publishing (OIDC)](https://docs.pypi.org/trusted-publishers/):

1. On https://pypi.org/manage/project/agentescrow402/settings/publishing/
   add a new trusted publisher pointing at:
   - Owner: `alexbelij`
   - Repository: `AgentEscrow402`
   - Workflow: `sdk-publish.yml`
   - Environment: (leave blank)
2. The workflow's `permissions: id-token: write` and the
   `pypa/gh-action-pypi-publish` step then mint short-lived credentials
   during the run itself. No secret to leak.

## Beta / pre-release channel

We publish beta versions to the same registry with a pre-release suffix
so testers can `pip install agentescrow402==0.3.0b1`:

- Python: append `b1`, `b2`, `rc1` etc. to the version
  (e.g. `0.3.0b1`). PyPI resolvers correctly rank these below `0.3.0`.
- TS: append `-beta.1` etc. (`0.2.0-beta.1`). Publish with
  `npm publish --tag beta` so `npm install @ae402/sdk` still picks up
  `latest` (i.e. the stable version). Testers opt in with
  `npm install @ae402/sdk@beta`.

The workflow does not need special handling for beta tags — just tag
`py-sdk-v0.3.0b1` / `ts-sdk-v0.2.0-beta.1` and it Just Works.

## What the workflow does NOT do

- **Does not** create GitHub Releases. Do that manually with the tag
  URL after the publish succeeds — attach the wheel + `.tgz` from the
  workflow's artifacts to make offline install trivial.
- **Does not** publish docs. Docs live in `docs/` in-repo; the site
  build (`docs/site.yml` — placeholder for a Docusaurus/MkDocs setup)
  will read the SDK version from `pyproject.toml` when we wire it in.
- **Does not** auto-bump the version. Version bumps are a human PR —
  they're the single point where you decide "is this really a minor?".
- **Does not** notify users. Announcements go to Slack + the GitHub
  Release notes; there's no auto-tweet.

## Related

- `.github/workflows/sdk-publish.yml` — the automation.
- `.github/workflows/sdk-version-check.yml` — the PR gate.
- `CHANGELOG.md` — human-readable release notes.
- `docs/POST_HACKATHON_ROADMAP.md` — where new features are queued.
- `docs/DISTRIBUTION.md` — which channels we push each SDK to and why.
