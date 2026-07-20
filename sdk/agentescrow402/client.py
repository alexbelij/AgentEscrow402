from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from .models import (
    AgentIdentity,
    ArbitrationSubmitRequest,
    EscrowActionRequest,
    EscrowCreate,
    EscrowResponse,
    EscrowStatus,
    InsuranceDepositRequest,
    InsuranceQuote,
    StreamConfig,
    StreamStatusResponse,
    TokenType,
)


class AgentEscrowError(Exception):
    """Base exception for AgentEscrow402 SDK errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class APIError(AgentEscrowError):
    """Raised for general API errors (e.g., 5xx)."""

    pass


class BadRequestError(AgentEscrowError):
    """Raised for 400 Bad Request errors."""

    pass


class UnauthorizedError(AgentEscrowError):
    """Raised for 401 Unauthorized errors."""

    pass


class ForbiddenError(AgentEscrowError):
    """Raised for 403 Forbidden errors."""

    pass


class NotFoundError(AgentEscrowError):
    """Raised for 404 Not Found errors."""

    pass


class ConflictError(AgentEscrowError):
    """Raised for 409 Conflict errors."""

    pass


class AgentEscrow402Client:
    """
    Asynchronous Python SDK for interacting with the AgentEscrow402 API.

    Provides methods for managing AI agent escrows, streaming payments,
    insurance, and arbitration.
    """

    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        """
        Initializes the AgentEscrow402Client.

        Args:
            base_url (str): The base URL of the AgentEscrow402 API (e.g., "https://api.agentescrow402.com").
            api_key (str): The API key for x402 header authentication.
            timeout (int): Default timeout for HTTP requests in seconds.
        """
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        response_model: Optional[Any] = None,
    ) -> Any:
        """
        Internal helper for making API requests and handling responses.

        Args:
            method (str): HTTP method (e.g., "GET", "POST", "PUT").
            path (str): API endpoint path.
            json (Optional[Dict[str, Any]]): JSON payload for the request body.
            params (Optional[Dict[str, Any]]): Query parameters.
            response_model (Optional[Any]): Pydantic model to parse the response into.

        Returns:
            Any: Parsed response data, or raw JSON if no model is provided.

        Raises:
            AgentEscrowError: For various API errors.
        """
        headers = {"X-402-Auth": self.api_key, "Content-Type": "application/json"}
        try:
            response = await self._client.request(method, path, json=json, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            if response_model:
                return response_model.model_validate(data)
            return data
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            details = e.response.json() if e.response.text else {"message": "No response body"}
            error_message = details.get("message", f"API error: {e.response.status_code} {e.response.reason_phrase}")

            if status_code == 400:
                raise BadRequestError(error_message, status_code, details)
            elif status_code == 401:
                raise UnauthorizedError(error_message, status_code, details)
            elif status_code == 403:
                raise ForbiddenError(error_message, status_code, details)
            elif status_code == 404:
                raise NotFoundError(error_message, status_code, details)
            elif status_code == 409:
                raise ConflictError(error_message, status_code, details)
            else:
                raise APIError(error_message, status_code, details)
        except httpx.RequestError as e:
            raise AgentEscrowError(f"Network or request error: {e}")
        except Exception as e:
            raise AgentEscrowError(f"An unexpected error occurred: {e}")

    async def create_escrow(self, escrow_data: EscrowCreate) -> EscrowResponse:
        """
        Creates a new escrow for an AI agent service.

        Args:
            escrow_data (EscrowCreate): Details for the new escrow.

        Returns:
            EscrowResponse: The created escrow's details.
        """
        return await self._request(
            "POST", "/escrow", json=escrow_data.model_dump(mode="json"), response_model=EscrowResponse
        )

    async def fund_escrow(self, escrow_id: UUID, amount: float, token_type: TokenType) -> EscrowResponse:
        """
        Funds an existing escrow.

        Args:
            escrow_id (UUID): The ID of the escrow to fund.
            amount (float): The amount to deposit.
            token_type (TokenType): The type of token being deposited.

        Returns:
            EscrowResponse: The updated escrow details.
        """
        action_data = EscrowActionRequest(action="fund", amount=amount, token_type=token_type)
        return await self._request(
            "POST",
            f"/escrow/{escrow_id}/action",
            json=action_data.model_dump(mode="json"),
            response_model=EscrowResponse,
        )

    async def release(self, escrow_id: UUID, amount: Optional[float] = None) -> EscrowResponse:
        """
        Releases funds from an escrow to the agent.

        Args:
            escrow_id (UUID): The ID of the escrow.
            amount (Optional[float]): The specific amount to release. If None, all remaining funds are released.

        Returns:
            EscrowResponse: The updated escrow details.
        """
        action_data = EscrowActionRequest(action="release", amount=amount)
        return await self._request(
            "POST",
            f"/escrow/{escrow_id}/action",
            json=action_data.model_dump(mode="json"),
            response_model=EscrowResponse,
        )

    async def dispute(self, escrow_id: UUID, reason: str) -> EscrowResponse:
        """
        Initiates a dispute for an escrow.

        Args:
            escrow_id (UUID): The ID of the escrow.
            reason (str): The reason for the dispute.

        Returns:
            EscrowResponse: The updated escrow details, now in DISPUTED status.
        """
        action_data = EscrowActionRequest(action="dispute", reason=reason)
        return await self._request(
            "POST",
            f"/escrow/{escrow_id}/action",
            json=action_data.model_dump(mode="json"),
            response_model=EscrowResponse,
        )

    async def refund(self, escrow_id: UUID, amount: Optional[float] = None) -> EscrowResponse:
        """
        Refunds funds from an escrow to the client.

        Args:
            escrow_id (UUID): The ID of the escrow.
            amount (Optional[float]): The specific amount to refund. If None, all remaining funds are refunded.

        Returns:
            EscrowResponse: The updated escrow details.
        """
        action_data = EscrowActionRequest(action="refund", amount=amount)
        return await self._request(
            "POST",
            f"/escrow/{escrow_id}/action",
            json=action_data.model_dump(mode="json"),
            response_model=EscrowResponse,
        )

    async def get_escrow(self, escrow_id: UUID) -> EscrowResponse:
        """
        Retrieves details for a specific escrow.

        Args:
            escrow_id (UUID): The ID of the escrow.

        Returns:
            EscrowResponse: The escrow's details.
        """
        return await self._request("GET", f"/escrow/{escrow_id}", response_model=EscrowResponse)

    async def list_escrows(
        self,
        client_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        status: Optional[EscrowStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[EscrowResponse]:
        """
        Lists escrows based on provided filters.

        Args:
            client_id (Optional[str]): Filter by client ID.
            agent_id (Optional[str]): Filter by agent ID.
            status (Optional[EscrowStatus]): Filter by escrow status.
            limit (int): Maximum number of escrows to return.
            offset (int): Number of escrows to skip.

        Returns:
            List[EscrowResponse]: A list of matching escrows.
        """
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if client_id:
            params["client_id"] = client_id
        if agent_id:
            params["agent_id"] = agent_id
        if status:
            params["status"] = status.value
        return await self._request("GET", "/escrow", params=params, response_model=List[EscrowResponse])

    async def create_streaming(self, escrow_id: UUID, stream_config: StreamConfig) -> EscrowResponse:
        """
        Configures streaming payments for an escrow.

        Args:
            escrow_id (UUID): The ID of the escrow.
            stream_config (StreamConfig): Configuration for streaming payments.

        Returns:
            EscrowResponse: The updated escrow details with streaming configuration.
        """
        return await self._request(
            "POST",
            f"/escrow/{escrow_id}/stream",
            json=stream_config.model_dump(mode="json"),
            response_model=EscrowResponse,
        )

    async def get_stream_status(self, escrow_id: UUID) -> StreamStatusResponse:
        """
        Retrieves the current status of streaming payments for an escrow.

        Args:
            escrow_id (UUID): The ID of the escrow.

        Returns:
            StreamStatusResponse: The current streaming payment status.
        """
        return await self._request("GET", f"/escrow/{escrow_id}/stream/status", response_model=StreamStatusResponse)

    async def insurance_quote(self, escrow_id: UUID) -> InsuranceQuote:
        """
        Gets an insurance quote for a specific escrow.

        Args:
            escrow_id (UUID): The ID of the escrow to get a quote for.

        Returns:
            InsuranceQuote: Details of the insurance quote.
        """
        return await self._request("GET", f"/insurance/quote/{escrow_id}", response_model=InsuranceQuote)

    async def insurance_deposit(self, deposit_request: InsuranceDepositRequest) -> Dict[str, Any]:
        """
        Deposits premium for an insurance policy.

        Args:
            deposit_request (InsuranceDepositRequest): Details for the insurance premium deposit.

        Returns:
            Dict[str, Any]: Confirmation of the deposit.
        """
        return await self._request("POST", "/insurance/deposit", json=deposit_request.model_dump(mode="json"))

    async def submit_arbitration(
        self, escrow_id: UUID, arbitration_request: ArbitrationSubmitRequest
    ) -> Dict[str, Any]:
        """
        Submits an arbitration claim for a disputed escrow.

        Args:
            escrow_id (UUID): The ID of the disputed escrow.
            arbitration_request (ArbitrationSubmitRequest): Details of the arbitration claim.

        Returns:
            Dict[str, Any]: Confirmation of the arbitration submission.
        """
        return await self._request(
            "POST", f"/arbitration/{escrow_id}/submit", json=arbitration_request.model_dump(mode="json")
        )

    async def get_agent_identity(self, agent_id: str) -> AgentIdentity:
        """
        Retrieves the public identity details of an AI agent.

        Args:
            agent_id (str): The unique identifier of the agent.

        Returns:
            AgentIdentity: The agent's identity details.
        """
        return await self._request("GET", f"/identity/agent/{agent_id}", response_model=AgentIdentity)

    async def close(self):
        """Closes the underlying HTTP client session."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
