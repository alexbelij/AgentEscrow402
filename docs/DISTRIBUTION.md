# Distribution

> **Question this answers.** How does AE402 reach an engineer who
> heard about it and now wants to use it? What are the channels, in
> what order, with what SLAs?
>
> **Audience.** Integrators, potential contributors, judges wondering
> how the project sustains itself post-hackathon.

---

## 1. Channels

We ship AE402 through five distinct channels, each with a different
promise:

| Channel | Content | Freshness | Audience | Phase |
|---|---|---|---|---|
| **GitHub repo** | Full source | `main` = HEAD | Contributors, security auditors, curious readers | Phase 0 (now) |
| **PyPI (`pip install agent-escrow-402`)** | SDK + CLI | Tagged releases only | Integration engineers | Phase 4 |
| **npm (`@ae402/mcp-sdk`)** | TypeScript MCP client shim | Tagged releases | Node-based MCP hosts | Phase 4 |
| **Sandbox backend URL** | Live testable REST + MCP | Redeployed per merge to `main` | Judges, pilot integrators, tinkerers | Phase 1 |
| **MCP registry listing** | AE402 tool bundle | Tagged releases | Claude Desktop, MCP-native clients | Phase 4 |

Order = maturity order. GitHub is the source of truth today; PyPI /
npm are Phase-4 gates that depend on a first stable API.

---

## 2. Versioning

- **Source repo:** `main` is the working line. Every merge is
  green-CI-only.
- **Contract hashes:** Casper contract hashes are pinned per deploy,
  documented in `docs/deployment/` and surfaced by the backend at
  `/health` + `/metrics` (`ae402_build_info{contract_escrow="…"}`).
- **SDK:** SemVer once we publish to PyPI. Until then, git ref = pin.
- **Backend API:** documented at `docs/API.md`. Breaking changes
  require a `MAJOR` bump and a migration note in `CHANGELOG.md`.
- **MCP tool catalogue:** each tool declares its `inputSchema`
  version implicitly via its `name`; a breaking rename becomes a new
  tool.

The last three converge on SemVer in Phase 4. Before that,
integrators pin by commit hash.

---

## 3. Publish flow (Phase 4)

Trigger: a git tag matching `v[0-9]+\.[0-9]+\.[0-9]+`.

Pipeline (in `.github/workflows/publish.yml`, drafted separately):

1. Full test suite green.
2. `make judge-demo` green (on-chain smoke).
3. `make judge-lite` green (Python-only smoke).
4. Build SDK sdist + wheel; publish to PyPI via API token stored in
   GitHub Secrets.
5. Build npm package (`@ae402/mcp-sdk`); publish to npm.
6. Update MCP registry listing with new tool bundle version.
7. Redeploy sandbox backend from the tagged commit.
8. Post release notes to GitHub Releases + Discord announcement
   channel.

Manual gates:

- **Contract hash change** — requires an on-chain redeploy separately
  (see `docs/ONCHAIN_DEPLOY.md`), NOT triggered by the tag pipeline.
- **Breaking change** — requires a `MAJOR` version bump and a
  `docs/upgrade/vX.Y-to-vX+1.0.md` note.

---

## 4. Sandbox backend

**URL.** Announced in the AE402 README once Phase 1 lands. Redeployed
on every merge to `main`.

**Guardrails:**

- Rate limit: 60 req/min per IP.
- Escrow amount capped at `10_000_000_000 motes` (10 CSPR-equivalent
  sandbox units).
- Data reset every 24h.
- No real key custody — sandbox mode accepts the `?sender=` unsigned
  path.

**Not for production.** For pilot / production use we ship a
container image via Docker Hub (`ae402/backend:vX.Y.Z`) and a
`docker-compose.yml` in `deploy/`. Both land in Phase 2.

---

## 5. Discovery paths (how do people find AE402?)

Prioritised, high → low reach per unit of effort:

1. **MCP registry listing** (Phase 4). Auto-discovery in every
   MCP-native client that browses the registry. Highest reach for
   agent devs; lowest effort per install.
2. **A curated demo endpoint that just works.** `sandbox.ae402.io`
   + `docs/JUDGE_QUICKSTART.md`. Zero-friction try-before-install.
3. **Ecosystem integrations posts.** LangGraph tutorials, CrewAI
   demos, LlamaIndex cookbooks. Written after Phase 2 pilots when
   we have real war stories.
4. **Contract-audit reports.** After Phase 3, a link to the audit
   report becomes a top-of-README badge. Trust-signal, not reach,
   but converts high-intent visitors.
5. **Conference talks / paper.** Long-tail. Written from Phase-4
   traction numbers, not from hackathon speculation.

---

## 6. Support & incident response

**Public issues.** GitHub Issues. First response ≤ 3 business days
in Phase 1 (best-effort), ≤ 24h from Phase 2 onward (pilot SLA).

**Security disclosures.** `security@ae402.io` (routed to a private
channel). PGP key published in `SECURITY.md`. Responsible disclosure
policy with a 90-day embargo option.

**Public status page.** `status.ae402.io` from Phase 4, hooked to
the Prometheus alertmanager on the sandbox backend.

---

## 7. Licence & terms

- **Code:** MIT (see `LICENSE`).
- **Contracts:** MIT (same as source).
- **Contribution:** DCO sign-off on every PR (see `CONTRIBUTING.md`).
- **Sandbox usage:** No warranty; see the notice at the sandbox root
  URL.
- **Paid hosted (Phase 4):** ToS + privacy policy at
  `docs/legal/ToS-v1.md` and `docs/legal/Privacy-v1.md`. Drafted, not
  yet published.

---

## 8. Related

- `docs/POST_HACKATHON_ROADMAP.md` — the phase gates each channel
  attaches to.
- `docs/INTEGRATION_GUIDE.md` — what integrators do once they've
  arrived.
- `docs/OBSERVABILITY.md` — what operators do once they've deployed.
- `SECURITY.md` + `docs/THREAT_MODEL.md` — the trust posture we
  ship these channels under.
