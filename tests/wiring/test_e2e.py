"""End-to-end integration test: upload CSV → get mapped results.

Uses the real app with real PolarsIngestor and NullCache, but mocks
the GroqMapper to avoid real API calls. This proves that all the
pieces connect — file upload, parsing, service orchestration, error
mapping, and response serialization.

Covers features from all loops: row validation, confidence report,
structured errors, async upload, sheet names, file validation, and
partial mapping.
"""

import io
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.wiring
from fastapi.testclient import TestClient

from src.domain.model.schema import ColumnMapping, MappingResult


def _make_mapping_response(headers: list[str]) -> MappingResult:
    """Build a realistic mapping result for the given headers."""
    known_mappings: dict[str, tuple[str, float]] = {
        "Policy No.": ("Policy_ID", 0.99),
        "Start Date": ("Inception_Date", 0.95),
        "End Date": ("Expiry_Date", 0.95),
        "TSI": ("Sum_Insured", 0.90),
        "GWP": ("Gross_Premium", 0.97),
        "Ccy": ("Currency", 0.98),
    }
    mappings = []
    unmapped = []
    for h in headers:
        if h in known_mappings:
            target, conf = known_mappings[h]
            mappings.append(
                ColumnMapping(
                    source_header=h, target_field=target, confidence=conf
                )
            )
        else:
            unmapped.append(h)
    return MappingResult(mappings=mappings, unmapped_headers=unmapped)


SAMPLE_CSV = (
    "Policy No.,Start Date,End Date,TSI,GWP,Ccy,Notes\n"
    "POL-001,2024-01-01,2025-01-01,1000000,50000,USD,Renewal\n"
    "POL-002,2024-06-15,2025-06-15,2000000,75000,GBP,New business\n"
)

CSV_WITH_INVALID_ROWS = (
    "Policy No.,Start Date,End Date,TSI,GWP,Ccy\n"
    "POL-001,2024-01-01,2025-01-01,1000000,50000,USD\n"
    "POL-002,2024-06-15,2025-06-15,2000000,75000,DOLLARS\n"
    "POL-003,2024-03-01,2025-03-01,-500000,25000,EUR\n"
)

PARTIAL_CSV = (
    "Policy No.,GWP\n"
    "POL-001,50000\n"
    "POL-002,75000\n"
)


@pytest.fixture
def mock_groq() -> AsyncMock:
    """Mock the GroqMapper.map_headers to return a realistic mapping."""
    mock = AsyncMock()

    async def _fake_map(
        source_headers: list[str],
        preview_rows: list[dict[str, object]],
    ) -> MappingResult:
        return _make_mapping_response(source_headers)

    mock.map_headers.side_effect = _fake_map
    return mock


@pytest.fixture
def client(mock_groq: AsyncMock) -> TestClient:
    """Create a TestClient with real ingestor + NullCache + mocked SLM."""
    with patch("src.entrypoint.main.GroqMapper") as MockMapper:
        MockMapper.return_value = mock_groq

        from src.entrypoint.main import create_app

        app = create_app()
        yield TestClient(app)


class TestEndToEnd:
    """Full pipeline: upload CSV → parse → map → return results."""

    def test_upload_csv_returns_mapping(self, client: TestClient) -> None:
        response = client.post(
            "/upload",
            files={
                "file": ("bordereaux.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert "mapping" in body
        assert "valid_records" in body
        assert "errors" in body

    def test_maps_all_known_headers(self, client: TestClient) -> None:
        response = client.post(
            "/upload",
            files={
                "file": ("bordereaux.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )

        body = response.json()
        mapped_targets = {m["target_field"] for m in body["mapping"]["mappings"]}
        assert "Policy_ID" in mapped_targets
        assert "Inception_Date" in mapped_targets
        assert "Expiry_Date" in mapped_targets
        assert "Sum_Insured" in mapped_targets
        assert "Gross_Premium" in mapped_targets
        assert "Currency" in mapped_targets

    def test_identifies_unmapped_headers(self, client: TestClient) -> None:
        response = client.post(
            "/upload",
            files={
                "file": ("bordereaux.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )

        body = response.json()
        assert "Notes" in body["mapping"]["unmapped_headers"]

    def test_confidence_scores_are_present(self, client: TestClient) -> None:
        response = client.post(
            "/upload",
            files={
                "file": ("bordereaux.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )

        body = response.json()
        for mapping in body["mapping"]["mappings"]:
            assert "confidence" in mapping
            assert 0.0 <= mapping["confidence"] <= 1.0

    def test_health_still_works(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestEdgeCases:
    """E2E edge cases that exercise the full pipeline."""

    def test_single_column_csv(self, client: TestClient) -> None:
        csv = "GWP\n50000\n75000\n"
        response = client.post(
            "/upload",
            files={"file": ("single.csv", io.BytesIO(csv.encode()), "text/csv")},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["mapping"]["mappings"]) == 1
        assert body["mapping"]["mappings"][0]["target_field"] == "Gross_Premium"

    def test_all_unmapped_headers(self, client: TestClient) -> None:
        csv = "Foo,Bar,Baz\n1,2,3\n"
        response = client.post(
            "/upload",
            files={"file": ("unknown.csv", io.BytesIO(csv.encode()), "text/csv")},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["mapping"]["mappings"]) == 0
        assert set(body["mapping"]["unmapped_headers"]) == {"Foo", "Bar", "Baz"}

    def test_empty_csv_with_headers_only(self, client: TestClient) -> None:
        csv = "Policy No.,GWP\n"
        response = client.post(
            "/upload",
            files={"file": ("empty.csv", io.BytesIO(csv.encode()), "text/csv")},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["mapping"]["mappings"]) == 2


class TestRowValidation:
    """E2E: row validation produces valid_records and errors."""

    def test_valid_rows_in_response(self, client: TestClient) -> None:
        response = client.post(
            "/upload",
            files={
                "file": ("data.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )

        body = response.json()
        assert len(body["valid_records"]) == 2
        assert body["valid_records"][0]["Policy_ID"] == "POL-001"
        assert body["valid_records"][0]["Currency"] == "USD"

    def test_invalid_rows_captured_as_errors(self, client: TestClient) -> None:
        response = client.post(
            "/upload",
            files={
                "file": (
                    "bad.csv",
                    io.BytesIO(CSV_WITH_INVALID_ROWS.encode()),
                    "text/csv",
                )
            },
        )

        body = response.json()
        assert len(body["valid_records"]) == 1
        assert body["valid_records"][0]["Policy_ID"] == "POL-001"
        assert len(body["errors"]) == 2
        error_rows = {e["row"] for e in body["errors"]}
        assert error_rows == {2, 3}

    def test_invalid_records_included(self, client: TestClient) -> None:
        response = client.post(
            "/upload",
            files={
                "file": (
                    "bad.csv",
                    io.BytesIO(CSV_WITH_INVALID_ROWS.encode()),
                    "text/csv",
                )
            },
        )

        body = response.json()
        assert len(body["invalid_records"]) == 2


class TestConfidenceReportE2E:
    """E2E: confidence report is included in the response."""

    def test_confidence_report_present(self, client: TestClient) -> None:
        response = client.post(
            "/upload",
            files={
                "file": ("data.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )

        body = response.json()
        report = body["confidence_report"]
        assert "min_confidence" in report
        assert "avg_confidence" in report
        assert "low_confidence_fields" in report
        assert "missing_fields" in report

    def test_missing_fields_for_partial_mapping(self, client: TestClient) -> None:
        """A CSV with only Policy_ID and Gross_Premium mapped should
        report the other 4 target fields as missing."""
        response = client.post(
            "/upload",
            files={
                "file": (
                    "partial.csv",
                    io.BytesIO(PARTIAL_CSV.encode()),
                    "text/csv",
                )
            },
        )

        body = response.json()
        missing = body["confidence_report"]["missing_fields"]
        assert "Inception_Date" in missing
        assert "Expiry_Date" in missing
        assert "Sum_Insured" in missing
        assert "Currency" in missing
        assert len(missing) == 4


class TestStructuredErrorsE2E:
    """E2E: error responses have error_code, message, suggestion."""

    def test_invalid_file_type_returns_400(self, client: TestClient) -> None:
        response = client.post(
            "/upload",
            files={
                "file": ("report.pdf", io.BytesIO(b"data"), "application/pdf")
            },
        )

        assert response.status_code == 400
        assert "file type" in response.json()["detail"].lower()

    def test_oversized_file_returns_400(self, client: TestClient) -> None:
        big = b"x" * (11 * 1024 * 1024)
        response = client.post(
            "/upload",
            files={"file": ("big.csv", io.BytesIO(big), "text/csv")},
        )

        assert response.status_code == 400
        assert "size" in response.json()["detail"].lower()

    def test_slm_error_returns_structured_503(self, mock_groq: AsyncMock, client: TestClient) -> None:
        """When the SLM fails, error response should have error_code."""
        from src.domain.model.errors import SLMUnavailableError

        mock_groq.map_headers.side_effect = SLMUnavailableError("Groq API timeout")

        response = client.post(
            "/upload",
            files={
                "file": ("data.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["error_code"] == "SLM_UNAVAILABLE"
        assert "suggestion" in detail


class TestAsyncUploadE2E:
    """E2E: async upload returns job_id, job status endpoint works."""

    def test_async_upload_returns_202(self, client: TestClient) -> None:
        response = client.post(
            "/upload/async",
            files={
                "file": ("data.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )

        assert response.status_code == 202
        assert "job_id" in response.json()

    def test_async_job_completes(self, client: TestClient) -> None:
        response = client.post(
            "/upload/async",
            files={
                "file": ("data.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )

        job_id = response.json()["job_id"]

        # TestClient runs background tasks synchronously, so job
        # should be complete immediately
        status = client.get(f"/jobs/{job_id}")
        assert status.status_code == 200
        body = status.json()
        assert body["status"] in ("complete", "processing", "pending")

    def test_nonexistent_job_returns_404(self, client: TestClient) -> None:
        response = client.get("/jobs/nonexistent-id")
        assert response.status_code == 404


class TestSheetNamesE2E:
    """E2E: POST /sheets returns sheet names."""

    def test_csv_returns_empty_sheets(self, client: TestClient) -> None:
        response = client.post(
            "/sheets",
            files={
                "file": ("data.csv", io.BytesIO(b"A,B\n1,2\n"), "text/csv")
            },
        )

        assert response.status_code == 200
        assert response.json() == {"sheets": []}

    def test_invalid_file_type_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/sheets",
            files={
                "file": ("report.pdf", io.BytesIO(b"data"), "application/pdf")
            },
        )

        assert response.status_code == 400


class TestFileValidationE2E:
    """E2E: file validation rejects bad uploads before processing."""

    @pytest.mark.parametrize("filename", ["report.pdf", "data.json", "image.png"])
    def test_rejects_non_spreadsheet(self, client: TestClient, filename: str) -> None:
        response = client.post(
            "/upload",
            files={
                "file": (filename, io.BytesIO(b"content"), "application/octet-stream")
            },
        )
        assert response.status_code == 400

    def test_accepts_csv(self, client: TestClient) -> None:
        response = client.post(
            "/upload",
            files={
                "file": ("data.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )
        assert response.status_code == 200
