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


class InvalidSchemaError(RiskFlowError):
    """Raised when a target schema config file is missing, malformed, or invalid."""


class InvalidCorrectionError(RiskFlowError):
    """Raised when a correction references a target field not in the active schema."""


class SchemaAlreadyExistsError(RiskFlowError):
    """Raised when creating a schema with a name that already exists."""


class ProtectedSchemaError(RiskFlowError):
    """Raised when attempting to delete a built-in (bootstrap) schema."""
