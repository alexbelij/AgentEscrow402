"""Prometheus / OpenMetrics 1.0.0 text endpoint for AgentEscrow402.

Task Q1-#4 (post-hackathon tech pass). Exposes existing operator-visible
signals (DB connectivity, uptime, chain identity, contract deployment
health) plus a small set of lifecycle counters in the format Prometheus
scrapers, Grafana Agent, VictoriaMetrics vmagent, and any OpenMetrics-
compliant collector natively understand.

Why hand-rolled instead of pulling `prometheus_client`:

* The library is not currently in requirements.txt and its collector /
  registry model is heavier than we need (a single scrape endpoint with
  ~10 series). Text output is a stable, spec-compliant contract:
  https://github.com/OpenObservability/OpenMetrics/blob/main/specification/OpenMetrics.md#text-format
* Zero new runtime dependency to audit for the hackathon submission.
* Full test coverage is trivial without needing to reset a global registry.

Backwards-compat: purely additive — new `/metrics` route, no changes to
existing endpoints. Response format follows content-type contract:
`application/openmetrics-text; version=1.0.0; charset=utf-8`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

_OPENMETRICS_CONTENT_TYPE = "application/openmetrics-text; version=1.0.0; charset=utf-8"


@dataclass
class _CounterStore:
    """Thread-safe integer counters. Increment-only per Prometheus semantics."""

    _values: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def inc(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._values[name] = self._values.get(name, 0) + amount

    def get(self, name: str) -> int:
        with self._lock:
            return self._values.get(name, 0)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._values)

    def reset(self) -> None:
        """Test-only. Reset all counters."""
        with self._lock:
            self._values.clear()


# Module-level singleton. Counters aggregate across the process lifetime,
# which is the Prometheus contract (a scrape resets nothing; monotonic).
COUNTERS = _CounterStore()


# Counter names — kept as constants so we don't fat-finger them at call sites.
COUNTER_ESCROW_CREATED = "ae402_escrows_created_total"
COUNTER_ESCROW_RELEASED = "ae402_escrows_released_total"
COUNTER_ESCROW_REFUNDED = "ae402_escrows_refunded_total"
COUNTER_ESCROW_DISPUTED = "ae402_escrows_disputed_total"
COUNTER_ESCROW_RESOLVED = "ae402_escrows_resolved_total"
COUNTER_RPC_FALLBACK = "ae402_rpc_fallback_total"
COUNTER_ARBITER_QUORUM_MET = "ae402_arbiter_quorum_met_total"
COUNTER_ARBITER_QUORUM_MISSING = "ae402_arbiter_quorum_missing_total"


# ---------------------------------------------------------------------------
# Metric families & rendering
# ---------------------------------------------------------------------------


@dataclass
class MetricFamily:
    """One metric family in OpenMetrics text output.

    A metric family is name + TYPE + HELP + one or more sample lines.
    """

    name: str
    kind: str  # "counter" | "gauge" | "info"
    help_text: str
    samples: list[tuple[str, float]] = field(default_factory=list)
    """samples: list of (label_str_or_empty, value). label_str format:
    `{key1="val1",key2="val2"}` including braces, or empty string for
    label-less samples."""

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} {self.kind}"]
        for label_str, value in self.samples:
            # OpenMetrics: counters carry `_total` suffix already in the
            # name; the sample line uses the FULL name including suffix.
            lines.append(f"{self.name}{label_str} {value}")
        return "\n".join(lines)


def _escape_label_value(value: str) -> str:
    """OpenMetrics label-value escaping: backslash, double-quote, newline."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt_labels(labels: dict[str, str] | None) -> str:
    if not labels:
        return ""
    parts = [f'{k}="{_escape_label_value(v)}"' for k, v in sorted(labels.items())]
    return "{" + ",".join(parts) + "}"


def _now_epoch_seconds() -> float:
    return time.time()


def build_metrics_text(
    *,
    started_at: float,
    db_connected: bool,
    chain_name: str,
    contract_hashes: dict[str, str],
    sandbox_mode: bool,
) -> str:
    """Render the full /metrics response body.

    Inputs are pushed in explicitly (no hidden globals) so tests can drive
    every branch and callers stay independent of module state.
    """
    now = _now_epoch_seconds()
    families: list[MetricFamily] = []

    # --- Process uptime gauge -------------------------------------------
    families.append(
        MetricFamily(
            name="ae402_uptime_seconds",
            kind="gauge",
            help_text="Seconds since the AgentEscrow402 server process started.",
            samples=[("", max(0.0, now - started_at))],
        )
    )

    # --- DB connectivity gauge (1 = connected, 0 = down) ----------------
    families.append(
        MetricFamily(
            name="ae402_db_connected",
            kind="gauge",
            help_text="1 if the primary database is reachable and responding, 0 otherwise.",
            samples=[("", 1.0 if db_connected else 0.0)],
        )
    )

    # --- Sandbox mode indicator (info-style) ----------------------------
    families.append(
        MetricFamily(
            name="ae402_sandbox_mode",
            kind="gauge",
            help_text="1 if the server is running in sandbox (mock chain) mode, 0 for live testnet.",
            samples=[("", 1.0 if sandbox_mode else 0.0)],
        )
    )

    # --- Chain / contract identity as info-labelled gauge value=1 -------
    # OpenMetrics doesn't have a first-class 'info' type in 0.0.4 scrape
    # scrapers universally support, so we emit a gauge=1 with labels.
    info_labels = {"chain": chain_name}
    for role, h in contract_hashes.items():
        if h:
            info_labels[f"contract_{role}"] = h
    families.append(
        MetricFamily(
            name="ae402_build_info",
            kind="gauge",
            help_text="Chain identity and deployed contract addresses (label-carrier gauge, value always 1).",
            samples=[(_fmt_labels(info_labels), 1.0)],
        )
    )

    # --- Deployed-contract count ----------------------------------------
    deployed_count = sum(1 for h in contract_hashes.values() if h)
    families.append(
        MetricFamily(
            name="ae402_deployed_contracts",
            kind="gauge",
            help_text="Number of core contracts with a non-empty deployment hash in config.",
            samples=[("", float(deployed_count))],
        )
    )

    # --- Counters -------------------------------------------------------
    counter_snapshot = COUNTERS.snapshot()

    def _counter_family(name: str, help_text: str) -> MetricFamily:
        return MetricFamily(
            name=name,
            kind="counter",
            help_text=help_text,
            samples=[("", float(counter_snapshot.get(name, 0)))],
        )

    families.extend(
        [
            _counter_family(
                COUNTER_ESCROW_CREATED,
                "Total number of escrows the server has created since process start.",
            ),
            _counter_family(
                COUNTER_ESCROW_RELEASED,
                "Total number of escrows released (funds sent to worker).",
            ),
            _counter_family(
                COUNTER_ESCROW_REFUNDED,
                "Total number of escrows refunded (funds returned to buyer).",
            ),
            _counter_family(
                COUNTER_ESCROW_DISPUTED,
                "Total number of escrows moved into the disputed state.",
            ),
            _counter_family(
                COUNTER_ESCROW_RESOLVED,
                "Total number of disputes resolved by arbiter quorum.",
            ),
            _counter_family(
                COUNTER_RPC_FALLBACK,
                "Total number of times the RPC client fell back to a secondary endpoint.",
            ),
            _counter_family(
                COUNTER_ARBITER_QUORUM_MET,
                "Total number of arbiter-quorum verifications that succeeded.",
            ),
            _counter_family(
                COUNTER_ARBITER_QUORUM_MISSING,
                "Total number of arbiter-quorum verifications that failed (insufficient signatures).",
            ),
        ]
    )

    body = "\n".join(f.render() for f in families) + "\n"
    # OpenMetrics 1.0 requires the exposition to end with # EOF.
    body += "# EOF\n"
    return body


def openmetrics_content_type() -> str:
    return _OPENMETRICS_CONTENT_TYPE
