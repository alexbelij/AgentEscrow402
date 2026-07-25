"""FastAPI wiring for the Agent-vs-Agent simulation framework (T3.5).

Exposes `POST /simulate/agent-vs-agent` — runs a deterministic batch of
simulated escrows through the real `EscrowFSM` + heuristic arbitrator and
returns the aggregate report. No on-chain interaction, no persistence,
no side effects on the live escrow store: this is purely a testing tool a
client or judge can call to reproduce a protocol stress scenario byte-for-
byte given the same request body.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .agent_sim import STRATEGY_REGISTRY, SimulationConfig, run_simulation

router = APIRouter(prefix="/simulate", tags=["agent-sim"])


class AgentSimRequest(BaseModel):
    num_escrows: int = Field(default=100, ge=1, le=5000)
    sender_strategy: str = Field(default="honest")
    receiver_strategy: str = Field(default="honest")
    seed: int = Field(default=0)
    max_rounds: int = Field(default=10, ge=1, le=100)
    base_amount: int = Field(default=1_000_000_000, gt=0)


class EscrowOutcomeResponse(BaseModel):
    escrow_id: str
    final_status: str
    rounds_taken: int
    disputed: bool
    arbitration_recommendation: str | None
    arbitration_confidence: float | None


class AgentSimResponse(BaseModel):
    outcome_counts: dict[str, int]
    dispute_rate: float
    avg_rounds: float
    report_hash: str
    summary: str
    outcomes: list[EscrowOutcomeResponse]


@router.get("/strategies")
def list_strategies() -> dict[str, list[str]]:
    """Available strategy names for `sender_strategy` / `receiver_strategy`."""
    return {"strategies": sorted(STRATEGY_REGISTRY.keys())}


@router.post("/agent-vs-agent", response_model=AgentSimResponse)
def simulate_agent_vs_agent(req: AgentSimRequest) -> AgentSimResponse:
    try:
        config = SimulationConfig(
            num_escrows=req.num_escrows,
            sender_strategy=req.sender_strategy,
            receiver_strategy=req.receiver_strategy,
            seed=req.seed,
            max_rounds=req.max_rounds,
            base_amount=req.base_amount,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    report = run_simulation(config)
    return AgentSimResponse(
        outcome_counts=report.outcome_counts,
        dispute_rate=report.dispute_rate,
        avg_rounds=report.avg_rounds,
        report_hash=report.report_hash,
        summary=report.summary(),
        outcomes=[
            EscrowOutcomeResponse(
                escrow_id=o.escrow_id,
                final_status=o.final_status.value,
                rounds_taken=o.rounds_taken,
                disputed=o.disputed,
                arbitration_recommendation=o.arbitration_recommendation,
                arbitration_confidence=o.arbitration_confidence,
            )
            for o in report.outcomes
        ],
    )


__all__ = ["router"]
