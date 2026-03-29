"""Tests for the marine_cargo schema — validates it loads, parses, and works end-to-end.

This is the second schema in the system (alongside standard_reinsurance).
It proves the configurable schema feature works with a real non-default schema.
"""

import datetime

import pytest
from pydantic import ValidationError

from src.adapters.parsers.schema_loader import YamlSchemaLoader
from src.domain.model.record_factory import build_record_model


SCHEMA_PATH = "schemas/marine_cargo.yaml"


class TestMarineCargoSchemaLoads:
    """The YAML file parses into a valid TargetSchema."""

    def test_loads_without_error(self) -> None:
        loader = YamlSchemaLoader()
        schema = loader.load(SCHEMA_PATH)
        assert schema.name == "marine_cargo"

    def test_has_expected_fields(self) -> None:
        loader = YamlSchemaLoader()
        schema = loader.load(SCHEMA_PATH)
        assert schema.field_names == {
            "Vessel_Name",
            "Voyage_Date",
            "Arrival_Date",
            "Cargo_Value",
            "Premium",
            "Currency",
            "Port_Of_Loading",
            "Port_Of_Discharge",
        }

    def test_port_of_discharge_is_optional(self) -> None:
        loader = YamlSchemaLoader()
        schema = loader.load(SCHEMA_PATH)
        assert schema.fields["Port_Of_Discharge"].required is False
        assert schema.fields["Vessel_Name"].required is True

    def test_has_date_ordering_rule(self) -> None:
        loader = YamlSchemaLoader()
        schema = loader.load(SCHEMA_PATH)
        assert len(schema.cross_field_rules) == 1
        rule = schema.cross_field_rules[0]
        assert rule.earlier == "Voyage_Date"
        assert rule.later == "Arrival_Date"

    def test_has_slm_hints(self) -> None:
        loader = YamlSchemaLoader()
        schema = loader.load(SCHEMA_PATH)
        aliases = {h.source_alias for h in schema.slm_hints}
        assert "Ship" in aliases
        assert "Vessel" in aliases
        assert "ETA" in aliases
        assert "Loading Port" in aliases

    def test_currency_allows_sgd_and_hkd(self) -> None:
        loader = YamlSchemaLoader()
        schema = loader.load(SCHEMA_PATH)
        allowed = schema.fields["Currency"].allowed_values
        assert allowed is not None
        assert "SGD" in allowed
        assert "HKD" in allowed

    def test_fingerprint_differs_from_default(self) -> None:
        from src.domain.model.target_schema import DEFAULT_TARGET_SCHEMA

        loader = YamlSchemaLoader()
        marine = loader.load(SCHEMA_PATH)
        assert marine.fingerprint != DEFAULT_TARGET_SCHEMA.fingerprint


class TestMarineCargoValidation:
    """The dynamic model from the marine cargo schema validates rows correctly."""

    @pytest.fixture
    def model(self):
        loader = YamlSchemaLoader()
        schema = loader.load(SCHEMA_PATH)
        return build_record_model(schema)

    def test_valid_row_passes(self, model) -> None:
        row = {
            "Vessel_Name": "MV Atlantic Star",
            "Voyage_Date": datetime.date(2024, 3, 15),
            "Arrival_Date": datetime.date(2024, 4, 2),
            "Cargo_Value": 8500000.0,
            "Premium": 212500.0,
            "Currency": "USD",
            "Port_Of_Loading": "Singapore",
            "Port_Of_Discharge": "Rotterdam",
        }
        record = model.model_validate(row)
        assert record.Vessel_Name == "MV Atlantic Star"
        assert record.Currency == "USD"

    def test_optional_port_of_discharge(self, model) -> None:
        """Port_Of_Discharge is optional — None is valid."""
        row = {
            "Vessel_Name": "MV Test",
            "Voyage_Date": datetime.date(2024, 1, 1),
            "Arrival_Date": datetime.date(2024, 1, 15),
            "Cargo_Value": 1000000.0,
            "Premium": 25000.0,
            "Currency": "GBP",
            "Port_Of_Loading": "London",
        }
        record = model.model_validate(row)
        assert record.Port_Of_Discharge is None

    def test_rejects_arrival_before_voyage(self, model) -> None:
        row = {
            "Vessel_Name": "MV Test",
            "Voyage_Date": datetime.date(2024, 6, 1),
            "Arrival_Date": datetime.date(2024, 5, 1),
            "Cargo_Value": 1000000.0,
            "Premium": 25000.0,
            "Currency": "EUR",
            "Port_Of_Loading": "Hamburg",
        }
        with pytest.raises(ValidationError, match="must not be before"):
            model.model_validate(row)

    def test_rejects_negative_cargo_value(self, model) -> None:
        row = {
            "Vessel_Name": "MV Test",
            "Voyage_Date": datetime.date(2024, 1, 1),
            "Arrival_Date": datetime.date(2024, 1, 15),
            "Cargo_Value": -100.0,
            "Premium": 25000.0,
            "Currency": "JPY",
            "Port_Of_Loading": "Tokyo",
        }
        with pytest.raises(ValidationError, match="non-negative"):
            model.model_validate(row)

    def test_rejects_empty_vessel_name(self, model) -> None:
        row = {
            "Vessel_Name": "",
            "Voyage_Date": datetime.date(2024, 1, 1),
            "Arrival_Date": datetime.date(2024, 1, 15),
            "Cargo_Value": 1000000.0,
            "Premium": 25000.0,
            "Currency": "USD",
            "Port_Of_Loading": "Singapore",
        }
        with pytest.raises(ValidationError, match="not be empty"):
            model.model_validate(row)

    def test_rejects_invalid_currency(self, model) -> None:
        row = {
            "Vessel_Name": "MV Test",
            "Voyage_Date": datetime.date(2024, 1, 1),
            "Arrival_Date": datetime.date(2024, 1, 15),
            "Cargo_Value": 1000000.0,
            "Premium": 25000.0,
            "Currency": "AUD",
            "Port_Of_Loading": "Sydney",
        }
        with pytest.raises(ValidationError, match="must be one of"):
            model.model_validate(row)

    def test_sgd_currency_accepted(self, model) -> None:
        row = {
            "Vessel_Name": "MV Southern Cross",
            "Voyage_Date": datetime.date(2024, 10, 1),
            "Arrival_Date": datetime.date(2024, 10, 18),
            "Cargo_Value": 6750000.0,
            "Premium": 168750.0,
            "Currency": "SGD",
            "Port_Of_Loading": "Sydney",
        }
        record = model.model_validate(row)
        assert record.Currency == "SGD"
