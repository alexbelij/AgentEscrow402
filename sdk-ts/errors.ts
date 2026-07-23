/** Error hierarchy mirroring `sdk/agentescrow402/client.py`. */

export class AgentEscrowError extends Error {
  status_code?: number;
  details?: unknown;

  constructor(message: string, status_code?: number, details?: unknown) {
    super(message);
    this.name = "AgentEscrowError";
    this.status_code = status_code;
    this.details = details;
  }
}

export class APIError extends AgentEscrowError {}
export class BadRequestError extends AgentEscrowError {}
export class UnauthorizedError extends AgentEscrowError {}
export class ForbiddenError extends AgentEscrowError {}
export class NotFoundError extends AgentEscrowError {}
export class ConflictError extends AgentEscrowError {}

/** Same status_code -> error class mapping as the Python SDK's `_request`. */
export function errorForStatus(status: number, message: string, details?: unknown): AgentEscrowError {
  switch (status) {
    case 400:
      return new BadRequestError(message, status, details);
    case 401:
      return new UnauthorizedError(message, status, details);
    case 403:
      return new ForbiddenError(message, status, details);
    case 404:
      return new NotFoundError(message, status, details);
    case 409:
      return new ConflictError(message, status, details);
    default:
      return new APIError(message, status, details);
  }
}
