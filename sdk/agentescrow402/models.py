from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import UUID4, BaseModel, Field


class TokenType(str, Enum):
    """Supported token types for escrow and payments."""

    CSPR = "CSPR"
    USDC = "USDC"
    # Add other supported tokens as needed


class EscrowStatus(str, Enum):
    """Current status of an escrow."""

    CREATED = "CREATED"
    FUNDED = "FUNDED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class AgentIdentity(BaseModel):
    """Represents the public identity of an AI agent."""

    agent_id: str = Field(..., description="Unique identifier for the AI agent.")
    public_key: str = Field(..., description="Casper public key of the agent.")
    name: str = Field(..., description="Human-readable name of the agent.")
    description: Optional[str] = Field(None, description="A brief description of the agent's capabilities.")
    capabilities: List[str] = Field(
        default_factory=list, description="List of capabilities/skills the agent possesses."
    )
    reputation_score: Optional[float] = Field(
        None, ge=0, le=100, description="Reputation score based on past performance."
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="Timestamp when the agent identity was registered."
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow, description="Timestamp of the last update to the agent identity."
    )


class StreamConfig(BaseModel):
    """Configuration for streaming payments within an escrow."""

    interval_seconds: int = Field(..., gt=0, description="Interval in seconds between payment disbursements.")
    total_periods: int = Field(
        ..., gt=0, description="Total number of periods over which the payment will be streamed."
    )
    start_time: Optional[datetime] = Field(
        None, description="Optional start time for streaming. Defaults to immediate if not provided."
    )


class EscrowCreate(BaseModel):
    """Request model for creating a new escrow."""

    agent_id: str = Field(..., description="The ID of the AI agent involved.")
    client_id: str = Field(..., description="The ID of the client initiating the escrow.")
    amount: float = Field(..., gt=0, description="Total amount to be held in escrow.")
    token_type: TokenType = Field(..., description="The type of token for the escrow (e.g., CSPR, USDC).")
    description: str = Field(..., min_length=10, description="A detailed description of the service or task.")
    deadline: Optional[datetime] = Field(None, description="Optional deadline for the escrow service completion.")
    streaming_config: Optional[StreamConfig] = Field(None, description="Optional configuration for streaming payments.")


class EscrowResponse(BaseModel):
    """Response model for an escrow's details."""

    id: UUID4 = Field(..., description="Unique identifier for the escrow.")
    agent_id: str = Field(..., description="The ID of the AI agent involved.")
    client_id: str = Field(..., description="The ID of the client initiating the escrow.")
    amount: float = Field(..., description="Total amount initially held in escrow.")
    current_balance: float = Field(..., description="Current balance remaining in the escrow.")
    token_type: TokenType = Field(..., description="The type of token for the escrow.")
    status: EscrowStatus = Field(..., description="Current status of the escrow.")
    description: str = Field(..., description="A detailed description of the service or task.")
    created_at: datetime = Field(..., description="Timestamp when the escrow was created.")
    updated_at: datetime = Field(..., description="Timestamp of the last update to the escrow.")
    deadline: Optional[datetime] = Field(None, description="Optional deadline for the escrow service completion.")
    streaming_config: Optional[StreamConfig] = Field(
        None, description="Configuration for streaming payments, if applicable."
    )
    dispute_details: Optional[Dict[str, Any]] = Field(None, description="Details if the escrow is in a disputed state.")
    insurance_policy_id: Optional[UUID4] = Field(None, description="ID of the associated insurance policy, if any.")


class EscrowActionRequest(BaseModel):
    """Request model for performing actions on an escrow (fund, release, dispute, refund)."""

    action: str = Field(..., description="The action to perform (e.g., 'fund', 'release', 'dispute', 'refund').")
    amount: Optional[float] = Field(
        None, gt=0, description="Amount for 'fund', 'release', 'refund' actions. Optional for full release/refund."
    )
    token_type: Optional[TokenType] = Field(None, description="Token type for 'fund' action.")
    reason: Optional[str] = Field(None, description="Reason for 'dispute' action.")


class StreamStatusResponse(BaseModel):
    """Response model for the current status of a streaming payment."""

    escrow_id: UUID4 = Field(..., description="The ID of the escrow.")
    total_amount_streamed: float = Field(..., description="Total amount disbursed so far via streaming.")
    remaining_amount_to_stream: float = Field(..., description="Amount remaining to be streamed.")
    next_payment_due: Optional[datetime] = Field(None, description="Timestamp of the next scheduled payment.")
    payments_made: int = Field(..., description="Number of streaming payments already made.")
    total_payments: int = Field(..., description="Total number of payments configured for the stream.")
    progress_percent: float = Field(..., ge=0, le=100, description="Percentage of streaming completed.")
    is_active: bool = Field(..., description="True if streaming is currently active.")


class InsuranceQuote(BaseModel):
    """Details of an insurance quote for an escrow."""

    escrow_id: UUID4 = Field(..., description="The ID of the escrow for which the quote is generated.")
    premium_amount: float = Field(..., gt=0, description="The cost of the insurance premium.")
    coverage_amount: float = Field(..., gt=0, description="The maximum amount covered by the insurance.")
    currency: TokenType = Field(..., description="The currency of the premium and coverage.")
    valid_until: datetime = Field(..., description="Timestamp until which this quote is valid.")
    terms_url: str = Field(..., description="URL to the full terms and conditions of the insurance policy.")


class InsuranceDepositRequest(BaseModel):
    """Request model for depositing an insurance premium."""

    escrow_id: UUID4 = Field(..., description="The ID of the escrow to insure.")
    premium_amount: float = Field(..., gt=0, description="The premium amount to deposit.")
    currency: TokenType = Field(..., description="The currency of the premium.")
    quote_id: Optional[UUID4] = Field(None, description="Optional ID of the quote this deposit is for.")


class ArbitrationSubmitRequest(BaseModel):
    """Request model for submitting an arbitration claim."""

    claimant_id: str = Field(..., description="The ID of the party submitting the claim (client or agent).")
    claim_details: str = Field(..., min_length=50, description="Detailed description of the arbitration claim.")
    evidence_urls: List[str] = Field(default_factory=list, description="List of URLs pointing to supporting evidence.")
    requested_resolution: str = Field(..., min_length=20, description="The desired resolution from the arbitration.")
