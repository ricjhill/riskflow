"""Tests for configurable TargetSchema domain model.

The TargetSchema defines the structure that source spreadsheets are mapped TO.
It is a self-validating configuration: invalid schemas fail at parse time,
not at runtime when processing a file.
"""

import pytest

from src.domain.model.target_schema import (
    DEFAULT_TARGET_SCHEMA,
    DateOrderingRule,
    FieldDefinition,
    FieldType,
    SLMHint,
    TargetSchema,
)


class TestTargetSchemaCreation:
    """Loop 1: Basic schema construction and properties."""

    def test_creates_schema_with_fields(self) -> None:
        schema = TargetSchema(
            name="test",
            fields={
                "Policy_ID": FieldDefinition(type=FieldType.STRING),
                "Amount": FieldDefinition(type=FieldType.FLOAT),
            },
        )
        assert schema.name == "test"
        assert len(schema.fields) == 2

    def test_field_names_property(self) -> None:
        schema = TargetSchema(
            name="test",
            fields={
                "Policy_ID": FieldDefinition(type=FieldType.STRING),
                "Amount": FieldDefinition(type=FieldType.FLOAT),
                "Currency": FieldDefinition(type=FieldType.CURRENCY, allowed_values=["USD"]),
            },
        )
        assert schema.field_names == {"Policy_ID", "Amount", "Currency"}

    def test_required_field_names_property(self) -> None:
        schema = TargetSchema(
            name="test",
            fields={
                "Policy_ID": FieldDefinition(type=FieldType.STRING, required=True),
                "Notes": FieldDefinition(type=FieldType.STRING, required=False),
                "Amount": FieldDefinition(type=FieldType.FLOAT, required=True),
            },
        )
        assert schema.required_field_names == {"Policy_ID", "Amount"}

    def test_fingerprint_is_stable(self) -> None:
        schema1 = TargetSchema(
            name="test",
            fields={"A": FieldDefinition(type=FieldType.STRING)},
        )
        schema2 = TargetSchema(
            name="test",
            fields={"A": FieldDefinition(type=FieldType.STRING)},
        )
        assert schema1.fingerprint == schema2.fingerprint

    def test_fingerprint_changes_with_fields(self) -> None:
        schema1 = TargetSchema(
            name="test",
            fields={"A": FieldDefinition(type=FieldType.STRING)},
        )
        schema2 = TargetSchema(
            name="test",
            fields={"B": FieldDefinition(type=FieldType.FLOAT)},
        )
        assert schema1.fingerprint != schema2.fingerprint

    def test_fingerprint_ignores_name(self) -> None:
        """Schema name is metadata — two schemas with different names
        but identical fields should produce the same fingerprint."""
        schema1 = TargetSchema(
            name="alpha",
            fields={"A": FieldDefinition(type=FieldType.STRING)},
        )
        schema2 = TargetSchema(
            name="beta",
            fields={"A": FieldDefinition(type=FieldType.STRING)},
        )
        assert schema1.fingerprint == schema2.fingerprint

    def test_fingerprint_is_32_hex_chars(self) -> None:
        schema = TargetSchema(
            name="test",
            fields={"A": FieldDefinition(type=FieldType.STRING)},
        )
        assert len(schema.fingerprint) == 32
        assert all(c in "0123456789abcdef" for c in schema.fingerprint)


class TestFieldDefinitionConstraints:
    """Loop 2: Constraint-type safety — invalid combinations rejected."""

    def test_non_negative_only_on_float(self) -> None:
        with pytest.raises(ValueError, match="non_negative"):
            FieldDefinition(type=FieldType.STRING, non_negative=True)

    def test_not_empty_only_on_string(self) -> None:
        with pytest.raises(ValueError, match="not_empty"):
            FieldDefinition(type=FieldType.FLOAT, not_empty=True)

    def test_not_empty_rejected_on_date(self) -> None:
        with pytest.raises(ValueError, match="not_empty"):
            FieldDefinition(type=FieldType.DATE, not_empty=True)

    def test_allowed_values_only_on_currency(self) -> None:
        with pytest.raises(ValueError, match="allowed_values"):
            FieldDefinition(type=FieldType.FLOAT, allowed_values=["X"])

    def test_valid_string_with_not_empty(self) -> None:
        defn = FieldDefinition(type=FieldType.STRING, not_empty=True)
        assert defn.not_empty is True

    def test_valid_float_with_non_negative(self) -> None:
        defn = FieldDefinition(type=FieldType.FLOAT, non_negative=True)
        assert defn.non_negative is True

    def test_valid_currency_with_allowed_values(self) -> None:
        defn = FieldDefinition(type=FieldType.CURRENCY, allowed_values=["USD", "GBP"])
        assert defn.allowed_values == ["USD", "GBP"]


class TestCrossFieldRuleValidation:
    """Loop 2: Cross-field rules must reference existing DATE fields."""

    def test_rejects_rule_referencing_nonexistent_field(self) -> None:
        with pytest.raises(ValueError, match="NoSuchField"):
            TargetSchema(
                name="test",
                fields={"Start": FieldDefinition(type=FieldType.DATE)},
                cross_field_rules=[
                    DateOrderingRule(earlier="Start", later="NoSuchField"),
                ],
            )

    def test_rejects_rule_on_non_date_field(self) -> None:
        with pytest.raises(ValueError, match="DATE"):
            TargetSchema(
                name="test",
                fields={
                    "Start": FieldDefinition(type=FieldType.DATE),
                    "Amount": FieldDefinition(type=FieldType.FLOAT),
                },
                cross_field_rules=[
                    DateOrderingRule(earlier="Start", later="Amount"),
                ],
            )

    def test_valid_date_ordering_rule(self) -> None:
        schema = TargetSchema(
            name="test",
            fields={
                "Start": FieldDefinition(type=FieldType.DATE),
                "End": FieldDefinition(type=FieldType.DATE),
            },
            cross_field_rules=[
                DateOrderingRule(earlier="Start", later="End"),
            ],
        )
        assert len(schema.cross_field_rules) == 1


class TestSLMHintValidation:
    """Loop 2: SLM hints must reference valid target fields with unique aliases."""

    def test_rejects_hint_referencing_nonexistent_field(self) -> None:
        with pytest.raises(ValueError, match="NoSuchField"):
            TargetSchema(
                name="test",
                fields={"Amount": FieldDefinition(type=FieldType.FLOAT)},
                slm_hints=[SLMHint(source_alias="GWP", target="NoSuchField")],
            )

    def test_rejects_duplicate_source_aliases(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            TargetSchema(
                name="test",
                fields={
                    "Amount": FieldDefinition(type=FieldType.FLOAT),
                    "Tax": FieldDefinition(type=FieldType.FLOAT),
                },
                slm_hints=[
                    SLMHint(source_alias="AMT", target="Amount"),
                    SLMHint(source_alias="AMT", target="Tax"),
                ],
            )

    def test_valid_hints(self) -> None:
        schema = TargetSchema(
            name="test",
            fields={
                "Amount": FieldDefinition(type=FieldType.FLOAT),
                "Currency": FieldDefinition(type=FieldType.CURRENCY, allowed_values=["USD"]),
            },
            slm_hints=[
                SLMHint(source_alias="GWP", target="Amount"),
                SLMHint(source_alias="Ccy", target="Currency"),
            ],
        )
        assert len(schema.slm_hints) == 2


class TestDefaultTargetSchema:
    """The default schema must match the current hardcoded 6-field schema."""

    def test_has_six_fields(self) -> None:
        assert len(DEFAULT_TARGET_SCHEMA.fields) == 6

    def test_field_names_match_hardcoded(self) -> None:
        expected = {
            "Policy_ID", "Inception_Date", "Expiry_Date",
            "Sum_Insured", "Gross_Premium", "Currency",
        }
        assert DEFAULT_TARGET_SCHEMA.field_names == expected

    def test_all_fields_required(self) -> None:
        assert DEFAULT_TARGET_SCHEMA.required_field_names == DEFAULT_TARGET_SCHEMA.field_names

    def test_has_date_ordering_rule(self) -> None:
        assert len(DEFAULT_TARGET_SCHEMA.cross_field_rules) == 1
        rule = DEFAULT_TARGET_SCHEMA.cross_field_rules[0]
        assert rule.earlier == "Inception_Date"
        assert rule.later == "Expiry_Date"

    def test_has_slm_hints(self) -> None:
        aliases = {h.source_alias for h in DEFAULT_TARGET_SCHEMA.slm_hints}
        assert "GWP" in aliases
        assert "TSI" in aliases
        assert "Ccy" in aliases

    def test_currency_allowed_values(self) -> None:
        currency_field = DEFAULT_TARGET_SCHEMA.fields["Currency"]
        assert currency_field.allowed_values == ["USD", "GBP", "EUR", "JPY"]

    def test_fingerprint_is_deterministic(self) -> None:
        fp1 = DEFAULT_TARGET_SCHEMA.fingerprint
        fp2 = DEFAULT_TARGET_SCHEMA.fingerprint
        assert fp1 == fp2
