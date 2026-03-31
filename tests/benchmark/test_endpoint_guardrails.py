"""Endpoint-level TTFB (Time To First Byte) guardrail tests.

These tests measure the full HTTP request lifecycle through FastAPI's
TestClient: ASGI routing, middleware, file parsing, Pydantic validation,
and response serialization. The SLM mapper is mocked (AsyncMock returns
instantly) so we measure everything EXCEPT the external API call.

Budgets are 10x typical, matching the convention in test_perf_guardrails.py.
They catch regressions like:
- Accidental middleware that blocks on I/O
- O(n^2) response serialization
- Full-file re-read when only headers were needed
"""

import csv
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.adapters.http.routes import create_router
from src.adapters.parsers.ingestor import PolarsIngestor
from src.adapters.storage.job_store import InMemoryJobStore
from src.domain.model.schema import ColumnMapping, MappingResult
from src.domain.service.mapping_service import MappingService

from tests.benchmark.conftest import Timer


def _make_mapping_result() -> MappingResult:
    return MappingResult(
        mappings=[
            ColumnMapping(
                source_header="Policy No.",
                target_field="Policy_ID",
                confidence=0.95,
            ),
            ColumnMapping(
                source_header="GWP",
                target_field="Gross_Premium",
                confidence=0.95,
            ),
        ],
        unmapped_headers=["Extra"],
    )


@pytest.fixture
def client() -> TestClient:
    """TestClient with real CSV parsing but mocked SLM."""
    mapper = AsyncMock()
    mapper.map_headers.return_value = _make_mapping_result()
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

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)
    return TestClient(app)


def _write_csv(tmp_path: Path, rows: int = 50) -> Path:
    """Write a CSV with the given number of rows."""
    csv_path = tmp_path / "ttfb_test.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Policy No.", "GWP", "Extra"])
        for i in range(rows):
            writer.writerow([f"POL-{i:04d}", 50000 + i, "x"])
    return csv_path


# ---------------------------------------------------------------------------
# TTFB Guardrails
# ---------------------------------------------------------------------------
@pytest.mark.perf_guardrail
class TestEndpointTTFBGuardrails:
    """HTTP endpoint response time guardrails.

    Each test hits an endpoint via TestClient and asserts the full
    request/response cycle completes within budget.
    """

    def test_health_under_50ms(self, client: TestClient) -> None:
        """GET /health — zero business logic, pure ASGI baseline."""
        # Warm-up: first request initializes ASGI middleware
        client.get("/health")

        with Timer() as t:
            resp = client.get("/health")

        assert resp.status_code == 200
        assert t.elapsed_ms < 50, f"/health took {t.elapsed_ms:.1f}ms (budget: 50ms)"

    def test_schemas_under_50ms(self, client: TestClient) -> None:
        """GET /schemas — in-memory dict lookup."""
        client.get("/schemas")

        with Timer() as t:
            resp = client.get("/schemas")

        assert resp.status_code == 200
        assert t.elapsed_ms < 50, f"/schemas took {t.elapsed_ms:.1f}ms (budget: 50ms)"

    def test_upload_csv_under_500ms(self, client: TestClient, tmp_path: Path) -> None:
        """POST /upload — real CSV parsing + mocked SLM + row validation.

        Budget covers: file save to temp, Polars CSV read, header
        extraction, preview read, AsyncMock mapper call, Pydantic
        validation of 50 rows, response serialization.
        """
        csv_path = _write_csv(tmp_path)

        with open(csv_path, "rb") as f:
            with Timer() as t:
                resp = client.post(
                    "/upload",
                    files={"file": ("test.csv", f, "text/csv")},
                )

        assert resp.status_code == 200
        assert t.elapsed_ms < 500, f"/upload took {t.elapsed_ms:.1f}ms (budget: 500ms)"

    def test_upload_async_enqueue_under_200ms(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """POST /upload/async — measures enqueue time only.

        TestClient normally runs BackgroundTasks synchronously, which
        would inflate the measurement. We patch add_task to a no-op
        so only the enqueue (save job + return 202) is timed.
        """
        csv_path = _write_csv(tmp_path, rows=10)

        with open(csv_path, "rb") as f:
            with patch("src.adapters.http.routes.BackgroundTasks.add_task"):
                with Timer() as t:
                    resp = client.post(
                        "/upload/async",
                        files={"file": ("test.csv", f, "text/csv")},
                    )

        assert resp.status_code == 202
        assert t.elapsed_ms < 200, (
            f"/upload/async enqueue took {t.elapsed_ms:.1f}ms (budget: 200ms)"
        )

    def test_job_status_under_50ms(self, client: TestClient, tmp_path: Path) -> None:
        """GET /jobs/{id} — in-memory dict lookup after creating a job."""
        csv_path = _write_csv(tmp_path, rows=5)

        # Create a job first
        with open(csv_path, "rb") as f:
            post_resp = client.post(
                "/upload/async",
                files={"file": ("test.csv", f, "text/csv")},
            )
        job_id = post_resp.json()["job_id"]

        with Timer() as t:
            resp = client.get(f"/jobs/{job_id}")

        assert resp.status_code == 200
        assert t.elapsed_ms < 50, (
            f"/jobs/{{id}} took {t.elapsed_ms:.1f}ms (budget: 50ms)"
        )
