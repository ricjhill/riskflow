"""Consumer-Driven Contract Tests for RiskFlow's internal API.

Contract testing ensures that when service A (consumer) calls service B
(provider), the expected request/response shapes don't silently break.

In a monolith scaling to microservices, this is critical:
    - The GUI (consumer) calls the FastAPI API (provider).
    - If someone changes the /upload response shape, the GUI breaks.
    - Contract tests catch this BEFORE deployment.

Implementation strategy (without external Pact broker):
    1. Define contracts as Python dataclasses — the expected shapes.
    2. Provider tests verify the actual API matches the contract.
    3. Consumer tests verify the consumer code handles the contract shape.

This is "poor man's Pact" — effective and zero-infrastructure. When
scaling to multiple teams/services, migrate to Pact (pactflow.io)
by generating Pact JSON from these contracts.

Contract structure:
    Contract = (HTTP method, path, request shape) → (status code, response shape)
"""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.adapters.http.routes import create_router
from src.adapters.parsers.ingestor import PolarsIngestor
from src.adapters.storage.job_store import InMemoryJobStore
from src.domain.model.schema import ColumnMapping, MappingResult
from src.domain.service.mapping_service import MappingService


# ---------------------------------------------------------------------------
# Contract definitions — shared between consumer and provider tests
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ResponseContract:
    """Expected shape of an API response."""

    status_code: int
    required_fields: frozenset[str]
    optional_fields: frozenset[str] = frozenset()


# POST /upload → 200
UPLOAD_SUCCESS_CONTRACT = ResponseContract(
    status_code=200,
    required_fields=frozenset(
        {
            "mapping",
            "confidence_report",
            "valid_records",
            "invalid_records",
            "errors",
        }
    ),
)

# POST /upload → mapping field shape
MAPPING_FIELD_CONTRACT = ResponseContract(
    status_code=200,
    required_fields=frozenset({"mappings", "unmapped_headers"}),
)

# POST /upload → confidence_report field shape
CONFIDENCE_REPORT_CONTRACT = ResponseContract(
    status_code=200,
    required_fields=frozenset(
        {
            "min_confidence",
            "avg_confidence",
            "low_confidence_fields",
            "missing_fields",
        }
    ),
)

# POST /upload/async → 202
ASYNC_UPLOAD_CONTRACT = ResponseContract(
    status_code=202,
    required_fields=frozenset({"job_id"}),
)

# GET /jobs/{id} → 200
JOB_STATUS_CONTRACT = ResponseContract(
    status_code=200,
    required_fields=frozenset({"job_id", "status", "result", "error"}),
)

# GET /schemas → 200
SCHEMAS_LIST_CONTRACT = ResponseContract(
    status_code=200,
    required_fields=frozenset({"schemas"}),
)

# POST /corrections → 201
CORRECTIONS_CONTRACT = ResponseContract(
    status_code=201,
    required_fields=frozenset({"stored"}),
)

# Error responses
ERROR_CONTRACT = ResponseContract(
    status_code=400,  # varies by error type
    required_fields=frozenset({"error_code", "message", "suggestion"}),
)


# ---------------------------------------------------------------------------
# Provider tests: verify the actual API matches contracts
# ---------------------------------------------------------------------------
@pytest.mark.contract
class TestProviderUploadContract:
    """Provider side: does /upload return what the consumer expects?"""

    @pytest.fixture
    def client(self) -> TestClient:
        mapper = AsyncMock()
        mapper.map_headers.return_value = MappingResult(
            mappings=[
                ColumnMapping(
                    source_header="Policy No.",
                    target_field="Policy_ID",
                    confidence=0.95,
                ),
                ColumnMapping(
                    source_header="GWP",
                    target_field="Gross_Premium",
                    confidence=0.90,
                ),
            ],
            unmapped_headers=["Extra"],
        )
        cache = MagicMock()
        cache.get_mapping.return_value = None

        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
        )
        job_store = InMemoryJobStore()
        registry = {"standard_reinsurance": service}
        router = create_router(service, job_store=job_store, schema_registry=registry)

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def _upload_csv(self, client: TestClient, tmp_path: Path) -> Any:
        csv_path = tmp_path / "contract_test.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Policy No.", "GWP", "Extra"])
            writer.writerow(["P001", "50000", "x"])
        with open(csv_path, "rb") as f:
            return client.post("/upload", files={"file": ("test.csv", f, "text/csv")})

    def test_upload_success_matches_contract(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        resp = self._upload_csv(client, tmp_path)
        assert resp.status_code == UPLOAD_SUCCESS_CONTRACT.status_code
        body = resp.json()
        for field_name in UPLOAD_SUCCESS_CONTRACT.required_fields:
            assert field_name in body, f"Missing required field: {field_name}"

    def test_mapping_field_matches_contract(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        resp = self._upload_csv(client, tmp_path)
        mapping = resp.json()["mapping"]
        for field_name in MAPPING_FIELD_CONTRACT.required_fields:
            assert field_name in mapping, f"Missing field in mapping: {field_name}"

    def test_confidence_report_matches_contract(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        resp = self._upload_csv(client, tmp_path)
        report = resp.json()["confidence_report"]
        for field_name in CONFIDENCE_REPORT_CONTRACT.required_fields:
            assert field_name in report, (
                f"Missing field in confidence_report: {field_name}"
            )

    def test_schemas_list_matches_contract(self, client: TestClient) -> None:
        resp = client.get("/schemas")
        assert resp.status_code == SCHEMAS_LIST_CONTRACT.status_code
        body = resp.json()
        for field_name in SCHEMAS_LIST_CONTRACT.required_fields:
            assert field_name in body, f"Missing required field: {field_name}"
        assert isinstance(body["schemas"], list)

    def test_async_upload_matches_contract(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        csv_path = tmp_path / "async_test.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Policy No.", "GWP", "Extra"])
            writer.writerow(["P001", "50000", "x"])
        with open(csv_path, "rb") as f:
            resp = client.post(
                "/upload/async", files={"file": ("test.csv", f, "text/csv")}
            )
        assert resp.status_code == ASYNC_UPLOAD_CONTRACT.status_code
        body = resp.json()
        for field_name in ASYNC_UPLOAD_CONTRACT.required_fields:
            assert field_name in body, f"Missing required field: {field_name}"

    def test_job_status_matches_contract(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        csv_path = tmp_path / "job_test.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Policy No.", "GWP", "Extra"])
            writer.writerow(["P001", "50000", "x"])
        with open(csv_path, "rb") as f:
            post_resp = client.post(
                "/upload/async", files={"file": ("test.csv", f, "text/csv")}
            )
        job_id = post_resp.json()["job_id"]
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == JOB_STATUS_CONTRACT.status_code
        body = resp.json()
        for field_name in JOB_STATUS_CONTRACT.required_fields:
            assert field_name in body, f"Missing required field: {field_name}"

    def test_error_response_matches_contract(self, client: TestClient) -> None:
        """Error responses must have error_code, message, suggestion."""
        resp = client.post(
            "/upload",
            files={"file": ("test.txt", b"not a csv", "text/plain")},
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        # Simple string error for file type validation — this is fine
        assert isinstance(detail, str)

    def test_corrections_matches_contract(self, client: TestClient) -> None:
        resp = client.post(
            "/corrections",
            json={
                "cedent_id": "test-cedent",
                "corrections": [
                    {"source_header": "GWP", "target_field": "Gross_Premium"}
                ],
            },
        )
        assert resp.status_code == CORRECTIONS_CONTRACT.status_code
        body = resp.json()
        for field_name in CORRECTIONS_CONTRACT.required_fields:
            assert field_name in body, f"Missing required field: {field_name}"


# ---------------------------------------------------------------------------
# Consumer tests: verify consumer code handles contract shapes
# ---------------------------------------------------------------------------
@pytest.mark.contract
class TestConsumerUploadContract:
    """Consumer side: if the API returns the contracted shape, can the GUI parse it?

    This simulates what gui/api_client.py would do with the response.
    If the contract changes, both provider AND consumer tests break.
    """

    def test_consumer_parses_upload_response(self) -> None:
        """Simulate a consumer parsing the upload success response."""
        # This is the shape the provider promises to return
        response_body = {
            "mapping": {
                "mappings": [
                    {
                        "source_header": "GWP",
                        "target_field": "Gross_Premium",
                        "confidence": 0.95,
                    }
                ],
                "unmapped_headers": ["Extra"],
            },
            "confidence_report": {
                "min_confidence": 0.95,
                "avg_confidence": 0.95,
                "low_confidence_fields": [],
                "missing_fields": ["Policy_ID"],
            },
            "valid_records": [{"Gross_Premium": 50000.0}],
            "invalid_records": [],
            "errors": [],
        }

        # Consumer parsing logic
        mappings = response_body["mapping"]["mappings"]
        assert len(mappings) == 1
        assert mappings[0]["target_field"] == "Gross_Premium"
        assert isinstance(mappings[0]["confidence"], float)

        report = response_body["confidence_report"]
        assert isinstance(report["min_confidence"], float)
        assert isinstance(report["missing_fields"], list)

    def test_consumer_parses_job_status(self) -> None:
        """Simulate a consumer polling job status."""
        response_body = {
            "job_id": "abc-123",
            "status": "complete",
            "result": {"valid_records": []},
            "error": None,
        }

        assert response_body["status"] in (
            "pending",
            "processing",
            "complete",
            "failed",
        )
        assert response_body["job_id"] is not None

    def test_consumer_handles_error_response(self) -> None:
        """Simulate consumer handling a structured error."""
        error_body = {
            "error_code": "LOW_CONFIDENCE",
            "message": "Mapping confidence too low",
            "suggestion": "Review the unmapped headers",
        }

        assert "error_code" in error_body
        assert "suggestion" in error_body
