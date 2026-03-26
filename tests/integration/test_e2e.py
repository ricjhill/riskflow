"""End-to-end integration test: upload CSV → get mapped results.

Uses the real app with real PolarsIngestor and NullCache, but mocks
the GroqMapper to avoid real API calls. This proves that all the
pieces connect — file upload, parsing, service orchestration, error
mapping, and response serialization.
"""

import io
import json
from unittest.mock import AsyncMock, patch

import pytest
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
        assert "mappings" in body
        assert "unmapped_headers" in body

    def test_maps_all_known_headers(self, client: TestClient) -> None:
        response = client.post(
            "/upload",
            files={
                "file": ("bordereaux.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )

        body = response.json()
        mapped_targets = {m["target_field"] for m in body["mappings"]}
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
        assert "Notes" in body["unmapped_headers"]

    def test_confidence_scores_are_present(self, client: TestClient) -> None:
        response = client.post(
            "/upload",
            files={
                "file": ("bordereaux.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")
            },
        )

        body = response.json()
        for mapping in body["mappings"]:
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
        assert len(body["mappings"]) == 1
        assert body["mappings"][0]["target_field"] == "Gross_Premium"

    def test_all_unmapped_headers(self, client: TestClient) -> None:
        csv = "Foo,Bar,Baz\n1,2,3\n"
        response = client.post(
            "/upload",
            files={"file": ("unknown.csv", io.BytesIO(csv.encode()), "text/csv")},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["mappings"]) == 0
        assert set(body["unmapped_headers"]) == {"Foo", "Bar", "Baz"}

    def test_empty_csv_with_headers_only(self, client: TestClient) -> None:
        csv = "Policy No.,GWP\n"
        response = client.post(
            "/upload",
            files={"file": ("empty.csv", io.BytesIO(csv.encode()), "text/csv")},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["mappings"]) == 2
