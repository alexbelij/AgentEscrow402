# Macaroon Capability Delegation

AE402 ships a Macaroon-style capability layer on top of the existing agent
identity registry. Where `POST /identity/delegate` records a single, static
`(delegator → delegatee → capability_uri)` grant, macaroons let a bearer
**attenuate** an authority they already hold — appending predicates like
`escrow_id=e42`, `capability=release`, `expires<T`, `amount<=100` — without
ever contacting the server. Attenuation only shrinks the authority; the
HMAC chain guarantees a bearer cannot lift a caveat, and third-party
caveats (`add-third-party` + `discharge`) let AE402 defer some checks to
external principals like the arbiter pool.

The design intentionally mirrors the original Macaroons paper
(Birgisson et al., NDSS'14) so the security argument is not "trust
this code" but "this is a well-studied primitive".

## Threat model

Macaroons authenticate **capability**, not identity. Anyone holding a
valid token can exercise it, so treat tokens like bearer credentials:

- **Signed but not encrypted.** Anyone can `decode()` a token and see
  which caveats it carries. Do not put confidential data in caveat
  strings — treat them like URL query parameters.
- **Root secret is authoritative.** Compromise of `MACAROON_ROOT_SECRET`
  is equivalent to full escrow-service takeover. Store it in the same
  secret store as `casper_private_key_path` and rotate together.
- **Discharge keys are derived.** The service can issue discharges for
  its own delegated third-party caveats because we derive discharge
  keys via `HMAC(root, "discharge:" || identifier)`. If you deploy a
  *separate* discharger (recommended in production for the arbiter
  pool), teach the discharger the derived key over an authenticated
  channel — do not share the root secret.
- **Attenuation is monotone-shrinking.** A caveat cannot be dropped by
  the bearer: the HMAC chain hashes every caveat into the terminal
  signature. Any attempt to drop / reorder / append-without-re-HMAC
  fails verification (property tests
  `test_dropping_caveat_is_detected`, `test_reordering_caveats_detected`,
  `test_appending_caveat_without_re_hmac_detected`).

## Endpoints

All endpoints are additive under `/macaroons/*`. When
`MACAROON_ROOT_SECRET` is unset, every route responds `503` — the layer
fails **closed**, not open.

| Method | Path                       | Purpose                                                   |
|--------|----------------------------|-----------------------------------------------------------|
| POST   | `/macaroons/mint`          | Mint a root macaroon with an initial caveat set + expiry. |
| POST   | `/macaroons/attenuate`     | Client-side attenuation, exposed as a convenience.        |
| POST   | `/macaroons/add-third-party` | Bind a third-party caveat (pointer to a discharge).     |
| POST   | `/macaroons/discharge`     | Mint a discharge macaroon (server-signed under derived key). |
| POST   | `/macaroons/verify`        | Verify a token + optional discharges against a fact set.  |
| GET    | `/macaroons/policy`        | Machine-readable caveat grammar.                          |

## Configuration

```bash
# 32 random bytes, base64url or hex. Anything shorter than 24 decoded
# bytes is refused with 503.
export MACAROON_ROOT_SECRET="$(openssl rand -base64 32)"
```

## Caveat grammar

The built-in matcher recognises:

- `capability=X`, `escrow_id=X`, ... — string equality on the verifier
  fact map.
- `amount<N`, `amount<=N`, `amount=N`, `amount>=N`, `amount>N` — numeric
  comparisons.
- `expires<T`, `expires<=T` — `T` is Unix seconds; compared against the
  verifier's `now`.

Third-party caveats have the canonical form `discharge:<identifier>` or
`discharge:<identifier>:<hint>`. The discharger mints a discharge
macaroon whose own identifier equals `<identifier>` and can itself
carry further first-party caveats (e.g. rate-limits, per-request
scoping).

## Example: an agent delegating capped release authority

```python
from sdk.macaroons import mint_root, attenuate, encode, decode, verify, VerifierContext

root = mint_root(SERVICE_SECRET, identifier="agent-alice/rel-42")
# Agent Alice adds her own attenuations before handing to Bob:
tok = attenuate(root, "capability=release")
tok = attenuate(tok, "escrow_id=e42")
tok = attenuate(tok, "amount<=100")
tok = attenuate(tok, f"expires<{int(time.time()) + 3600}")
url_token = encode(tok)  # ship to Bob

# On the release endpoint:
ctx = VerifierContext(
    now=int(time.time()),
    facts={"capability": "release", "escrow_id": "e42", "amount": 42},
)
verify(decode(url_token), SERVICE_SECRET, ctx)  # OK
```

Bob cannot broaden the token — attempting `amount<=1000` after the
`amount<=100` caveat is already applied fails verification because Bob
cannot recompute the terminal HMAC without the root secret.

## Relationship with `/identity/delegate`

`/identity/delegate` remains the source of truth for **who** an agent
has authorised for **what** capability URI. `/macaroons/*` sits above
that layer and lets each capability grant be exercised with dynamic,
per-request attenuations. The two layers are additive; existing
delegation tests (`tests/test_agent_identity_delegation.py`) continue
to pass unchanged.
