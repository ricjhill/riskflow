"""Domain models for reinsurance data mapping."""

import datetime
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator


class RiskRecord(BaseModel):
    """A single validated reinsurance risk record."""

    Policy_ID: str
    Inception_Date: datetime.date
    Expiry_Date: datetime.date
    Sum_Insured: float
    Gross_Premium: float
    Currency: Literal["USD", "GBP", "EUR", "JPY"]

    @field_validator("Policy_ID")
    @classmethod
    def policy_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            msg = "Policy_ID must not be empty"
            raise ValueError(msg)
        return v

    @field_validator("Sum_Insured")
    @classmethod
    def sum_insured_non_negative(cls, v: float) -> float:
        if v < 0:
            msg = "Sum_Insured must be non-negative"
            raise ValueError(msg)
        return v

    @field_validator("Gross_Premium")
    @classmethod
    def gross_premium_non_negative(cls, v: float) -> float:
        if v < 0:
            msg = "Gross_Premium must be non-negative"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def expiry_not_before_inception(self) -> "RiskRecord":
        if self.Expiry_Date < self.Inception_Date:
            msg = "Expiry_Date must not be before Inception_Date"
            raise ValueError(msg)
        return self


class ColumnMapping(BaseModel):
    """Maps a source spreadsheet header to a target schema field.

    target_field is not validated here — it's validated at the
    MappingResult level via validate_against_schema() where the
    TargetSchema is known. This allows ColumnMapping to work with
    any schema, not just the hardcoded default.
    """

    source_header: str
    target_field: str
    confidence: float

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            msg = "confidence must be between 0.0 and 1.0"
            raise ValueError(msg)
        return v


class MappingResult(BaseModel):
    """Result of SLM header mapping."""

    mappings: list[ColumnMapping]
    unmapped_headers: list[str]

    @model_validator(mode="after")
    def no_duplicate_target_fields(self) -> "MappingResult":
        targets = [m.target_field for m in self.mappings]
        dupes = [t for t in targets if targets.count(t) > 1]
        if dupes:
            msg = f"MappingResult contains duplicate target fields: {set(dupes)}"
            raise ValueError(msg)
        return self

    def validate_against_schema(self, valid_fields: set[str]) -> None:
        """Validate that all target fields exist in the given field set.

        Called by the MappingService after receiving the SLM response,
        using the active TargetSchema's field_names. Raises ValueError
        if any mapping references a field not in the schema.
        """
        for mapping in self.mappings:
            if mapping.target_field not in valid_fields:
                msg = (
                    f"target_field '{mapping.target_field}' not in schema fields: "
                    f"{sorted(valid_fields)}"
                )
                raise ValueError(msg)


DEFAULT_CONFIDENCE_REVIEW_THRESHOLD = 0.6


class ConfidenceReport(BaseModel):
    """Summarizes mapping quality for human review.

    Built from a MappingResult, this report highlights:
    - Overall confidence (min and average)
    - Which fields have low confidence and need review
    - Which target fields were not mapped at all
    """

    min_confidence: float
    avg_confidence: float
    low_confidence_fields: list["ColumnMapping"]
    missing_fields: list[str]

    @classmethod
    def from_mapping_result(
        cls,
        result: "MappingResult",
        threshold: float = DEFAULT_CONFIDENCE_REVIEW_THRESHOLD,
        valid_fields: set[str] | None = None,
    ) -> "ConfidenceReport":
        if valid_fields is None:
            msg = "valid_fields is required — pass schema.field_names"
            raise ValueError(msg)
        all_fields = valid_fields

        if not result.mappings:
            return cls(
                min_confidence=0.0,
                avg_confidence=0.0,
                low_confidence_fields=[],
                missing_fields=sorted(all_fields),
            )

        confidences = [m.confidence for m in result.mappings]
        mapped_targets = {m.target_field for m in result.mappings}

        return cls(
            min_confidence=min(confidences),
            avg_confidence=sum(confidences) / len(confidences),
            low_confidence_fields=[
                m for m in result.mappings if m.confidence < threshold
            ],
            missing_fields=sorted(all_fields - mapped_targets),
        )


class RowError(BaseModel):
    """A validation error for a specific row."""

    row: int
    error: str


class ProcessingResult(BaseModel):
    """Full result of processing a spreadsheet: mapping + row validation.

    valid_records uses list[dict] instead of list[RiskRecord] because
    the record model is dynamic — field names depend on the active
    TargetSchema. Dicts are the natural serialization format and avoid
    complex generic type gymnastics.
    """

    mapping: MappingResult
    confidence_report: ConfidenceReport
    valid_records: list[dict[str, object]]
    invalid_records: list[dict[str, object]]
    errors: list[RowError]
