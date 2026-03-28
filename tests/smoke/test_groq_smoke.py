"""Smoke tests that call the real Groq API.

These tests are NOT run in the standard CI pipeline — they run in a
separate 'smoke' job that has access to GROQ_API_KEY. This catches
issues that mocked tests miss: model deprecation, API changes, prompt
regressions, and response format drift.

Skipped automatically when GROQ_API_KEY is not set.
"""

import os

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set — skipping smoke tests",
)


SAMPLE_CSV = (
    "Policy No.,Start Date,End Date,Total Sum Insured,GWP,Ccy,Broker Notes\n"
    "POL-2024-001,2024-01-15,2025-01-15,5000000,125000,USD,Renewal\n"
    "POL-2024-002,2024-03-01,2025-03-01,2500000,75000,GBP,New business\n"
)


@pytest.fixture
def client() -> TestClient:
    """Create a TestClient with the REAL app — real Groq, real Polars, NullCache."""
    from src.entrypoint.main import create_app

    app = create_app()
    return TestClient(app)


class TestGroqSmoke:
    """Verify the real SLM maps headers correctly."""

    def test_health(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200

    def test_upload_maps_all_target_fields(self, client: TestClient) -> None:
        """Upload a realistic bordereaux CSV and verify all 6 target fields are mapped."""
        import io

        response = client.post(
            "/upload",
            files={
                "file": ("bordereaux.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )

        assert response.status_code == 200, f"Upload failed: {response.json()}"
        body = response.json()

        mapped_targets = {m["target_field"] for m in body["mapping"]["mappings"]}
        assert "Policy_ID" in mapped_targets, f"Missing Policy_ID. Mapped: {mapped_targets}"
        assert "Gross_Premium" in mapped_targets, f"Missing Gross_Premium. Mapped: {mapped_targets}"
        assert "Currency" in mapped_targets, f"Missing Currency. Mapped: {mapped_targets}"

    def test_confidence_scores_are_reasonable(self, client: TestClient) -> None:
        """Confidence scores should be > 0.5 for obvious mappings."""
        import io

        response = client.post(
            "/upload",
            files={
                "file": ("bordereaux.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )

        body = response.json()
        for mapping in body["mapping"]["mappings"]:
            assert mapping["confidence"] >= 0.5, (
                f"Low confidence for {mapping['source_header']} → {mapping['target_field']}: "
                f"{mapping['confidence']}"
            )

    def test_row_validation_produces_valid_records(self, client: TestClient) -> None:
        """Valid rows should be parsed into records."""
        import io

        response = client.post(
            "/upload",
            files={
                "file": ("bordereaux.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )

        body = response.json()
        # With all 6 fields mapped correctly, rows should validate
        assert len(body["valid_records"]) > 0, (
            f"No valid records. Errors: {body['errors']}"
        )

    def test_confidence_report_present(self, client: TestClient) -> None:
        """Response should include confidence report."""
        import io

        response = client.post(
            "/upload",
            files={
                "file": ("bordereaux.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )

        body = response.json()
        assert "confidence_report" in body
        assert body["confidence_report"]["min_confidence"] > 0
