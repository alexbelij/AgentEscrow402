"""
Snapshot the on-chain state of every escrow ever created (read-only), so any
future contract change to `escrow`/`escrow-manager` has a verifiable
before/after diff. Uses the same CasperClient.get_escrow() the backend API
uses, not a reimplementation.

Run from the repo root:
  ESCROW_CONTRACT_HASH=<live escrow contract_hash, see docs/STATUS_AND_ROADMAP.md> \
    uv run python scripts/snapshot_escrow_state.py

Output: docs/evidence/escrow_state_snapshot_<label>.json (label from
SNAPSHOT_LABEL env var, defaults to "latest").
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server.config import Config  # noqa: E402
from server.casper_client import CasperClient  # noqa: E402


def collect_service_hashes(repo_root: str) -> list[str]:
    ids: set[str] = set()
    log_path = os.path.join(repo_root, "docs", "evidence", "bulk_escrow_tx_log.jsonl")
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            h = d.get("service_hash")
            if h:
                ids.add(h)
    return sorted(ids)


async def main() -> None:
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    cfg = Config.from_env()
    if not cfg.contract_hash:
        print("ESCROW_CONTRACT_HASH not set in env", file=sys.stderr)
        sys.exit(1)
    client = CasperClient(cfg)

    ids = collect_service_hashes(repo_root)
    print(f"Querying {len(ids)} escrow records from contract {cfg.contract_hash} ...", file=sys.stderr)

    results = []
    sem = asyncio.Semaphore(8)

    async def fetch(service_hash: str) -> None:
        async with sem:
            try:
                rec = await client.get_escrow(service_hash)
            except Exception as exc:  # noqa: BLE001
                results.append({"service_hash": service_hash, "error": str(exc)})
                return
            if rec is None:
                results.append({"service_hash": service_hash, "found": False})
            else:
                results.append({
                    "service_hash": service_hash,
                    "found": True,
                    "sender": rec.sender,
                    "receiver": rec.receiver,
                    "amount": rec.amount,
                    "status": rec.status.value,
                    "created_at": rec.created_at,
                    "ttl": rec.ttl,
                })

    await asyncio.gather(*(fetch(h) for h in ids))

    label = os.environ.get("SNAPSHOT_LABEL", "latest")
    out_path = os.path.join(repo_root, "docs", "evidence", f"escrow_state_snapshot_{label}.json")
    with open(out_path, "w") as f:
        json.dump({
            "contract_hash": cfg.contract_hash,
            "total_ids_queried": len(ids),
            "found": sum(1 for r in results if r.get("found")),
            "not_found": sum(1 for r in results if r.get("found") is False),
            "errors": sum(1 for r in results if "error" in r),
            "records": results,
        }, f, indent=2)
    print(f"Wrote snapshot to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
