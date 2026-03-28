"""Tests for FastAPI HTTP adapter routes.

Uses TestClient with a mocked MappingService — no real file I/O or SLM calls.
Tests verify request handling, response shapes, and domain error → HTTP status mapping.
"""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.adapters.http.routes import create_router
from src.domain.model.errors import (
    InvalidCedentDataError,
    InvalidCorrectionError,
    MappingConfidenceLowError,
    SchemaValidationError,
    SLMUnavailableError,
)
from src.domain.model.schema import ColumnMapping, ConfidenceReport, MappingResult, ProcessingResult

from fastapi import FastAPI


def _make_processing_result() -> ProcessingResult:
    mapping = MappingResult(
        mappings=[
            ColumnMapping(
                source_header="Policy No.",
                target_field="Policy_ID",
                confidence=0.99,
            ),
            ColumnMapping(
                source_header="GWP",
                target_field="Gross_Premium",
                confidence=0.95,
            ),
        ],
        unmapped_headers=["Extra"],
    )
    return ProcessingResult(
        mapping=mapping,
        confidence_report=ConfidenceReport.from_mapping_result(mapping),
        valid_records=[],
        invalid_records=[],
        errors=[],
    )


def _create_test_app(mapping_service: AsyncMock) -> FastAPI:
    app = FastAPI()
    router = create_router(mapping_service)
    app.include_router(router)
    return app


def _upload_csv(
    client: TestClient, content: str = "ID,Value\n1,a\n", url: str = "/upload"
) -> object:
    return client.post(
        url,
        files={"file": ("test.csv", io.BytesIO(content.encode()), "text/csv")},
    )


class TestUploadEndpoint:
    def test_returns_200_with_mapping_result(self) -> None:
        service = AsyncMock()
        service.process_file.return_value = _make_processing_result()
        app = _create_test_app(service)
        client = TestClient(app)

        response = _upload_csv(client)

        assert response.status_code == 200
        body = response.json()
        assert "mapping" in body
        assert "valid_records" in body
        assert "errors" in body
        assert "confidence_report" in body
        assert len(body["mapping"]["mappings"]) == 2

    def test_mapping_result_contains_expected_fields(self) -> None:
        service = AsyncMock()
        service.process_file.return_value = _make_processing_result()
        app = _create_test_app(service)
        client = TestClient(app)

        response = _upload_csv(client)
        mapping = response.json()["mapping"]["mappings"][0]

        assert "source_header" in mapping
        assert "target_field" in mapping
        assert "confidence" in mapping

    def test_passes_file_to_service(self) -> None:
        service = AsyncMock()
        service.process_file.return_value = _make_processing_result()
        app = _create_test_app(service)
        client = TestClient(app)

        _upload_csv(client, content="Col1,Col2\nx,y\n")

        service.process_file.assert_called_once()
        # The temp file path is dynamic, just verify it was called
        call_path = service.process_file.call_args[0][0]
        assert isinstance(call_path, str)

    def test_cleans_up_temp_file(self) -> None:
        import os

        service = AsyncMock()
        service.process_file.return_value = _make_processing_result()
        app = _create_test_app(service)
        client = TestClient(app)

        _upload_csv(client)

        # The temp file should be deleted after processing
        call_path = service.process_file.call_args[0][0]
        assert not os.path.exists(call_path)


class TestSheetNameParam:
    """Upload endpoint accepts optional sheet_name query param."""

    def test_passes_sheet_name_to_service(self) -> None:
        service = AsyncMock()
        service.process_file.return_value = _make_processing_result()
        app = _create_test_app(service)
        client = TestClient(app)

        client.post(
            "/upload?sheet_name=Claims",
            files={"file": ("test.xlsx", io.BytesIO(b"data"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

        call_kwargs = service.process_file.call_args
        assert call_kwargs[1]["sheet_name"] == "Claims"

    def test_sheet_name_defaults_to_none(self) -> None:
        service = AsyncMock()
        service.process_file.return_value = _make_processing_result()
        app = _create_test_app(service)
        client = TestClient(app)

        _upload_csv(client)

        call_kwargs = service.process_file.call_args
        assert call_kwargs[1]["sheet_name"] is None


class TestSheetNameErrors:
    """Nonexistent sheet names must return 400, not 500."""

    def test_nonexistent_sheet_returns_400(self) -> None:
        service = AsyncMock()
        service.process_file.side_effect = ValueError(
            "Sheet 'NoSuchSheet' not found in /tmp/test.xlsx"
        )
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.post(
            "/upload?sheet_name=NoSuchSheet",
            files={"file": ("test.xlsx", io.BytesIO(b"data"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error_code"] == "INVALID_SHEET"
        assert "NoSuchSheet" in detail["message"]
        assert "suggestion" in detail


class TestErrorMapping:
    """Domain errors must map to appropriate HTTP status codes."""

    def test_low_confidence_returns_422(self) -> None:
        service = AsyncMock()
        service.process_file.side_effect = MappingConfidenceLowError(
            "confidence 0.3 below threshold 0.6"
        )
        app = _create_test_app(service)
        client = TestClient(app)

        response = _upload_csv(client)

        assert response.status_code == 422
        assert "confidence" in response.json()["detail"]["message"].lower()

    def test_invalid_cedent_data_returns_400(self) -> None:
        service = AsyncMock()
        service.process_file.side_effect = InvalidCedentDataError(
            "unparseable spreadsheet"
        )
        app = _create_test_app(service)
        client = TestClient(app)

        response = _upload_csv(client)

        assert response.status_code == 400
        assert "unparseable" in response.json()["detail"]["message"].lower()

    def test_schema_validation_error_returns_422(self) -> None:
        service = AsyncMock()
        service.process_file.side_effect = SchemaValidationError(
            "Currency 'DOLLARS' not in ISO 4217"
        )
        app = _create_test_app(service)
        client = TestClient(app)

        response = _upload_csv(client)

        assert response.status_code == 422
        assert "dollars" in response.json()["detail"]["message"].lower()

    def test_slm_unavailable_returns_503(self) -> None:
        service = AsyncMock()
        service.process_file.side_effect = SLMUnavailableError(
            "Groq API timeout"
        )
        app = _create_test_app(service)
        client = TestClient(app)

        response = _upload_csv(client)

        assert response.status_code == 503
        assert "detail" in response.json()

    def test_unexpected_error_returns_500(self) -> None:
        service = AsyncMock()
        service.process_file.side_effect = RuntimeError("unexpected crash")
        app = _create_test_app(service)
        client = TestClient(app)

        response = _upload_csv(client)

        assert response.status_code == 500
        assert "internal" in response.json()["detail"]["message"].lower()

    def test_no_file_uploaded_returns_422(self) -> None:
        service = AsyncMock()
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.post("/upload")

        assert response.status_code == 422


class TestStructuredErrorResponses:
    """Error responses must include error_code, message, and suggestion."""

    def test_low_confidence_includes_structured_detail(self) -> None:
        service = AsyncMock()
        service.process_file.side_effect = MappingConfidenceLowError(
            "Mapping 'GWP' -> 'Gross_Premium' has confidence 0.3, below threshold 0.6"
        )
        app = _create_test_app(service)
        client = TestClient(app)

        response = _upload_csv(client)
        detail = response.json()["detail"]

        assert detail["error_code"] == "LOW_CONFIDENCE"
        assert "GWP" in detail["message"]
        assert "suggestion" in detail

    def test_slm_unavailable_includes_structured_detail(self) -> None:
        service = AsyncMock()
        service.process_file.side_effect = SLMUnavailableError(
            "Groq API timeout"
        )
        app = _create_test_app(service)
        client = TestClient(app)

        response = _upload_csv(client)
        detail = response.json()["detail"]

        assert detail["error_code"] == "SLM_UNAVAILABLE"
        assert "suggestion" in detail

    def test_invalid_cedent_data_includes_structured_detail(self) -> None:
        service = AsyncMock()
        service.process_file.side_effect = InvalidCedentDataError(
            "unparseable spreadsheet"
        )
        app = _create_test_app(service)
        client = TestClient(app)

        response = _upload_csv(client)
        detail = response.json()["detail"]

        assert detail["error_code"] == "INVALID_DATA"
        assert "suggestion" in detail

    def test_schema_validation_includes_structured_detail(self) -> None:
        service = AsyncMock()
        service.process_file.side_effect = SchemaValidationError(
            "Currency 'DOLLARS' not in ISO 4217"
        )
        app = _create_test_app(service)
        client = TestClient(app)

        response = _upload_csv(client)
        detail = response.json()["detail"]

        assert detail["error_code"] == "SCHEMA_VALIDATION"
        assert "suggestion" in detail

    def test_unexpected_error_does_not_leak_internals(self) -> None:
        service = AsyncMock()
        service.process_file.side_effect = RuntimeError("database connection string: postgres://...")
        app = _create_test_app(service)
        client = TestClient(app)

        response = _upload_csv(client)
        detail = response.json()["detail"]

        assert detail["error_code"] == "INTERNAL_ERROR"
        assert "postgres" not in detail["message"]
        assert "suggestion" in detail


class TestSheetsEndpoint:
    """POST /sheets returns sheet names from an uploaded Excel file."""

    def test_returns_sheet_names_for_xlsx(self) -> None:
        service = AsyncMock()
        service.get_sheet_names = MagicMock(return_value=["Policies", "Claims", "Summary"])
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.post(
            "/sheets",
            files={"file": ("workbook.xlsx", io.BytesIO(b"data"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

        assert response.status_code == 200
        assert response.json() == {"sheets": ["Policies", "Claims", "Summary"]}

    def test_returns_empty_for_csv(self) -> None:
        service = AsyncMock()
        service.get_sheet_names = MagicMock(return_value=[])
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.post(
            "/sheets",
            files={"file": ("data.csv", io.BytesIO(b"A,B\n1,2\n"), "text/csv")},
        )

        assert response.status_code == 200
        assert response.json() == {"sheets": []}

    def test_rejects_invalid_file_type(self) -> None:
        service = AsyncMock()
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.post(
            "/sheets",
            files={"file": ("report.pdf", io.BytesIO(b"data"), "application/pdf")},
        )

        assert response.status_code == 400


class TestFileValidation:
    """Upload endpoint must reject invalid file types and oversized files."""

    @pytest.mark.parametrize(
        "filename",
        ["report.pdf", "data.json", "image.png", "script.py", "doc.txt"],
    )
    def test_rejects_non_spreadsheet_files(self, filename: str) -> None:
        service = AsyncMock()
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.post(
            "/upload",
            files={"file": (filename, io.BytesIO(b"some content"), "application/octet-stream")},
        )

        assert response.status_code == 400
        assert "file type" in response.json()["detail"].lower()

    @pytest.mark.parametrize("filename", ["data.csv", "data.xlsx", "data.xls"])
    def test_accepts_spreadsheet_extensions(self, filename: str) -> None:
        service = AsyncMock()
        service.process_file.return_value = _make_processing_result()
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.post(
            "/upload",
            files={"file": (filename, io.BytesIO(b"ID\n1\n"), "application/octet-stream")},
        )

        assert response.status_code == 200

    def test_rejects_oversized_file(self) -> None:
        service = AsyncMock()
        app = _create_test_app(service)
        client = TestClient(app)

        # 11MB file — over the 10MB limit
        big_content = b"x" * (11 * 1024 * 1024)
        response = client.post(
            "/upload",
            files={"file": ("big.csv", io.BytesIO(big_content), "text/csv")},
        )

        assert response.status_code == 400
        assert "size" in response.json()["detail"].lower()

    def test_accepts_file_under_size_limit(self) -> None:
        service = AsyncMock()
        service.process_file.return_value = _make_processing_result()
        app = _create_test_app(service)
        client = TestClient(app)

        small_content = b"ID,Value\n1,a\n"
        response = client.post(
            "/upload",
            files={"file": ("small.csv", io.BytesIO(small_content), "text/csv")},
        )

        assert response.status_code == 200


class TestCedentIdParam:
    """Upload endpoints pass cedent_id to the service."""

    def test_upload_with_cedent_id(self) -> None:
        service = AsyncMock()
        service.process_file.return_value = _make_processing_result()
        app = _create_test_app(service)
        client = TestClient(app)

        _upload_csv(client, url="/upload?cedent_id=ACME_RE")

        call_kwargs = service.process_file.call_args[1]
        assert call_kwargs["cedent_id"] == "ACME_RE"

    def test_upload_without_cedent_id(self) -> None:
        service = AsyncMock()
        service.process_file.return_value = _make_processing_result()
        app = _create_test_app(service)
        client = TestClient(app)

        _upload_csv(client)

        call_kwargs = service.process_file.call_args[1]
        assert call_kwargs["cedent_id"] is None

    def test_cedent_id_with_special_characters(self) -> None:
        service = AsyncMock()
        service.process_file.return_value = _make_processing_result()
        app = _create_test_app(service)
        client = TestClient(app)

        _upload_csv(client, url="/upload?cedent_id=ACME%20RE%2F2024")

        call_kwargs = service.process_file.call_args[1]
        assert call_kwargs["cedent_id"] == "ACME RE/2024"


class TestCorrectionsEndpoint:
    """POST /corrections stores human-verified mappings."""

    def test_post_correction_returns_201(self) -> None:
        service = AsyncMock()
        service.store_correction = MagicMock()
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.post(
            "/corrections",
            json={
                "cedent_id": "ABC",
                "corrections": [
                    {"source_header": "GWP", "target_field": "Gross_Premium"},
                ],
            },
        )

        assert response.status_code == 201

    def test_correction_stored_via_service(self) -> None:
        service = AsyncMock()
        service.store_correction = MagicMock()
        app = _create_test_app(service)
        client = TestClient(app)

        client.post(
            "/corrections",
            json={
                "cedent_id": "ABC",
                "corrections": [
                    {"source_header": "GWP", "target_field": "Gross_Premium"},
                    {"source_header": "Ccy", "target_field": "Currency"},
                ],
            },
        )

        assert service.store_correction.call_count == 2

    def test_rejects_empty_cedent_id(self) -> None:
        service = AsyncMock()
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.post(
            "/corrections",
            json={
                "cedent_id": "",
                "corrections": [
                    {"source_header": "GWP", "target_field": "Gross_Premium"},
                ],
            },
        )

        assert response.status_code == 400

    def test_rejects_empty_corrections_list(self) -> None:
        service = AsyncMock()
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.post(
            "/corrections",
            json={"cedent_id": "ABC", "corrections": []},
        )

        assert response.status_code == 400

    def test_invalid_target_field_returns_422(self) -> None:
        service = AsyncMock()
        service.store_correction = MagicMock(
            side_effect=InvalidCorrectionError("Nonexistent not in schema")
        )
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.post(
            "/corrections",
            json={
                "cedent_id": "ABC",
                "corrections": [
                    {"source_header": "GWP", "target_field": "Nonexistent"},
                ],
            },
        )

        assert response.status_code == 422
        assert "INVALID_CORRECTION" in response.json()["detail"]["error_code"]

    def test_duplicate_corrections_in_request(self) -> None:
        """Same source_header twice — last one wins, both stored."""
        service = AsyncMock()
        service.store_correction = MagicMock()
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.post(
            "/corrections",
            json={
                "cedent_id": "ABC",
                "corrections": [
                    {"source_header": "GWP", "target_field": "Gross_Premium"},
                    {"source_header": "GWP", "target_field": "Sum_Insured"},
                ],
            },
        )

        assert response.status_code == 201
        assert service.store_correction.call_count == 2
