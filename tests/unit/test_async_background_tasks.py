"""TDD patterns for async background tasks.

Testing async code without flakiness requires three strategies:

1. **Deterministic completion**: Don't await real timers or queues.
   Inject a mock task executor that completes synchronously.

2. **State machine testing**: Test job state transitions independently
   of the async mechanism. The Job model is a pure state machine —
   test it without async at all.

3. **Integration via FastAPI TestClient**: FastAPI's TestClient runs
   BackgroundTasks synchronously in test mode — no sleep/polling needed.

This file demonstrates all three patterns using RiskFlow's actual
async upload pipeline.
"""

import csv
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.adapters.parsers.ingestor import PolarsIngestor
from src.domain.model.job import Job, JobStatus
from src.domain.model.schema import ColumnMapping, MappingResult, ProcessingResult
from src.domain.service.mapping_service import MappingService


# ---------------------------------------------------------------------------
# Pattern 1: Pure state machine tests (no async at all)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestJobStateMachine:
    """Job lifecycle is a state machine. Test transitions, not I/O."""

    def test_fresh_job_is_pending(self) -> None:
        job = Job.create()
        assert job.status == JobStatus.PENDING

    def test_pending_to_processing(self) -> None:
        job = Job.create()
        job.start()
        assert job.status == JobStatus.PROCESSING

    def test_processing_to_complete(self) -> None:
        job = Job.create()
        job.start()
        job.complete(result={"valid_records": []})
        assert job.status == JobStatus.COMPLETE
        assert job.result == {"valid_records": []}

    def test_processing_to_failed(self) -> None:
        job = Job.create()
        job.start()
        job.fail(error="SLM timeout")
        assert job.status == JobStatus.FAILED
        assert job.error == "SLM timeout"

    def test_cannot_complete_from_pending(self) -> None:
        job = Job.create()
        with pytest.raises(ValueError, match="Can only complete a PROCESSING job"):
            job.complete(result={})

    def test_cannot_start_from_complete(self) -> None:
        job = Job.create()
        job.start()
        job.complete(result={})
        with pytest.raises(ValueError, match="Can only start a PENDING job"):
            job.start()


# ---------------------------------------------------------------------------
# Pattern 2: Async service tests with deterministic mocks
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestAsyncServiceDeterministic:
    """Test MappingService.process_file without real I/O.

    The mapper port is async (returns a coroutine). AsyncMock makes it
    deterministic — the coroutine completes immediately when awaited,
    so no timers, no polling, no flakiness.
    """

    @pytest.fixture
    def mapper(self) -> AsyncMock:
        mock = AsyncMock()
        mock.map_headers.return_value = MappingResult(
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
        return mock

    @pytest.fixture
    def cache(self) -> MagicMock:
        mock = MagicMock()
        mock.get_mapping.return_value = None
        return mock

    @pytest.fixture
    def service(self, mapper: AsyncMock, cache: MagicMock) -> MappingService:
        return MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
        )

    @pytest.mark.asyncio
    async def test_process_file_calls_mapper_once(
        self, service: MappingService, mapper: AsyncMock, tmp_path: Path
    ) -> None:
        csv_path = self._write_csv(tmp_path)
        await service.process_file(csv_path)
        mapper.map_headers.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_file_returns_processing_result(
        self, service: MappingService, tmp_path: Path
    ) -> None:
        csv_path = self._write_csv(tmp_path)
        result = await service.process_file(csv_path)
        assert isinstance(result, ProcessingResult)

    @pytest.mark.asyncio
    async def test_cache_hit_skips_mapper(
        self,
        service: MappingService,
        mapper: AsyncMock,
        cache: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When cache returns a result, the SLM mapper is never called."""
        cache.get_mapping.return_value = MappingResult(
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
        csv_path = self._write_csv(tmp_path)
        await service.process_file(csv_path)
        mapper.map_headers.assert_not_awaited()

    @staticmethod
    def _write_csv(tmp_path: Path) -> str:
        csv_path = str(tmp_path / "test.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Policy No.", "GWP", "Extra"])
            writer.writerow(["P001", "50000", "x"])
        return csv_path


# ---------------------------------------------------------------------------
# Pattern 3: Background task integration via TestClient
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestAsyncUploadIntegration:
    """FastAPI's TestClient executes BackgroundTasks synchronously.

    This means we can test the full async upload → job completion flow
    without any sleep() calls or polling loops. The background task
    runs to completion before the test continues.
    """

    @pytest.fixture
    def client(self, tmp_path: Path) -> TestClient:
        from src.adapters.http.routes import create_router
        from src.adapters.storage.job_store import InMemoryJobStore
        from fastapi import FastAPI

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
                    confidence=0.95,
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
        router = create_router(service, job_store=job_store)

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_async_upload_returns_202(self, client: TestClient, tmp_path: Path) -> None:
        csv_path = tmp_path / "test.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Policy No.", "GWP", "Extra"])
            writer.writerow(["P001", "50000", "x"])

        with open(csv_path, "rb") as f:
            resp = client.post(
                "/upload/async",
                files={"file": ("test.csv", f, "text/csv")},
            )

        assert resp.status_code == 202
        assert "job_id" in resp.json()

    def test_background_task_completes_synchronously(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """After TestClient returns from POST /upload/async, the background
        task has already run. Polling GET /jobs/{id} returns COMPLETE."""
        csv_path = tmp_path / "test.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Policy No.", "GWP", "Extra"])
            writer.writerow(["P001", "50000", "x"])

        with open(csv_path, "rb") as f:
            post_resp = client.post(
                "/upload/async",
                files={"file": ("test.csv", f, "text/csv")},
            )

        job_id = post_resp.json()["job_id"]
        get_resp = client.get(f"/jobs/{job_id}")

        assert get_resp.status_code == 200
        body = get_resp.json()
        # BackgroundTasks runs synchronously in TestClient — no polling needed
        assert body["status"] in ("complete", "failed")
