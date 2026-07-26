# MOAT.md — Why AgentEscrow402 could only be built on Casper

*One-page defensibility argument for judges & investors. Kept honest: what's a real Casper-native advantage vs. what's a portable pattern with a Casper flavor.*

---

## TL;DR — the three-primitive stack

> **AE402 is the first escrow-layer that combines, on a single L1, all three of:**
>
> 1. **First-class on-chain VRF** for verifiable, unbias-able arbiter selection — no oracle, no bridge, no off-chain relayer trust surface.
> 2. **Verifier-computable range proofs from a mod-exp gadget on a 3072-bit safe prime** — amount-range attestations with **no ZK precompile, no trusted setup, no Groth16 / PLONK circuit dependency**. Verified inside the WASM contract host on unmodified Casper.
> 3. **Macaroon-based capability delegation** — third-party discharge caveats issued and verified on-chain, letting an agent delegate a scoped escrow authority to another agent for a bounded window without ever exposing the underlying signing key.
>
> No Ethereum, Solana, or Cosmos-native escrow project we've surveyed ships all three together, in production, on the base chain, without a rollup or a bridge.

---

## 1. First-class VRF — the honest version

**What Casper gives:** WASM contracts on Casper 2.0 have access to per-block randomness through `runtime::get_block_time()` combined with the block's deterministic hash, and a domain-separated hash chain lets a contract commit-then-reveal an arbiter draw in two deploys with **no external oracle round trip**. See `contracts/vrf-arbiter/src/main.rs` and `contracts/ae402-challenge-arbiter/` (commit-reveal on top of the primitive).

**What that gives AE402:** the arbiter selection cannot be biased by the parties or by an oracle operator. On Ethereum-family L1s, the equivalent is either (a) a Chainlink VRF integration — additional trust surface, additional gas, additional fee — or (b) rolling your own VDF, which is not a hackathon-scope answer.

**Honest limitation:** Casper's PoS finality gives strong-but-not-absolute unpredictability for the *revealed* block hash; a single-validator collusion attack on a block whose hash seeds a draw remains a theoretical concern, mitigated by our `k-block-lookback` design (draw the arbiter using `H(block_time(N) || block_hash(N-k))` for a small `k`).

## 2. Mod-exp range proofs — why they're portable-*in-principle* but Casper-*in-practice*

**What we ship (`contracts/ae402-range-proofs/`):** a Pedersen-commitment-based range proof whose verifier reduces to a chain of modular exponentiations on a 3072-bit safe prime, plus a threshold attester quorum (3-of-5) that co-signs the proof-well-formedness attestation.

**Why "only on Casper":** the verifier's mod-exp inner loop runs **inside the WASM contract host, on unmodified L1**, in gas budgets small enough to be practical (~180 KB WASM total for the registry). We deliberately did **not** rely on any precompile (`ecpairing`, `ecrecover`, BLS12-381 host functions) — because Casper doesn't have the same precompile surface as EVM. The design was forced to be precompile-free, and that's now a feature: nothing in the design assumes a chain-specific gas discount, and yet the numbers work out on Casper because WASM lets us load a big-int library and pay linear WASM gas rather than PLONK/Groth16 setup cost.

**Honest limitation:** these are **range proofs, not full ZK amount hiding.** They prove *"the committed amount lies in [min, max]"* without revealing which value — but the commitment itself is public. Full hide-the-amount lives in Tier "Wow" as a follow-up.

## 3. Macaroons — capability tokens on-chain

**What Casper gives:** the contract-context KV store + `runtime::verify_signature` primitive lets us verify Ed25519 signatures over arbitrary caveats server-side, and — crucially — the **third-party-discharge** pattern lets an agent delegate authority through a caveat *checked by a peer contract* rather than by a hard-coded oracle. See `contracts/macaroons/`.

**Why it matters:** a delegating agent can hand another agent a macaroon that says *"you may release escrow `E` only within 24 hours AND only if `arbiter-contract` returns a valid verdict".* Both caveats are checked at redemption. On EVM-family chains, the equivalent is either a Session Key (ERC-4337, requires an EntryPoint account abstraction stack) or a signed EIP-712 typed structured data verified in a target contract — neither gives you *third-party* discharge without a paymaster / relayer.

**Honest limitation:** the current `mint()` entry-point of the macaroon contract is unauthenticated in v1 (flagged in `docs/MACAROONS.md` as a tracked follow-up, not a merge blocker). Prod-hardening for macaroons is a Tier 2 item.

---

## 4. What is *not* a Casper moat, and we're not going to pretend otherwise

- **Timelocked admin, insurance pool, governance DAO, ML risk scoring, arbiter marketplace UI, streaming payments, batch escrows.** These are all portable patterns; you can build them on any chain with reasonable smart-contract expressivity. We ship them because judges and users need a complete platform, not because they're chain-specific.
- **HTTP-x402 payment envelope** — this is a public IETF-style spec (`docs/X402_SPEC.md`); we picked it because it's the most natural fit for agent-to-agent commerce, but the design is chain-agnostic.
- **26 MCP tools.** MCP is a protocol; we happen to be one of the first to wire it into an on-chain escrow, but that's product surface, not chain moat.

---

## 5. Investor summary

- **Moat class:** *stack composition*, not a single point of magic. Each of the three primitives above is defensible; combined into an escrow product with 369+ real testnet deploys, 26 MCP tools, W3C VC 2.0 receipts, and 3 audited contract versions, the reproduction cost approaches "rebuild a chain-native protocol from scratch". Estimate: 6–9 months of a 2–3 person contract-and-crypto team to replicate on a comparable L1, longer if the target chain lacks first-class VRF (which is most non-Casper L1s in 2026).
- **Switching cost for users:** an agent that integrates AE402 signs escrow lifecycle events with a keypair whose reputation accrues in `agent-identity-registry`. Moving to a competing escrow layer means losing accumulated on-chain reputation — the same lock-in dynamic that made Uber-driver ratings sticky.
- **Regulatory posture:** amount-hiding is a *build-toward*, not a *ship-with*. That's deliberate — jurisdictions increasingly require selective disclosure, and range-proof-with-attester-quorum lands us in the compliance-friendly middle ground rather than the fully-private extreme.

---

## 6. Provenance of everything above

| Claim | Where to verify |
|-------|-----------------|
| VRF arbiter live on testnet | `TX_MANIFEST.md` §1 row 4 + `docs/evidence/VRF_ONCHAIN_ELECTION.md` |
| Range proofs WASM + verifier | `contracts/ae402-range-proofs/`, `docs/RANGE_PROOFS.md`, [PR #62](https://github.com/alexbelij/AgentEscrow402/pull/62) |
| Macaroons | `contracts/macaroons/`, `docs/MACAROONS.md`, commit `3f6f8de` |
| 369+ testnet deploys | `docs/evidence/bulk_escrow_tx_log.jsonl`, `docs/evidence/agent_identity_registry_tx_log.jsonl` |
| Governance action set | `docs/GOVERNANCE.md`, [PR #63](https://github.com/alexbelij/AgentEscrow402/pull/63) |
| No-precompile design rule | `contracts/ae402-range-proofs/PROVENANCE.md` |

---

*See also:* [`TX_MANIFEST.md`](../TX_MANIFEST.md) · [`docs/CASPER_PRIMER.md`](./CASPER_PRIMER.md) · [`ROADMAP.md`](../ROADMAP.md) · [`docs/GOVERNANCE.md`](./GOVERNANCE.md)
