"""Standardized domain exception hierarchy for AI Workload Orchestration Platform."""


class OrchestrationError(Exception):
    """Base exception for platform failures."""
    def __init__(self, message: str, error_code: str = "INTERNAL_ERROR", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}


class ConstraintViolationError(OrchestrationError):
    """Raised when no nodes satisfy hard constraints."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, error_code="CONSTRAINT_VIOLATION", details=details)


class DecisionEngineUnavailableError(OrchestrationError):
    """Raised when Decision Engine is unreachable or times out."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, error_code="DECISION_ENGINE_UNAVAILABLE", details=details)


class NodeUnavailableError(OrchestrationError):
    """Raised when candidate node execution rejects or fails."""
    def __init__(self, message: str, node_id: str, details: dict | None = None):
        d = details or {}
        d["node_id"] = node_id
        super().__init__(message, error_code="NODE_UNAVAILABLE", details=d)


class FallbackExhaustionError(OrchestrationError):
    """Raised when all candidates in the fallback chain fail."""
    def __init__(self, message: str, chain: list[str], details: dict | None = None):
        d = details or {}
        d["fallback_chain"] = chain
        super().__init__(message, error_code="FALLBACK_EXHAUSTED", details=d)


class StaleTelemetryError(OrchestrationError):
    """Raised when telemetry exceeds staleness threshold."""
    def __init__(self, message: str, node_id: str, age_ms: float):
        super().__init__(
            message,
            error_code="STALE_TELEMETRY",
            details={"node_id": node_id, "age_ms": age_ms},
        )


class IdempotencyConflictError(OrchestrationError):
    """Raised on concurrent execution with identical idempotency key."""
    def __init__(self, message: str, idempotency_key: str):
        super().__init__(
            message,
            error_code="IDEMPOTENCY_CONFLICT",
            details={"idempotency_key": idempotency_key},
        )
