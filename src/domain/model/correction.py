"""Domain model for human-verified mapping corrections.

A Correction records that for a specific cedent, a source header
should map to a specific target field. These override the SLM with
confidence 1.0 and build a feedback loop that improves accuracy.
"""

from pydantic import BaseModel, field_validator


class Correction(BaseModel):
    """A human-verified mapping: (cedent_id, source_header) → target_field."""

    cedent_id: str
    source_header: str
    target_field: str

    @field_validator("cedent_id")
    @classmethod
    def cedent_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            msg = "cedent_id must not be empty"
            raise ValueError(msg)
        return v

    @field_validator("source_header")
    @classmethod
    def source_header_not_empty(cls, v: str) -> str:
        if not v.strip():
            msg = "source_header must not be empty"
            raise ValueError(msg)
        return v

    @field_validator("target_field")
    @classmethod
    def target_field_not_empty(cls, v: str) -> str:
        if not v.strip():
            msg = "target_field must not be empty"
            raise ValueError(msg)
        return v
