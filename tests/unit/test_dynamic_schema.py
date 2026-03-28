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

    def test_fingerprint_changes_with_optional_sections(self) -> None:
        """Adding cross_field_rules or slm_hints must change the fingerprint."""
        base = TargetSchema(
            name="test",
            fields={
                "Start": FieldDefinition(type=FieldType.DATE),
                "End": FieldDefinition(type=FieldType.DATE),
            },
        )
        with_rules = TargetSchema(
            name="test",
            fields={
                "Start": FieldDefinition(type=FieldType.DATE),
                "End": FieldDefinition(type=FieldType.DATE),
            },
            cross_field_rules=[DateOrderingRule(earlier="Start", later="End")],
        )
        assert base.fingerprint != with_rules.fingerprint

    def test_empty_fields_allowed(self) -> None:
        """Empty schema is valid — useful for testing. Missing fields
        are surfaced by ConfidenceReport, not rejected at schema level."""
        schema = TargetSchema(name="empty", fields={})
        assert schema.field_names == set()
        assert schema.required_field_names == set()

    def test_single_field_schema(self) -> None:
        schema = TargetSchema(
            name="minimal",
            fields={"ID": FieldDefinition(type=FieldType.STRING)},
        )
        assert schema.field_names == {"ID"}

    def test_all_fields_optional(self) -> None:
        schema = TargetSchema(
            name="test",
            fields={
                "A": FieldDefinition(type=FieldType.STRING, required=False),
                "B": FieldDefinition(type=FieldType.FLOAT, required=False),
            },
        )
        assert schema.required_field_names == set()


class TestFieldDefinitionConstraints:
    """Loop 2: Constraint-type safety — invalid combinations rejected."""

    @pytest.mark.parametrize("field_type", [FieldType.STRING, FieldType.DATE, FieldType.CURRENCY])
    def test_non_negative_rejected_on_non_float(self, field_type: FieldType) -> None:
        kwargs: dict = {"type": field_type, "non_negative": True}
        if field_type == FieldType.CURRENCY:
            kwargs["allowed_values"] = ["USD"]
        with pytest.raises(ValueError, match="non_negative"):
            FieldDefinition(**kwargs)

    @pytest.mark.parametrize("field_type", [FieldType.FLOAT, FieldType.DATE, FieldType.CURRENCY])
    def test_not_empty_rejected_on_non_string(self, field_type: FieldType) -> None:
        kwargs: dict = {"type": field_type, "not_empty": True}
        if field_type == FieldType.CURRENCY:
            kwargs["allowed_values"] = ["USD"]
        with pytest.raises(ValueError, match="not_empty"):
            FieldDefinition(**kwargs)

    @pytest.mark.parametrize("field_type", [FieldType.STRING, FieldType.FLOAT, FieldType.DATE])
    def test_allowed_values_rejected_on_non_currency(self, field_type: FieldType) -> None:
        with pytest.raises(ValueError, match="allowed_values"):
            FieldDefinition(type=field_type, allowed_values=["X"])

    def test_valid_string_with_not_empty(self) -> None:
        defn = FieldDefinition(type=FieldType.STRING, not_empty=True)
        assert defn.not_empty is True

    def test_valid_float_with_non_negative(self) -> None:
        defn = FieldDefinition(type=FieldType.FLOAT, non_negative=True)
        assert defn.non_negative is True

    def test_valid_currency_with_allowed_values(self) -> None:
        defn = FieldDefinition(type=FieldType.CURRENCY, allowed_values=["USD", "GBP"])
        assert defn.allowed_values == ["USD", "GBP"]

    def test_empty_allowed_values_is_valid(self) -> None:
        """Empty list means no currency is accepted — weird but not invalid
        at the schema level. Validation catches it at row level."""
        defn = FieldDefinition(type=FieldType.CURRENCY, allowed_values=[])
        assert defn.allowed_values == []

    def test_defaults_have_no_constraints(self) -> None:
        defn = FieldDefinition(type=FieldType.STRING)
        assert defn.not_empty is False
        assert defn.non_negative is False
        assert defn.allowed_values is None
        assert defn.required is True


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

    def test_rejects_same_field_as_earlier_and_later(self) -> None:
        """A date ordering rule where earlier == later is nonsensical."""
        with pytest.raises(ValueError, match="Start"):
            TargetSchema(
                name="test",
                fields={"Start": FieldDefinition(type=FieldType.DATE)},
                cross_field_rules=[
                    DateOrderingRule(earlier="Start", later="Start"),
                ],
            )

    @pytest.mark.parametrize("non_date_type", [FieldType.STRING, FieldType.FLOAT, FieldType.CURRENCY])
    def test_rejects_rule_on_each_non_date_type(self, non_date_type: FieldType) -> None:
        kwargs: dict = {"type": non_date_type}
        if non_date_type == FieldType.CURRENCY:
            kwargs["allowed_values"] = ["USD"]
        with pytest.raises(ValueError, match="DATE"):
            TargetSchema(
                name="test",
                fields={
                    "Start": FieldDefinition(type=FieldType.DATE),
                    "Other": FieldDefinition(**kwargs),
                },
                cross_field_rules=[
                    DateOrderingRule(earlier="Start", later="Other"),
                ],
            )


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
