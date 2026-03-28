"""Domain models for reinsurance data mapping."""

import datetime
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

VALID_CURRENCIES: set[str] = {"USD", "GBP", "EUR", "JPY"}

VALID_TARGET_FIELDS: set[str] = {
    "Policy_ID",
    "Inception_Date",
    "Expiry_Date",
    "Sum_Insured",
    "Gross_Premium",
    "Currency",
}


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
    """Maps a source spreadsheet header to a target schema field."""

    source_header: str
    target_field: str
    confidence: float

    @field_validator("target_field")
    @classmethod
    def target_field_must_be_valid(cls, v: str) -> str:
        if v not in VALID_TARGET_FIELDS:
            msg = f"target_field must be one of {VALID_TARGET_FIELDS}, got '{v}'"
            raise ValueError(msg)
        return v

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
    ) -> "ConfidenceReport":
        if not result.mappings:
            return cls(
                min_confidence=0.0,
                avg_confidence=0.0,
                low_confidence_fields=[],
                missing_fields=sorted(VALID_TARGET_FIELDS),
            )

        confidences = [m.confidence for m in result.mappings]
        mapped_targets = {m.target_field for m in result.mappings}

        return cls(
            min_confidence=min(confidences),
            avg_confidence=sum(confidences) / len(confidences),
            low_confidence_fields=[
                m for m in result.mappings if m.confidence < threshold
            ],
            missing_fields=sorted(VALID_TARGET_FIELDS - mapped_targets),
        )


class RowError(BaseModel):
    """A validation error for a specific row."""

    row: int
    error: str


class ProcessingResult(BaseModel):
    """Full result of processing a spreadsheet: mapping + row validation."""

    mapping: MappingResult
    confidence_report: ConfidenceReport
    valid_records: list[RiskRecord]
    invalid_records: list[dict[str, object]]
    errors: list[RowError]
