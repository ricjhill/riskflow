"""Tests for Correction domain model.

A Correction represents a human-verified mapping: for a given cedent,
a specific source header maps to a specific target field. Used to
build a feedback loop that improves mapping accuracy over time.
"""

import pytest

from src.domain.model.correction import Correction


class TestCorrectionCreation:
    """Valid construction and field access."""

    def test_valid_correction(self) -> None:
        c = Correction(
            cedent_id="ACME_RE",
            source_header="GWP",
            target_field="Gross_Premium",
        )
        assert c.cedent_id == "ACME_RE"
        assert c.source_header == "GWP"
        assert c.target_field == "Gross_Premium"

    def test_special_characters_in_source_header(self) -> None:
        """Real bordereaux have headers like 'Policy #', 'Sum (USD)'."""
        c = Correction(
            cedent_id="ABC",
            source_header="Sum (USD)",
            target_field="Sum_Insured",
        )
        assert c.source_header == "Sum (USD)"

    def test_source_header_preserves_whitespace_content(self) -> None:
        """Headers may have internal spaces — these should be preserved."""
        c = Correction(
            cedent_id="ABC",
            source_header="Total Sum Insured",
            target_field="Sum_Insured",
        )
        assert c.source_header == "Total Sum Insured"


class TestCorrectionValidation:
    """All three string fields must be non-empty."""

    def test_rejects_empty_cedent_id(self) -> None:
        with pytest.raises(ValueError, match="cedent_id"):
            Correction(cedent_id="", source_header="GWP", target_field="Gross_Premium")

    def test_rejects_whitespace_only_cedent_id(self) -> None:
        with pytest.raises(ValueError, match="cedent_id"):
            Correction(cedent_id="   ", source_header="GWP", target_field="Gross_Premium")

    def test_rejects_empty_source_header(self) -> None:
        with pytest.raises(ValueError, match="source_header"):
            Correction(cedent_id="ABC", source_header="", target_field="Gross_Premium")

    def test_rejects_whitespace_only_source_header(self) -> None:
        with pytest.raises(ValueError, match="source_header"):
            Correction(cedent_id="ABC", source_header="  ", target_field="Gross_Premium")

    def test_rejects_empty_target_field(self) -> None:
        with pytest.raises(ValueError, match="target_field"):
            Correction(cedent_id="ABC", source_header="GWP", target_field="")

    def test_rejects_whitespace_only_target_field(self) -> None:
        with pytest.raises(ValueError, match="target_field"):
            Correction(cedent_id="ABC", source_header="GWP", target_field="  ")


class TestCorrectionEquality:
    """Same inputs should produce equal objects."""

    def test_equal_corrections(self) -> None:
        c1 = Correction(cedent_id="ABC", source_header="GWP", target_field="Gross_Premium")
        c2 = Correction(cedent_id="ABC", source_header="GWP", target_field="Gross_Premium")
        assert c1 == c2
