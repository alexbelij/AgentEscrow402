# AE402 Signed Payloads — Detached Signatures, Nonces, Domain Separation

**Status:** Advisory (opt-in); flip `AE402_ENFORCE_SIGNED_ENVELOPES=1` to enforce.
**Applies to:** `/escrow` (deposit), `/release`, `/refund`, `/dispute`, and any future purpose registered in `KNOWN_PURPOSES`.
**Backwards-compat:** existing x402-v1 clients continue to work unchanged in advisory mode.

---

## 1. Why this exists

Before this hardening layer, AE402 authenticated write-path operations two ways:

1. **x402-v1 payment header** (`X-Payment`) — signed request-metadata with an in-process nonce cache and a 5-minute replay window. Fine for payment metering; too narrow for the escrow verbs.
2. **Arbiter cap-approval signatures** on `/release` and `/resolve` — a domain-scoped multi-sig, but only guards escrows over `release_cap`.

Neither surface prevents an attacker from:

* Replaying a signature captured on one chain (testnet) against another chain (mainnet).
* Replaying a signature captured for one purpose (`escrow.deposit`) at a different endpoint (`escrow.release`).
* Reusing a signature the server has already accepted, after the process restarts (in-memory nonce cache is wiped).
* Signing an arbitrary caller-supplied byte string that the server later interprets as a different structure than the signer intended.

The signed-envelope layer closes all four in one primitive.

---

## 2. The envelope

```json
{
  "domain": {
    "protocol": "AgentEscrow402",
    "version": "v1",
    "chain_id": "casper-test",
    "purpose": "escrow.release"
  },
  "payload": {
    "service_hash": "…",
    "amount_motes": 1000000000
  },
  "signer_pubkey": "<32-byte hex, lowercase>",
  "algorithm": "ed25519",
  "nonce": "<8+ char random>",
  "timestamp": 1723809612,
  "signature": "<64-byte hex, lowercase>"
}
```

Sent as the JSON-encoded value of the `X-AE402-Envelope` request header.

### Signing bytes

`build_signing_bytes(envelope)` returns the exact byte string the signer signed. It is deterministic and includes an explicit 32-byte domain prefix so **the same private key signing the same payload on two different chains, versions, or purposes produces four different signatures**:

```
domain_prefix = SHA-256("AgentEscrow402" || 0x1F || "v1" || 0x1F || "casper-test" || 0x1F || "escrow.release")
signing_bytes = domain_prefix
              || canonical_json(payload)          # keys sorted, no whitespace
              || nonce.encode("utf-8")
              || timestamp_be_uint64              # 8-byte big-endian
```

`0x1F` (ASCII Unit Separator) is not part of any legitimate protocol/purpose name, so no field can bleed into the next.

### Detached, not embedded

The signature is stored **alongside** the payload, not inside it. Handlers, loggers, and Merkle-inclusion code touch `envelope.payload` freely without disturbing signature material. There is one canonical encoding for signing (`build_signing_bytes`); everyone verifies against the same bytes.

---

## 3. Verification pipeline

`verify_envelope(envelope, expected_domain, replay_window_seconds, nonce_store)` returns a `VerifyResult(ok, reason)` and never raises. Reasons form a stable, small enum:

| `reason` | HTTP | Meaning |
| --- | --- | --- |
| `envelope_missing` | 401 | Header absent under strict enforcement. |
| `envelope_bad_json` | 400 | Header not valid JSON. |
| `envelope_bad_shape` | 400 | JSON is not an object. |
| `envelope_bad_fields` | 400 | Required field missing or wrong type. |
| `domain_mismatch` | 400 | Domain-separator does not match the endpoint (wrong chain, version, or purpose). |
| `timestamp_stale` | 401 | Older than `replay_window_seconds` (default 300s). |
| `timestamp_future` | 401 | More than `replay_window_seconds / 2` in the future. |
| `nonce_reused` | 401 | Nonce already seen for this domain within the replay window. |
| `bad_signature` | 401 | Signature failed cryptographic verify. |
| `unknown_purpose` | 400 | Purpose not in `KNOWN_PURPOSES`. |
| `bad_algorithm` | 400 | Algorithm not `ed25519` or `secp256k1`. |
| `nonce_too_short` | 400 | Nonce < 8 characters. |

The check order is deterministic (shape → domain → nonce reuse → timestamp → signature). Each check runs *only* if the previous one passed, so the response reveals exactly which barrier the request hit.

---

## 4. Persistent nonce store

`PersistentNonceStore` is a SQLite table:

```
CREATE TABLE ae402_nonces (
  domain_hash BLOB NOT NULL,   -- SHA-256(domain_prefix)
  nonce       TEXT NOT NULL,
  first_seen  INTEGER NOT NULL,
  PRIMARY KEY (domain_hash, nonce)
);
CREATE INDEX ae402_nonces_first_seen ON ae402_nonces(first_seen);
```

Key properties:

* **Survives process restart.** In-memory OrderedDict is fine for x402 payment metering but useless the moment uvicorn workers cycle.
* **Auto-prunes** everything older than `replay_window_seconds` on every insert.
* **Scoped per domain.** A nonce reused on a *different* purpose or chain is genuinely different and is allowed — the primary key covers `(domain_hash, nonce)`.

Configuration:

* `AE402_NONCE_STORE_PATH=/var/lib/ae402/nonces.sqlite` — persistent volume path.
* `AE402_NONCE_STORE_PATH=:memory:` — in-memory for tests.
* Unset — defaults to `$TMPDIR/ae402_nonces.sqlite`, which survives within a single container but **not** across container rebuilds. In production, point it at a volume.

The store is process-wide (`functools.lru_cache(maxsize=1)`), so per-request handler decoration does not reopen the DB.

---

## 5. Advisory vs strict enforcement

Two decorators, same verifier:

```python
from server.middleware import (
    require_signed_envelope,          # strict — always 401 on missing header
    verify_signed_envelope_if_present, # advisory — allow if missing, verify if present
)

@app.post("/escrow", response_model=EscrowRecord)
@verify_signed_envelope_if_present(purpose="escrow.deposit")
async def create_escrow(req, request, ...):
    ...

@app.post("/admin/danger", response_model=Ack)
@require_signed_envelope(purpose="admin.rotate_keys")
async def rotate_keys(req, request, ..., envelope=None):
    ...
```

**Advisory** is the deployment default for the four existing escrow verbs. Semantics:

| Header state | Advisory | Strict |
| --- | --- | --- |
| Absent | Handler runs; `request.state.ae402_envelope = None`. | 401 `envelope_missing`. |
| Present + valid | Handler runs; `request.state.ae402_envelope = SignedEnvelope`. | Identical. |
| Present + invalid | 4xx with structured `reason`. | Identical. |

**Promotion path** — no code change:

1. Ship server (advisory) and client (attaches header). Wait.
2. Watch logs for `envelope_missing` on any real production caller. Fix them one at a time.
3. When telemetry shows every real caller is attaching envelopes → set `AE402_ENFORCE_SIGNED_ENVELOPES=1` in the deployment env. Restart.
4. If a legitimate client is later added → their envelope is verified strictly from day one.

**Never** ship strict mode into a live deployment without step 2, or every existing client will hard-fail on the next deploy.

---

## 6. Threat model — what this defends, what it doesn't

### Defended

* **Cross-chain replay** — testnet signature valid on mainnet? Domain prefix binds `chain_id`. Rejected `domain_mismatch`.
* **Cross-purpose replay** — signature captured on `/escrow` (deposit) presented at `/dispute`? Domain prefix binds `purpose`. Rejected `domain_mismatch`.
* **Cross-version replay** — signature captured before an on-chain contract upgrade re-presented after? Domain prefix binds `version`. Rejected `domain_mismatch` after the operator bumps the version in `AE402_ENVELOPE_VERSION`.
* **Within-window replay** — signature captured and re-submitted before it expires? Nonce store rejects with `nonce_reused`.
* **Cross-restart replay** — process restarts, in-memory cache lost, attacker replays? SQLite-backed nonce store survives. Rejected `nonce_reused`.
* **Payload smuggling** — attacker rebuilds signing bytes with a different canonical serialization? Canonical JSON (`sort_keys=True`, no whitespace, no NaN) has one representation; attacker signs a different string, verification fails.
* **Clock skew abuse** — attacker forges a timestamp in the far future to survive replay windows? Future skew capped at `replay_window / 2`. Rejected `timestamp_future`.
* **Low-entropy nonces** — attacker uses "0" as nonce and hopes for collision-free replay? Server rejects nonces shorter than 8 characters (`nonce_too_short`).

### Not defended (out of scope for this layer)

* **Signer key compromise.** If the attacker holds the private key, they hold the world. Rotate keys through the on-chain arbiter registry and bump `version` to invalidate every pre-rotation envelope.
* **On-chain contract logic bugs.** Envelope proves *someone with the key* authorized the operation. It does not vouch for the correctness of the state transition — that's the contract's job.
* **Transport tampering.** Use TLS. The envelope integrity check is over the parsed JSON, not over the raw HTTPS bytes.
* **Downstream side effects.** If a signed request causes the server to make a downstream call (e.g. Casper deploy), the envelope does not cover the downstream request; the server's own credentials do.

---

## 7. Client example

Python signer (SDK-quality reference):

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import time, json, requests

from server.signed_envelope import (
    DomainSeparator,
    sign_envelope_ed25519,
)

sk = Ed25519PrivateKey.generate()
priv = sk.private_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PrivateFormat.Raw,
    encryption_algorithm=serialization.NoEncryption(),
)
pub = sk.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)

domain = DomainSeparator(
    protocol="AgentEscrow402",
    version="v1",
    chain_id="casper-test",
    purpose="escrow.release",
)

envelope = sign_envelope_ed25519(
    domain=domain,
    payload={"service_hash": SERVICE_HASH},
    nonce=f"nonce-{int(time.time_ns())}",
    timestamp=int(time.time()),
    private_key_bytes=priv,
    public_key_bytes=pub,
)

resp = requests.post(
    "https://ae402.example/release",
    json={"service_hash": SERVICE_HASH},
    headers={"X-AE402-Envelope": envelope.to_json()},
)
```

Curl (envelope prepared out-of-band):

```bash
curl -X POST https://ae402.example/release \
     -H "Content-Type: application/json" \
     -H "X-AE402-Envelope: $(cat envelope.json)" \
     -d '{"service_hash":"…"}'
```

---

## 8. Testing

* `tests/test_signed_envelope.py` — 20 unit tests covering domain prefix stability, cross-domain rejection, tamper detection, replay-window boundaries, nonce reuse, persistent-store survival, unknown purpose, and bad algorithm.
* `tests/test_signed_envelope_endpoints.py` — 11 integration tests covering advisory pass-through, advisory reject on tampered/wrong-purpose/replayed envelope, strict `envelope_missing`, and parity across `/escrow`, `/release`, `/refund`, `/dispute`.

All 31 pass as part of the full suite (`pytest tests/` — 635/635 green).

---

## 9. Registering a new purpose

Extend `KNOWN_PURPOSES` in `server/signed_envelope.py`:

```python
KNOWN_PURPOSES: frozenset[str] = frozenset({
    ...,
    "insurance.claim_vote",
})
```

Then decorate the new endpoint:

```python
@app.post("/insurance/claim")
@verify_signed_envelope_if_present(purpose="insurance.claim_vote")
async def submit_claim(...):
    ...
```

No other changes. The domain-separator, replay window, nonce store, and rollout mode are inherited.
