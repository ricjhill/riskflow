"""Domain-specific errors for reinsurance data mapping."""


class RiskFlowError(Exception):
    """Base class for all domain errors."""


class MappingConfidenceLowError(RiskFlowError):
    """Raised when SLM mapping confidence is below threshold."""


class InvalidCedentDataError(RiskFlowError):
    """Raised when source spreadsheet data is unparseable."""


class SchemaValidationError(RiskFlowError):
    """Raised when a row fails RiskRecord validation."""


class SLMUnavailableError(RiskFlowError):
    """Raised when the Groq API is unreachable or returns invalid data."""
