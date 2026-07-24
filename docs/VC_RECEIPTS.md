# W3C VC 2.0 Escrow Receipts

AE402 can issue **W3C Verifiable Credentials 2.0** as cryptographically
verifiable receipts for escrow lifecycle events (`release`, `refund`,
`resolve`). Receipts are portable, verifiable offline, and follow the
official [W3C VC Data Model 2.0](https://www.w3.org/TR/vc-data-model-2.0/).

## Why VCs

- **Portable**: a receipt is a self-contained JSON blob a payer or
  receiver can archive, share, or present to auditors.
- **Verifiable offline**: the issuer's public key is embedded in the
  issuer DID (`did:key:z...`), so any client with the VC and the standard
  can verify without contacting AE402.
- **Interop-standard**: JSON-LD `@context` + typed credentialSubject
  makes receipts consumable by any VC-aware wallet / auditor.
- **Tamper-evident**: any bit change invalidates the Ed25519 signature.

## Proof suite

**Ed25519Signature2020** over the JCS canonicalization (RFC 8785) of the
credential body (excluding `proof`). Chosen over LD-Proofs /
DataIntegrityProof because it needs no JSON-LD processor and gives
byte-exact reproducible signatures — critical for on-chain anchoring or
Merkle inclusion.

Issuer DID: `did:key:z<base58btc(multicodec(ed25519-pub) || pubkey)>`.
No DID resolver required.

## Configuration

| Env var | Type | Default | Description |
|---|---|---|---|
| `VC_ISSUER_SEED` | base64 / base64url / hex / 32-char ASCII | *(unset)* | 32-byte Ed25519 seed. Issuance endpoints return `503` if unset. |
| `VC_AUTO_ISSUE_ON_RELEASE` | `1`/`true`/`yes` | off | If set, `/release`, `/refund`, `/resolve` responses include a `receipt` field with the signed VC (opt-in — off by default so we never mask escrow failures with issuance errors). |

Verification does **not** require the issuer secret — the public key is
embedded in the issuer DID.

## Endpoints

```
GET  /vc/issuer                      → { did, public_key_hex, proof_suite, supported_events }
POST /vc/receipts/issue              → { credential, summary }
POST /vc/receipts/verify             → { valid, summary?, error_type?, error_detail? }
```

### `POST /vc/receipts/issue`

Request:

```json
{
  "event": "release",
  "service_hash": "0xdeadbeef...",
  "escrow_id": "0xdeadbeef...",
  "payer": "0201f2...casperpubkey",
  "receiver": "0203a8...casperpubkey",
  "amount_motes": 1000000,
  "asset": "CSPR",
  "issuance_ts": 1732000000,
  "extra_claims": {"disputeId": "0xabc", "arbiterQuorum": 3}
}
```

- `event` — one of `release`, `refund`, `resolve`.
- `issuance_ts` optional; defaults to `time.time()`. Pass explicitly for
  reproducible receipts (e.g. block-time-anchored).
- `extra_claims` optional; may not collide with reserved keys (`id`,
  `type`, `serviceHash`, `event`, `payer`, `receiver`, `amount`).

Response — signed VC + summary. Example receipt body:

```json
{
  "@context": [
    "https://www.w3.org/ns/credentials/v2",
    "https://ae402.dev/contexts/escrow-receipt/v1"
  ],
  "type": ["VerifiableCredential", "EscrowReleaseReceipt"],
  "issuer": "did:key:z6Mkv...",
  "issuanceDate": "2024-11-19T09:46:40Z",
  "credentialSubject": {
    "id": "urn:ae402:escrow:0xdeadbeef",
    "type": "AE402Escrow",
    "serviceHash": "0xdeadbeef",
    "event": "release",
    "payer": "0201f2...",
    "receiver": "0203a8...",
    "amount": {"value": 1000000, "asset": "CSPR"}
  },
  "proof": {
    "type": "Ed25519Signature2020",
    "created": "2024-11-19T09:46:40Z",
    "verificationMethod": "did:key:z6Mkv...#z6Mkv...",
    "proofPurpose": "assertionMethod",
    "proofValue": "z3rhc..."
  }
}
```

### `POST /vc/receipts/verify`

Request:

```json
{"credential": {...}, "expected_issuer": "did:key:z6Mkv..." /* optional */}
```

Response on success:

```json
{"valid": true, "summary": {"issuer": "...", "event": "release", ...}}
```

Response on failure — `valid: false` + `error_type` in
`Schema | ProofMissing | SignatureInvalid | Verification`, plus
`error_detail`.

## Verification checklist for consumers

A verifier MUST:

1. Check `type` includes `VerifiableCredential` and the expected receipt
   type (`EscrowReleaseReceipt`, etc.).
2. Extract the Ed25519 public key from the `issuer` DID.
3. Re-canonicalize the credential (excluding `proof`) with JCS.
4. Verify the Ed25519 signature.
5. Check the `serviceHash` matches the expected escrow.
6. Check `issuanceDate` is within an acceptable window (replay guard).
7. Compare the issuer DID against an allow-list.

`sdk/vc_receipts.py:verify_receipt` performs (1)–(4). Consumers must add
(5)–(7) in their application layer.

## Threat model

- **Forgery** — infeasible without the issuer signing key (Ed25519,
  128-bit classical security).
- **Tamper** — any byte change breaks JCS reconstruction and Ed25519
  verify.
- **Replay** — receipts include `serviceHash` + `issuanceDate`; verifier
  MUST scope them to the intended escrow.
- **Key rotation** — new issuer DID for the rotated key. Historical
  receipts remain verifiable under the old DID; consumers must maintain
  an issuer allow-list.
- **Revocation** — not modeled in v1. Receipts attest historical events;
  revocation semantics don't map cleanly. If needed later, add
  `credentialStatus` field per the VC 2.0 revocation spec.
- **Missing secret** — issuance endpoints fail closed with `503`; the
  auto-issue hook returns `None` (never breaks the escrow event).

## Programmatic use

```python
from sdk.vc_receipts import IssuerKey, issue_receipt, verify_receipt

issuer = IssuerKey.from_seed(seed_bytes)
vc = issue_receipt(
    issuer,
    event="release",
    service_hash="0xdeadbeef",
    escrow_id="0xdeadbeef",
    payer="payer_pk",
    receiver="receiver_pk",
    amount_motes=1_000_000,
)
verify_receipt(vc)                                # raises on invalid
verify_receipt(vc, expected_issuer=issuer.did)    # also checks issuer
```

## Relation to existing AE402 features

- **Merkle provenance** (`server/merkle_provenance.py`) — VCs can be
  Merkle-anchored: a batch of receipt hashes forms a leaf set, and the
  root can be posted on-chain. Same crypto assumptions; complementary
  layers (per-event receipt + on-chain aggregate root).
- **Macaroon delegation** (`sdk/macaroons.py`) — orthogonal:
  macaroons are *forward* capabilities (permission to act); VC receipts
  are *backward* attestations (proof an action happened).
- **AI arbitration** (`server/ai_arbitration.py`) — resolve receipts
  can carry an `extra_claims["arbitrationRecommendation"]` snapshot for
  audit trail.
