"""Strict / fail-loud mode helpers.

Under AE402_STRICT=1 (see :attr:`server.config.Config.strict_mode`), any
code path that would ordinarily fall back to sandbox / demo / mock behaviour
must instead raise :class:`StrictModeError`.

Why it exists
=============
The default AE402 backend tolerates a lot of environmental slop -- an empty
CASPER_NODE_URL degrades RPC calls to no-ops, a missing private key
degrades signed writes to unsigned mocks, RPC 5xx errors are logged and the
handler returns a cached / synthesised value. That behaviour is deliberate
for local development / demos: the frontend does not crash if the operator
happens to forget to wire testnet up.

For a hackathon judge running the live deployment, that same behaviour is
disqualifying: they get a green 200 response with a fabricated hash and no
signal that the write never actually reached testnet. AE402_STRICT=1
inverts the choice -- every documented silent-fallback branch becomes a
hard error, and the app refuses to start if the three preconditions
(casper_node_url set, contract_hash set, sandbox=false) are not
all satisfied.

Contract
--------
* :func:`ensure_strict` at startup / import time: raises
  :class:`StrictModeError` if strict mode is enabled and preconditions are
  missing. Callers use this to fail-close instead of tolerating a bad
  config.

* :func:`guard` inside a handler: raises :class:`StrictModeError` from a
  code path that is about to fall back. The ``path`` argument is a short
  identifier the operator can grep for (e.g.
  "casper_client.put_deploy"); ``reason`` is the human-readable reason
  the fallback was about to trigger.

* :class:`StrictModeError` -- raised on any strict-mode violation.
  FastAPI handlers map it to a 503 with a structured error body so the UI
  and CLI callers can distinguish it from a generic 500. See the
  ``strict_mode_exception_handler`` registered in ``server/app.py``.

The module is intentionally free of runtime dependencies on the rest of the
package so importing it from any layer (config, chain client, DB, routes)
is safe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config


class StrictModeError(RuntimeError):
    """Raised when strict-mode fail-loud is triggered.

    Attributes:
        path: Short identifier of the code path that would have fallen back.
        reason: Human-readable explanation of why the fallback was going
            to happen (e.g. "CASPER_NODE_URL is empty").

    The FastAPI handler in server/app.py renders this as a 503 with a
    JSON body {"error": "strict_mode_violation", "path": path,
    "reason": reason}.
    """

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"[strict-mode] {path}: {reason}")


def ensure_strict(cfg: "Config") -> None:
    """Validate strict-mode preconditions at startup.

    Raises :class:`StrictModeError` if ``cfg.strict_mode`` is enabled and
    any of the three well-known preconditions are missing. See
    :meth:`server.config.Config.require_strict_preconditions`.

    Called from application startup so an operator who sets
    AE402_STRICT=1 but forgets CASPER_NODE_URL gets an immediate
    crash rather than a silently-broken app.
    """
    if not cfg.strict_mode:
        return
    violations = cfg.require_strict_preconditions()
    if violations:
        raise StrictModeError(
            path="config.startup",
            reason="AE402_STRICT=1 but preconditions missing: " + "; ".join(violations),
        )


def guard(cfg: "Config", path: str, reason: str) -> None:
    """Fail-loud guard for a request-time silent-fallback branch.

    Args:
        cfg: Current :class:`Config`.
        path: Short identifier of the code path (e.g.
            "casper_client.put_deploy.no_key").
        reason: Human-readable explanation of the missing precondition
            (e.g. "casper_private_key_path is empty").

    If ``cfg.strict_mode`` is enabled, raises :class:`StrictModeError`.
    Otherwise this is a no-op -- the caller proceeds with its normal
    fallback behaviour.

    Use this at the top of every branch that would ordinarily degrade to
    sandbox / demo / mock behaviour::

        if not self.private_key_path:
            strict.guard(cfg, "casper_client.put_deploy.no_key",
                         "casper_private_key_path is empty")
            return _synthesise_deploy_hash(...)
    """
    if cfg.strict_mode:
        raise StrictModeError(path=path, reason=reason)
