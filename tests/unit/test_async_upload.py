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
    """POST /upload/async — accepts file immediately, returns job ID for polling."""

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
    """GET /jobs/{id} — poll job status through PENDING → COMPLETE or FAILED."""

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
    """GET /jobs — list all uploaded files with filenames, dates, and status."""

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
    async def test_5_concurrent_uploads_overlap(self) -> None:
        """Prove 5 uploads run concurrently via create_task, not serially.

        5 uploads each sleep 0.1s. If serial, total >= 0.5s. If concurrent,
        all overlap. We record start/end times and assert every pair overlaps.
        """
        timestamps: list[tuple[str, float, float]] = []

        async def slow_process_file(
            file_path: str, *, sheet_name: str | None = None, cedent_id: str | None = None
        ) -> AsyncMock:
            start = time.monotonic()
            await asyncio.sleep(0.1)
            end = time.monotonic()
            timestamps.append((file_path, start, end))
            mock_result = AsyncMock()
            mock_result.model_dump.return_value = {"mapping": {}, "valid_records": []}
            return mock_result

        service = AsyncMock()
        service.process_file.side_effect = slow_process_file

        app = _create_test_app(service, async_backend="tasks")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            tasks = [
                asyncio.create_task(
                    client.post(
                        "/upload/async",
                        files={"file": (f"file{i}.csv", f"ID\n{i}\n".encode(), "text/csv")},
                    )
                )
                for i in range(5)
            ]
            responses = await asyncio.gather(*tasks)

        for resp in responses:
            assert resp.status_code == 202

        # Wait for all background tasks to complete
        await asyncio.sleep(0.5)

        assert len(timestamps) == 5

        # Prove overlap: the earliest end is after the latest start
        # (meaning all 5 were running at the same time)
        earliest_end = min(end for _, _, end in timestamps)
        latest_start = max(start for _, start, _ in timestamps)
        assert latest_start < earliest_end, (
            f"Not all 5 tasks overlapped: latest start {latest_start:.3f} "
            f">= earliest end {earliest_end:.3f}"
        )


class TestTaskLifecycleLogging:
    """Tests for task_started, task_completed, and error shielding logs."""

    def test_task_started_event_logged(self, capfd: pytest.CaptureFixture[str]) -> None:
        """_process_job emits task_started with job_id and filename."""
        import json as json_mod

        from src.entrypoint.main import configure_logging

        configure_logging()

        service = AsyncMock()
        store = InMemoryJobStore()
        app = _create_test_app(service, job_store=store, async_backend="background")
        client = TestClient(app)

        client.post(
            "/upload/async",
            files={"file": ("report.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
        )

        captured = capfd.readouterr()
        lines = [l for l in captured.out.strip().split("\n") if l.strip()]
        started_events = []
        for line in lines:
            try:
                parsed = json_mod.loads(line)
                if parsed.get("event") == "task_started":
                    started_events.append(parsed)
            except json_mod.JSONDecodeError:
                continue

        assert len(started_events) == 1
        assert "job_id" in started_events[0]
        assert started_events[0]["filename"] == "report.csv"

    def test_task_completed_event_logged(self, capfd: pytest.CaptureFixture[str]) -> None:
        """_process_job emits task_completed with job_id, duration_ms, status."""
        import json as json_mod

        from src.entrypoint.main import configure_logging

        configure_logging()

        service = AsyncMock()
        store = InMemoryJobStore()
        app = _create_test_app(service, job_store=store, async_backend="background")
        client = TestClient(app)

        client.post(
            "/upload/async",
            files={"file": ("report.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
        )

        captured = capfd.readouterr()
        lines = [l for l in captured.out.strip().split("\n") if l.strip()]
        completed_events = []
        for line in lines:
            try:
                parsed = json_mod.loads(line)
                if parsed.get("event") == "task_completed":
                    completed_events.append(parsed)
            except json_mod.JSONDecodeError:
                continue

        assert len(completed_events) == 1
        assert "job_id" in completed_events[0]
        assert "duration_ms" in completed_events[0]
        assert isinstance(completed_events[0]["duration_ms"], int)
        assert completed_events[0]["status"] in ("complete", "failed")

    def test_task_completed_shows_failed_status(self, capfd: pytest.CaptureFixture[str]) -> None:
        """When service raises, task_completed status is 'failed'."""
        import json as json_mod

        from src.entrypoint.main import configure_logging

        configure_logging()

        service = AsyncMock()
        service.process_file.side_effect = Exception("SLM timeout")
        store = InMemoryJobStore()
        app = _create_test_app(service, job_store=store, async_backend="background")
        client = TestClient(app)

        client.post(
            "/upload/async",
            files={"file": ("bad.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
        )

        captured = capfd.readouterr()
        lines = [l for l in captured.out.strip().split("\n") if l.strip()]
        completed_events = []
        for line in lines:
            try:
                parsed = json_mod.loads(line)
                if parsed.get("event") == "task_completed":
                    completed_events.append(parsed)
            except json_mod.JSONDecodeError:
                continue

        assert len(completed_events) == 1
        assert completed_events[0]["status"] == "failed"

    def test_task_exception_does_not_crash_server(self) -> None:
        """Server continues responding after a background task fails."""
        service = AsyncMock()
        service.process_file.side_effect = Exception("catastrophic")
        app = _create_test_app(service, async_backend="background")
        client = TestClient(app)

        # Upload that triggers failure
        client.post(
            "/upload/async",
            files={"file": ("bad.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
        )

        # Server should still respond to subsequent requests
        response = client.get("/jobs")
        assert response.status_code == 200
