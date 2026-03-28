"""Configurable target schema for reinsurance data mapping.

Defines the structure that source spreadsheets are mapped TO.
Different cedents can define different target schemas via YAML config.
This is a pure domain model — no file I/O, no YAML awareness.

The schema is self-validating: invalid configurations (wrong constraint
types, cross-field rules on non-date fields, duplicate SLM aliases)
are rejected at parse time, not at runtime when processing a file.
"""

import enum
import hashlib
import json

from pydantic import BaseModel, model_validator


class FieldType(str, enum.Enum):
    STRING = "string"
    DATE = "date"
    FLOAT = "float"
    CURRENCY = "currency"


class FieldDefinition(BaseModel):
    """Definition of a single target field with type-safe constraints.

    Constraints are validated against the field type:
    - not_empty: only valid for STRING
    - non_negative: only valid for FLOAT
    - allowed_values: only valid for CURRENCY
    """

    type: FieldType
    required: bool = True
    not_empty: bool = False
    non_negative: bool = False
    allowed_values: list[str] | None = None

    @model_validator(mode="after")
    def constraints_match_type(self) -> "FieldDefinition":
        if self.non_negative and self.type != FieldType.FLOAT:
            msg = f"non_negative constraint only applies to FLOAT fields, got {self.type.value}"
            raise ValueError(msg)
        if self.not_empty and self.type != FieldType.STRING:
            msg = f"not_empty constraint only applies to STRING fields, got {self.type.value}"
            raise ValueError(msg)
        if self.allowed_values is not None and self.type != FieldType.CURRENCY:
            msg = f"allowed_values constraint only applies to CURRENCY fields, got {self.type.value}"
            raise ValueError(msg)
        return self


class DateOrderingRule(BaseModel):
    """Cross-field rule: one date must not precede another."""

    earlier: str
    later: str


class SLMHint(BaseModel):
    """Maps common source header aliases to target fields.

    Injected into the SLM prompt to improve mapping accuracy.
    E.g., "GWP" is a common alias for "Gross_Premium" in reinsurance.
    """

    source_alias: str
    target: str


class TargetSchema(BaseModel):
    """A complete target schema definition.

    Self-validating: cross-field rules must reference existing DATE fields,
    SLM hints must reference existing fields, aliases must be unique.
    """

    name: str
    fields: dict[str, FieldDefinition]
    cross_field_rules: list[DateOrderingRule] = []
    slm_hints: list[SLMHint] = []

    @property
    def field_names(self) -> set[str]:
        """All field names in this schema."""
        return set(self.fields.keys())

    @property
    def required_field_names(self) -> set[str]:
        """Only the required field names."""
        return {name for name, defn in self.fields.items() if defn.required}

    @property
    def fingerprint(self) -> str:
        """Stable hash of schema content for caching and audit trails.

        Excludes name (metadata) — two schemas with different names but
        identical fields produce the same fingerprint. Uses blake2b for
        speed with 16-byte digest (32 hex chars).
        """
        payload = self.model_dump(exclude={"name"})
        stable_json = json.dumps(payload, sort_keys=True).encode()
        return hashlib.blake2b(stable_json, digest_size=16).hexdigest()

    @model_validator(mode="after")
    def cross_field_rules_reference_valid_date_fields(self) -> "TargetSchema":
        """Cross-field rules must reference existing, distinct fields of type DATE."""
        for rule in self.cross_field_rules:
            if rule.earlier == rule.later:
                msg = (
                    f"Cross-field rule has same field '{rule.earlier}' "
                    f"as both earlier and later"
                )
                raise ValueError(msg)
            for field_ref in [rule.earlier, rule.later]:
                if field_ref not in self.fields:
                    msg = (
                        f"Cross-field rule references '{field_ref}' "
                        f"but schema only has fields: {sorted(self.fields.keys())}"
                    )
                    raise ValueError(msg)
                if self.fields[field_ref].type != FieldType.DATE:
                    msg = (
                        f"Cross-field rule references '{field_ref}' "
                        f"which is {self.fields[field_ref].type.value}, not DATE"
                    )
                    raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def slm_hints_valid_and_unique(self) -> "TargetSchema":
        """SLM hints must reference existing fields with unique aliases."""
        aliases: list[str] = []
        for hint in self.slm_hints:
            if hint.target not in self.fields:
                msg = (
                    f"SLM hint target '{hint.target}' "
                    f"not in schema fields: {sorted(self.fields.keys())}"
                )
                raise ValueError(msg)
            aliases.append(hint.source_alias)

        if len(aliases) != len(set(aliases)):
            dupes = [a for a in aliases if aliases.count(a) > 1]
            msg = f"SLM hints contain duplicate source aliases: {sorted(set(dupes))}"
            raise ValueError(msg)
        return self


DEFAULT_TARGET_SCHEMA = TargetSchema(
    name="standard_reinsurance",
    fields={
        "Policy_ID": FieldDefinition(type=FieldType.STRING, not_empty=True),
        "Inception_Date": FieldDefinition(type=FieldType.DATE),
        "Expiry_Date": FieldDefinition(type=FieldType.DATE),
        "Sum_Insured": FieldDefinition(type=FieldType.FLOAT, non_negative=True),
        "Gross_Premium": FieldDefinition(type=FieldType.FLOAT, non_negative=True),
        "Currency": FieldDefinition(
            type=FieldType.CURRENCY,
            allowed_values=["USD", "GBP", "EUR", "JPY"],
        ),
    },
    cross_field_rules=[
        DateOrderingRule(earlier="Inception_Date", later="Expiry_Date"),
    ],
    slm_hints=[
        SLMHint(source_alias="GWP", target="Gross_Premium"),
        SLMHint(source_alias="TSI", target="Sum_Insured"),
        SLMHint(source_alias="Ccy", target="Currency"),
        SLMHint(source_alias="Certificate", target="Policy_ID"),
    ],
)
