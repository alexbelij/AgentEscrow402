# Merkle Provenance for Arbitration Evidence (AE-8)

Every arbitration decision now carries an `evidence_root` — a Merkle root
computed deterministically over the evidence set the arbitrator saw at
decision time. The root lets any third party later prove, without
trusting the arbitrator or the API, that a specific piece of evidence
was in the set that produced a given verdict.

## Where it lives

- Implementation: `server/merkle_provenance.py`
- Wired into: `server/ai_arbitration.py` (`ArbitrationAgent.analyze_dispute`)
- Response field: `ArbitrationRecommendation.evidence_root` (hex string, `""` when no evidence)
- Also folded into `analysis_hash` pre-image, so tampering with the
  evidence set changes both `evidence_root` and `analysis_hash`.

## Leaf pre-image

```
leaf_hash = sha256("<claimant>:<content_hash>:<evidence_type>:<timestamp>")
```

All fields are stringified. `timestamp` is the same integer the API took
in, rendered without padding.

## Tree math

- Sender evidence appears first (order-preserving), then receiver
  evidence — this defines the leaf order.
- Parent nodes: `sha256(left || right)` (hex-string concatenation).
- Odd level: the last node is duplicated (standard "last leaf
  duplication" convention).
- Empty batch: `sha256("empty")`. Well-defined even when both sides
  submit nothing.

Same math as the RWA-Sentinel TypeScript reference
(`rwa-s/agent/src/data/merkleProvenance.ts`). The two implementations
are byte-equal on every batch — enforced by
`tests/test_merkle_provenance.py::test_root_matches_ts_reference_golden_vectors`
against `tests/fixtures/merkle_golden_vectors.json`.

## Independently verifying an evidence item

Given the arbitrator returned `evidence_root = R`, and a caller believes
their `claimant / content_hash / evidence_type / timestamp` were in the
set:

1. Reconstruct the full evidence list (order-preserved: sender first,
   then receiver).
2. Compute the inclusion proof for the target `content_hash` via
   `build_inclusion_proof(leaves, target_content_hash)`.
3. Verify with `verify_inclusion_proof(proof, R)`.

Passing verification proves that this evidence item was one of the
inputs to the verdict; failing verification means either the target was
not present, the caller's leaves diverge from what the arbitrator saw,
or `R` was tampered with.

## Cross-language use

Because the leaf pre-image is a plain string and hashing is stdlib
sha256, any language that can produce the same string and sha256 it
can verify a proof produced by AE402 without touching Python — see the
regeneration recipe in `tests/fixtures/README.md`.

## What this does NOT provide

- It does not anchor the root on-chain by itself; that's a separate
  step (a future batch anchor tx).
- It does not sign the root; provenance authenticity relies on the
  arbitrator's `analysis_hash` (which now includes the root).
- It does not deduplicate — two evidence items with the same
  `(claimant, content_hash, evidence_type, timestamp)` produce
  identical leaf hashes but occupy two positions in the tree. Callers
  wanting dedup should dedup at the API boundary.
