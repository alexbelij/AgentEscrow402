# Golden vectors

These are reference outputs from other implementations, used to guarantee
byte-exact compatibility. **Never edit them by hand.** Regenerate from
the reference tool.

## `merkle_golden_vectors.json`

Roots produced by the RWA-Sentinel TypeScript reference implementation
(`rwa-s/agent/src/data/merkleProvenance.ts`) on well-known evidence
batches (sizes 0, 1, 2, 3, 5, 8, 10). Consumed by
`tests/test_merkle_provenance.py::test_root_matches_ts_reference_golden_vectors`
to prove the Python port
(`server/merkle_provenance.py`) is bit-compatible with the TS side.

### Regenerating

If the leaf shape or hashing changes on the TS side, regenerate:

```bash
node <<'JS' > tests/fixtures/merkle_golden_vectors.json
import { createHash } from 'node:crypto';
function sha256Hex(s) { return createHash('sha256').update(s).digest('hex'); }
function leafHash(l) { return sha256Hex(`${l.claimant}:${l.content_hash}:${l.evidence_type}:${l.timestamp}`); }
function buildLevels(hs) {
  if (hs.length === 0) return [[sha256Hex('empty')]];
  const levels = [hs]; let cur = hs;
  while (cur.length > 1) {
    const nxt = [];
    for (let i = 0; i < cur.length; i += 2) {
      const L = cur[i]; const R = i + 1 < cur.length ? cur[i+1] : cur[i];
      nxt.push(sha256Hex(L + R));
    }
    levels.push(nxt); cur = nxt;
  }
  return levels;
}
function root(leaves) { return buildLevels(leaves.map(leafHash)).slice(-1)[0][0]; }
function makeLeaves(n) {
  return Array.from({length:n}, (_,i) => ({
    claimant: `alice-${i}`, content_hash: `hash-${i}`,
    evidence_type: i % 2 === 0 ? 'text' : 'hash',
    timestamp: String(1700000000 + i),
  }));
}
const vectors = [];
for (const n of [0, 1, 2, 3, 5, 8, 10]) {
  const ls = makeLeaves(n); vectors.push({ n, leaves: ls, root: root(ls) });
}
console.log(JSON.stringify(vectors, null, 2));
JS
```

The Python port and the TS reference then MUST agree on every root; the
test fails otherwise.
