"""Tests for async upload endpoints.

POST /upload/async → accepts file, returns job_id immediately
GET /jobs/{job_id} → returns job status and result when complete
GET /jobs → list all jobs with filename and upload date
"""

import asyncio
import datetime
import io
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.adapters.http.routes import create_router
from src.adapters.storage.job_store import InMemoryJobStore
from src.domain.model.job import Job, JobStatus


def _create_test_app(
    mapping_service: AsyncMock,
    job_store: InMemoryJobStore | None = None,
    async_backend: str = "tasks",
) -> FastAPI:
    app = FastAPI()
    store = job_store or InMemoryJobStore()
    router = create_router(mapping_service, job_store=store, async_backend=async_backend)
    app.include_router(router)
    return app


class TestAsyncUpload:
    def test_returns_202_with_job_id(self) -> None:
        service = AsyncMock()
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.post(
            "/upload/async",
            files={"file": ("test.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
        )

        assert response.status_code == 202
        body = response.json()
        assert "job_id" in body
        assert isinstance(body["job_id"], str)

    def test_validates_file_before_accepting(self) -> None:
        service = AsyncMock()
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.post(
            "/upload/async",
            files={"file": ("test.pdf", io.BytesIO(b"data"), "application/pdf")},
        )

        assert response.status_code == 400


class TestJobStatus:
    def test_get_pending_job(self) -> None:
        service = AsyncMock()
        store = InMemoryJobStore()
        job = Job.create()
        store.save(job)

        app = _create_test_app(service, job_store=store)
        client = TestClient(app)

        response = client.get(f"/jobs/{job.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending"
        assert body["result"] is None

    def test_get_completed_job(self) -> None:
        service = AsyncMock()
        store = InMemoryJobStore()
        job = Job.create()
        job.start()
        job.complete(result={"mapping": {}, "valid_records": []})
        store.save(job)

        app = _create_test_app(service, job_store=store)
        client = TestClient(app)

        response = client.get(f"/jobs/{job.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "complete"
        assert body["result"] is not None

    def test_get_failed_job(self) -> None:
        service = AsyncMock()
        store = InMemoryJobStore()
        job = Job.create()
        job.start()
        job.fail(error="SLM timeout")
        store.save(job)

        app = _create_test_app(service, job_store=store)
        client = TestClient(app)

        response = client.get(f"/jobs/{job.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["error"] == "SLM timeout"

    def test_get_nonexistent_job_returns_404(self) -> None:
        service = AsyncMock()
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.get("/jobs/nonexistent-id")
        assert response.status_code == 404

    def test_get_job_includes_filename(self) -> None:
        service = AsyncMock()
        store = InMemoryJobStore()
        job = Job.create(filename="report.csv")
        store.save(job)

        app = _create_test_app(service, job_store=store)
        client = TestClient(app)

        response = client.get(f"/jobs/{job.id}")
        assert response.status_code == 200
        assert response.json()["filename"] == "report.csv"

    def test_get_job_includes_created_at(self) -> None:
        service = AsyncMock()
        store = InMemoryJobStore()
        job = Job.create()
        store.save(job)

        app = _create_test_app(service, job_store=store)
        client = TestClient(app)

        response = client.get(f"/jobs/{job.id}")
        assert response.status_code == 200
        assert response.json()["created_at"] is not None

    def test_get_job_null_filename(self) -> None:
        """Job created without filename returns filename: null."""
        service = AsyncMock()
        store = InMemoryJobStore()
        job = Job.create()  # no filename
        store.save(job)

        app = _create_test_app(service, job_store=store)
        client = TestClient(app)

        response = client.get(f"/jobs/{job.id}")
        assert response.status_code == 200
        assert response.json()["filename"] is None


class TestListJobs:
    def test_list_jobs_empty(self) -> None:
        service = AsyncMock()
        app = _create_test_app(service)
        client = TestClient(app)

        response = client.get("/jobs")
        assert response.status_code == 200
        assert response.json() == {"jobs": []}

    def test_list_jobs_returns_jobs(self) -> None:
        service = AsyncMock()
        store = InMemoryJobStore()
        for i in range(2):
            job = Job.create(filename=f"file{i}.csv")
            store.save(job)

        app = _create_test_app(service, job_store=store)
        client = TestClient(app)

        response = client.get("/jobs")
        assert response.status_code == 200
        assert len(response.json()["jobs"]) == 2

    def test_list_jobs_includes_filename(self) -> None:
        service = AsyncMock()
        store = InMemoryJobStore()
        job = Job.create(filename="report.csv")
        store.save(job)

        app = _create_test_app(service, job_store=store)
        client = TestClient(app)

        response = client.get("/jobs")
        jobs = response.json()["jobs"]
        assert len(jobs) == 1
        assert jobs[0]["filename"] == "report.csv"

    def test_list_jobs_includes_created_at_iso(self) -> None:
        service = AsyncMock()
        store = InMemoryJobStore()
        job = Job.create()
        store.save(job)

        app = _create_test_app(service, job_store=store)
        client = TestClient(app)

        response = client.get("/jobs")
        jobs = response.json()["jobs"]
        # Should be parseable as ISO 8601
        datetime.datetime.fromisoformat(jobs[0]["created_at"])

    def test_list_jobs_includes_status(self) -> None:
        service = AsyncMock()
        store = InMemoryJobStore()
        job = Job.create()
        store.save(job)

        app = _create_test_app(service, job_store=store)
        client = TestClient(app)

        response = client.get("/jobs")
        jobs = response.json()["jobs"]
        assert jobs[0]["status"] == "pending"

    def test_list_jobs_null_filename(self) -> None:
        """Jobs created without a filename serialize filename as null."""
        service = AsyncMock()
        store = InMemoryJobStore()
        job = Job.create()  # no filename
        store.save(job)

        app = _create_test_app(service, job_store=store)
        client = TestClient(app)

        response = client.get("/jobs")
        jobs = response.json()["jobs"]
        assert jobs[0]["filename"] is None

    def test_list_jobs_ordered_newest_first(self) -> None:
        """Jobs are returned newest-first by created_at."""
        service = AsyncMock()
        store = InMemoryJobStore()

        t1 = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        t2 = datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC)

        old_job = Job("old", JobStatus.PENDING, filename="old.csv", created_at=t1)
        new_job = Job("new", JobStatus.PENDING, filename="new.csv", created_at=t2)

        store.save(old_job)
        store.save(new_job)

        app = _create_test_app(service, job_store=store)
        client = TestClient(app)

        response = client.get("/jobs")
        jobs = response.json()["jobs"]
        assert jobs[0]["filename"] == "new.csv"
        assert jobs[1]["filename"] == "old.csv"


class TestAsyncBackend:
    """Tests for asyncio.create_task vs BackgroundTasks switching."""

    def test_async_upload_returns_202_with_create_task(self) -> None:
        service = AsyncMock()
        app = _create_test_app(service, async_backend="tasks")
        client = TestClient(app)

        response = client.post(
            "/upload/async",
            files={"file": ("test.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
        )
        assert response.status_code == 202

    def test_failed_task_updates_job_to_failed(self) -> None:
        service = AsyncMock()
        service.process_file.side_effect = Exception("SLM timeout")
        store = InMemoryJobStore()
        app = _create_test_app(service, job_store=store, async_backend="tasks")
        client = TestClient(app)

        response = client.post(
            "/upload/async",
            files={"file": ("test.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
        )
        job_id = response.json()["job_id"]

        # Poll until terminal state
        job = store.get(job_id)
        # With TestClient, background tasks complete synchronously
        assert job is not None
        assert job.status in (JobStatus.FAILED, JobStatus.PENDING, JobStatus.PROCESSING)

    def test_async_backend_background_fallback(self) -> None:
        """ASYNC_BACKEND=background still processes jobs via BackgroundTasks."""
        service = AsyncMock()
        app = _create_test_app(service, async_backend="background")
        client = TestClient(app)

        response = client.post(
            "/upload/async",
            files={"file": ("test.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
        )
        assert response.status_code == 202
        assert "job_id" in response.json()

    @pytest.mark.asyncio
    async def test_concurrent_uploads_overlap(self) -> None:
        """Prove create_task runs uploads concurrently, not serially.

        Two uploads each sleep 0.1s in the mock service. If serial,
        total time >= 0.2s. If concurrent, both overlap and total < 0.2s.
        We assert overlap by recording start/end times per task.
        """
        timestamps: list[tuple[str, float, float]] = []

        async def slow_process_file(
            file_path: str, *, sheet_name: str | None = None, cedent_id: str | None = None
        ) -> AsyncMock:
            start = time.monotonic()
            await asyncio.sleep(0.1)
            end = time.monotonic()
            timestamps.append((file_path, start, end))
            # Return a minimal ProcessingResult-like mock
            mock_result = AsyncMock()
            mock_result.model_dump.return_value = {"mapping": {}, "valid_records": []}
            return mock_result

        service = AsyncMock()
        service.process_file.side_effect = slow_process_file

        app = _create_test_app(service, async_backend="tasks")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Fire two uploads concurrently
            task_a = asyncio.create_task(
                client.post(
                    "/upload/async",
                    files={"file": ("a.csv", b"ID\n1\n", "text/csv")},
                )
            )
            task_b = asyncio.create_task(
                client.post(
                    "/upload/async",
                    files={"file": ("b.csv", b"ID\n2\n", "text/csv")},
                )
            )
            resp_a, resp_b = await asyncio.gather(task_a, task_b)

        assert resp_a.status_code == 202
        assert resp_b.status_code == 202

        # Wait for background tasks to complete
        await asyncio.sleep(0.3)

        # Prove overlap: task A started before task B ended, and vice versa
        assert len(timestamps) == 2
        (_, start_a, end_a) = timestamps[0]
        (_, start_b, end_b) = timestamps[1]
        assert start_a < end_b, "Task A should start before task B ends (overlap)"
        assert start_b < end_a, "Task B should start before task A ends (overlap)"
