"""Tests for domain error hierarchy."""

from src.domain.model.errors import (
    InvalidCedentDataError,
    MappingConfidenceLowError,
    RiskFlowError,
    SchemaValidationError,
    SLMUnavailableError,
)


class TestErrorHierarchy:
    def test_all_errors_inherit_from_riskflow_error(self) -> None:
        assert issubclass(MappingConfidenceLowError, RiskFlowError)
        assert issubclass(InvalidCedentDataError, RiskFlowError)
        assert issubclass(SchemaValidationError, RiskFlowError)
        assert issubclass(SLMUnavailableError, RiskFlowError)

    def test_riskflow_error_inherits_from_exception(self) -> None:
        assert issubclass(RiskFlowError, Exception)

    def test_errors_carry_messages(self) -> None:
        err = MappingConfidenceLowError("confidence 0.3 below threshold 0.6")
        assert "0.3" in str(err)
        assert "0.6" in str(err)

    def test_errors_are_catchable_by_base(self) -> None:
        try:
            raise SLMUnavailableError("Groq API timeout")
        except RiskFlowError as e:
            assert "timeout" in str(e)


class TestSchemasCrudErrors:
    def test_schema_already_exists_inherits(self) -> None:
        from src.domain.model.errors import SchemaAlreadyExistsError

        assert issubclass(SchemaAlreadyExistsError, RiskFlowError)

    def test_schema_already_exists_carries_message(self) -> None:
        from src.domain.model.errors import SchemaAlreadyExistsError

        err = SchemaAlreadyExistsError("Schema 'marine_cargo' already exists")
        assert "marine_cargo" in str(err)

    def test_protected_schema_inherits(self) -> None:
        from src.domain.model.errors import ProtectedSchemaError

        assert issubclass(ProtectedSchemaError, RiskFlowError)

    def test_protected_schema_carries_message(self) -> None:
        from src.domain.model.errors import ProtectedSchemaError

        err = ProtectedSchemaError("Cannot delete built-in schema 'standard_reinsurance'")
        assert "standard_reinsurance" in str(err)
