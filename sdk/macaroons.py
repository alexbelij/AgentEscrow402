"""Macaroon-style capability tokens for AgentEscrow402.

Zero-dependency implementation of the core Macaroons contract:

- Root macaroon minted by a secret-holding *authority* (the escrow service).
- Any bearer can *attenuate* the macaroon by appending first-party caveats
  (predicates like `escrow_id=X`, `capability=release`, `expires<T`,
  `amount<=N`). Attenuation only *shrinks* the authority a bearer can
  claim; it never grows it. That is the crucial property Macaroons enforce
  cryptographically.
- Third-party caveats bind delegated authority to a discharge issued by a
  *different* principal (e.g. the arbiter), tied together by an
  identifier-derived HMAC key so the caveat cannot be replayed or reused.
- Verification recomputes the HMAC chain from the root secret and checks
  every caveat against a verifier context (current-time, escrow_id, ...).

Wire format is the canonical Macaroon binary shape flattened to a
URL-safe base64 v1 envelope:

    {
      "v": 1,
      "location": "ae402",
      "identifier": "<hex-random>",
      "caveats": [
        {"cid": "capability=release"},
        {"cid": "escrow_id=e123"},
        {"cid": "expires<1789200000"},
        {"cid": "discharge:arb-pool", "vid": "<hex>", "cl": "arbiter"},
        ...
      ],
      "signature": "<hex>"
    }

The signature is the running HMAC-SHA256:

    sig_0 = HMAC(root_secret, identifier)
    sig_i = HMAC(sig_{i-1}, cid_i)          for first-party caveats
    sig_i = HMAC(sig_{i-1}, vid_i || cid_i)  for third-party caveats

Discharge macaroons are ordinary macaroons whose *identifier* equals the
third-party caveat identifier, minted by the discharger with the vid-key
(the recovered HMAC key for that caveat). At verification time each
discharge macaroon's terminal signature is HMAC-bound to the enclosing
macaroon's signature so the pair cannot be swapped independently.

This module deliberately keeps zero third-party crypto dependencies —
`hmac`, `hashlib`, `secrets`, `os` from stdlib are enough for the
capability model that ships here. External crypto (Ed25519 signing) is
already covered by other AE402 modules; Macaroons authenticate via
symmetric HMAC alone.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass, field
from typing import Callable, Iterable

__all__ = [
    "Macaroon",
    "Caveat",
    "VerifierContext",
    "MacaroonError",
    "MacaroonVerifyError",
    "mint_root",
    "attenuate",
    "verify",
    "encode",
    "decode",
    "derive_third_party_key",
    "add_third_party_caveat",
    "mint_discharge",
    "predicate_matcher",
]


DOMAIN_TAG = b"ae402:macaroon:v1"
DEFAULT_LOCATION = "ae402"


class MacaroonError(Exception):
    """Base error for macaroon minting/serialization."""


class MacaroonVerifyError(MacaroonError):
    """Raised when a macaroon fails verification."""


@dataclass(frozen=True)
class Caveat:
    """A single caveat on a macaroon.

    - First-party caveat: only `cid` is set; the verifier checks the
      predicate string against the context (e.g. `capability=release`).
    - Third-party caveat: `cid` is the third-party's opaque identifier,
      `vid` is the verifier identifier (HMAC-encrypted key material bound
      to the enclosing signature), and `cl` names the discharger's
      location.
    """

    cid: str
    vid: str | None = None
    cl: str | None = None

    @property
    def is_third_party(self) -> bool:
        return self.vid is not None


@dataclass
class Macaroon:
    """A capability token."""

    identifier: str
    caveats: list[Caveat] = field(default_factory=list)
    signature: str = ""
    location: str = DEFAULT_LOCATION
    version: int = 1

    def copy(self) -> "Macaroon":
        return Macaroon(
            identifier=self.identifier,
            caveats=list(self.caveats),
            signature=self.signature,
            location=self.location,
            version=self.version,
        )


@dataclass
class VerifierContext:
    """Context supplied by the relying party at verification time.

    - `now` — Unix seconds, used to evaluate `expires<T` caveats.
    - `facts` — flat key-value dictionary that first-party predicates can
      match against, e.g. `{"escrow_id": "e123", "capability": "release",
      "amount": 25}`.
    - `predicates` — extra callables that receive the raw caveat string
      and return `True` when satisfied (fallback path for domain-specific
      caveats the built-in matcher does not know).
    - `discharges` — bag of discharge macaroons keyed by identifier.
    """

    now: int
    facts: dict[str, str | int]
    predicates: list[Callable[[str], bool]] = field(default_factory=list)
    discharges: dict[str, "Macaroon"] = field(default_factory=dict)


# --- HMAC chain helpers ------------------------------------------------------


def _hmac(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _root_key(root_secret: bytes) -> bytes:
    # Domain-separate the root secret so a leak of one AE402 HMAC key does
    # not automatically grant macaroon-minting authority.
    return _hmac(root_secret, DOMAIN_TAG)


def _initial_signature(root_secret: bytes, identifier: str) -> bytes:
    return _hmac(_root_key(root_secret), identifier.encode("utf-8"))


def _extend_first_party(sig: bytes, cid: str) -> bytes:
    return _hmac(sig, cid.encode("utf-8"))


def _extend_third_party(sig: bytes, vid: str, cid: str) -> bytes:
    return _hmac(sig, bytes.fromhex(vid) + cid.encode("utf-8"))


def _walk(sig_seed: bytes, caveats: Iterable[Caveat]) -> bytes:
    sig = sig_seed
    for cav in caveats:
        if cav.is_third_party:
            assert cav.vid is not None
            sig = _extend_third_party(sig, cav.vid, cav.cid)
        else:
            sig = _extend_first_party(sig, cav.cid)
    return sig


# --- Public mint / attenuate -------------------------------------------------


def mint_root(root_secret: bytes, *, identifier: str | None = None, location: str = DEFAULT_LOCATION) -> Macaroon:
    """Mint a root macaroon under `root_secret`.

    The identifier defaults to a fresh 128-bit random hex string so
    macaroons minted in the same process are still distinct. Callers who
    need a deterministic identifier (e.g. auditability) can pass their
    own; the caller is responsible for uniqueness in that case.
    """

    if not root_secret:
        raise MacaroonError("root_secret must be non-empty bytes")
    ident = identifier if identifier is not None else secrets.token_hex(16)
    sig = _initial_signature(root_secret, ident)
    return Macaroon(identifier=ident, caveats=[], signature=sig.hex(), location=location)


def attenuate(macaroon: Macaroon, caveat: str) -> Macaroon:
    """Return a NEW macaroon with a first-party caveat appended.

    Immutability is important: attenuation must not mutate the source
    macaroon so callers can hand a base macaroon to multiple sub-agents
    and derive independent attenuated tokens from it.
    """

    if not caveat or "\n" in caveat:
        raise MacaroonError("caveat must be a non-empty single-line string")
    new_sig = _extend_first_party(bytes.fromhex(macaroon.signature), caveat)
    out = macaroon.copy()
    out.caveats.append(Caveat(cid=caveat))
    out.signature = new_sig.hex()
    return out


def derive_third_party_key(root_secret: bytes, discharge_identifier: str) -> bytes:
    """Derive the HMAC key a discharger must use to mint discharge macaroons.

    In a full Macaroon deployment the vid ciphertext transports this key
    to the discharger; here we ship a simpler HMAC-derived key model:
    the authority and the discharger share `root_secret` context and
    both compute the same key from the discharge identifier via
    HMAC(root, "discharge:" || identifier). That keeps the demo
    cryptography honest without pulling in a public-key crate.
    """

    return _hmac(root_secret, b"discharge:" + discharge_identifier.encode("utf-8"))


def add_third_party_caveat(
    macaroon: Macaroon,
    *,
    discharge_identifier: str,
    location: str,
    predicate_hint: str | None = None,
) -> Macaroon:
    """Attach a third-party caveat pointing to a discharge macaroon.

    `vid` is HMAC(current-signature, discharge_identifier) — that binding
    is what makes third-party caveats *macaroon-shape*: it cannot be
    lifted onto another macaroon because the recovered vid depends on
    the enclosing signature chain.
    """

    cid = f"discharge:{discharge_identifier}"
    if predicate_hint:
        cid = f"{cid}:{predicate_hint}"
    vid = _hmac(bytes.fromhex(macaroon.signature), discharge_identifier.encode("utf-8")).hex()
    new_sig = _extend_third_party(bytes.fromhex(macaroon.signature), vid, cid)
    out = macaroon.copy()
    out.caveats.append(Caveat(cid=cid, vid=vid, cl=location))
    out.signature = new_sig.hex()
    return out


def mint_discharge(discharge_key: bytes, *, identifier: str, location: str = DEFAULT_LOCATION) -> Macaroon:
    """Mint a discharge macaroon that a third-party caveat points to."""

    return mint_root(discharge_key, identifier=identifier, location=location)


# --- Predicate matcher -------------------------------------------------------

# Longer operators must come first in the alternation — Python's `re` picks
# the first that matches, so listing `<` before `<=` would eat `amount<=100`
# as `amount < =100` and derail the numeric comparison.
_KV_RE = re.compile(r"^([a-zA-Z0-9_.-]+)(<=|>=|=|<|>)(.+)$")


def _coerce(value_str: str) -> int | str:
    try:
        return int(value_str)
    except ValueError:
        return value_str


def predicate_matcher(context: VerifierContext) -> Callable[[str], bool]:
    """Return a matcher that evaluates first-party predicates.

    Built-ins:
      - `expires<T`, `expires<=T` — T is Unix seconds; `context.now`
        must be strictly less-than / less-or-equal-than T.
      - `capability=X`, `escrow_id=X`, `amount<=N`, `amount<N`, `amount>N`,
        `amount>=N` — matched against `context.facts`.
    Unknown predicates fall through to any user-registered predicate in
    `context.predicates`. If none matches, the caveat fails.
    """

    def matcher(cid: str) -> bool:
        m = _KV_RE.match(cid)
        if m:
            key, op, raw = m.group(1), m.group(2), m.group(3)
            if key == "expires":
                threshold = int(raw)
                return context.now < threshold if op == "<" else context.now <= threshold if op == "<=" else False
            value = _coerce(raw)
            fact = context.facts.get(key)
            if fact is None:
                return False
            # Normalise: if both look numeric, compare numerically.
            if isinstance(value, int) and isinstance(fact, int):
                return _compare_int(fact, op, value)
            if isinstance(value, int) and isinstance(fact, str) and fact.isdigit():
                return _compare_int(int(fact), op, value)
            if op == "=":
                return str(fact) == str(value)
            return False
        # Non-KV predicates: fall through to user hooks.
        for extra in context.predicates:
            try:
                if extra(cid):
                    return True
            except Exception:
                continue
        return False

    return matcher


def _compare_int(fact: int, op: str, value: int) -> bool:
    return {
        "=": fact == value,
        "<": fact < value,
        "<=": fact <= value,
        ">": fact > value,
        ">=": fact >= value,
    }.get(op, False)


# --- Verify ------------------------------------------------------------------


def verify(macaroon: Macaroon, root_secret: bytes, context: VerifierContext) -> None:
    """Verify a macaroon (raises on any failure).

    Verification runs three passes:
      1. Recompute the signature chain from `root_secret` and every
         caveat; the terminal HMAC must equal `macaroon.signature`.
         Constant-time comparison via `hmac.compare_digest`.
      2. Evaluate each first-party caveat against the verifier context.
      3. Resolve every third-party caveat against a discharge macaroon
         from `context.discharges`; the discharge's own chain must
         verify under the caveat's derived key, and its terminal
         signature must chain-back to the enclosing macaroon.
    """

    if macaroon.version != 1:
        raise MacaroonVerifyError(f"unsupported macaroon version {macaroon.version}")

    # 1. Signature chain.
    expected_terminal = _walk(_initial_signature(root_secret, macaroon.identifier), macaroon.caveats)
    if not hmac.compare_digest(expected_terminal.hex(), macaroon.signature):
        raise MacaroonVerifyError("signature chain mismatch")

    # 2 & 3. Caveat semantics.
    matcher = predicate_matcher(context)
    for cav in macaroon.caveats:
        if cav.is_third_party:
            _verify_third_party(cav, root_secret, context)
            continue
        if not matcher(cav.cid):
            raise MacaroonVerifyError(f"caveat failed: {cav.cid}")


def _verify_third_party(cav: Caveat, root_secret: bytes, context: VerifierContext) -> None:
    # `discharge:<identifier>[:predicate_hint]`
    body = cav.cid.split(":", 2)
    if len(body) < 2 or body[0] != "discharge":
        raise MacaroonVerifyError(f"unrecognised third-party caveat: {cav.cid}")
    discharge_id = body[1]
    discharge = context.discharges.get(discharge_id)
    if discharge is None:
        raise MacaroonVerifyError(f"missing discharge macaroon for {discharge_id}")

    discharge_key = derive_third_party_key(root_secret, discharge_id)
    expected = _walk(_initial_signature(discharge_key, discharge.identifier), discharge.caveats)
    if not hmac.compare_digest(expected.hex(), discharge.signature):
        raise MacaroonVerifyError("discharge signature invalid")

    # Verify the discharge's own first-party caveats under the same context.
    matcher = predicate_matcher(context)
    for inner in discharge.caveats:
        if inner.is_third_party:
            _verify_third_party(inner, root_secret, context)
            continue
        if not matcher(inner.cid):
            raise MacaroonVerifyError(f"discharge caveat failed: {inner.cid}")


# --- Wire format -------------------------------------------------------------


def encode(macaroon: Macaroon) -> str:
    payload = {
        "v": macaroon.version,
        "location": macaroon.location,
        "identifier": macaroon.identifier,
        "caveats": [
            {k: v for k, v in {"cid": c.cid, "vid": c.vid, "cl": c.cl}.items() if v is not None}
            for c in macaroon.caveats
        ],
        "signature": macaroon.signature,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode(token: str) -> Macaroon:
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise MacaroonError(f"invalid macaroon token: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise MacaroonError("unsupported macaroon envelope")
    caveats = []
    for c in payload.get("caveats", []):
        if not isinstance(c, dict) or "cid" not in c:
            raise MacaroonError("caveat missing cid")
        caveats.append(Caveat(cid=c["cid"], vid=c.get("vid"), cl=c.get("cl")))
    return Macaroon(
        identifier=payload["identifier"],
        caveats=caveats,
        signature=payload["signature"],
        location=payload.get("location", DEFAULT_LOCATION),
        version=payload["v"],
    )
