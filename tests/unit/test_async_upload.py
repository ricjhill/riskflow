"""Tests for async upload endpoints.

POST /upload/async → accepts file, returns job_id immediately
GET /jobs/{job_id} → returns job status and result when complete
"""

import io
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.adapters.http.routes import create_router
from src.adapters.storage.job_store import InMemoryJobStore
from src.domain.model.job import Job


def _create_test_app(
    mapping_service: AsyncMock,
    job_store: InMemoryJobStore | None = None,
) -> FastAPI:
    app = FastAPI()
    store = job_store or InMemoryJobStore()
    router = create_router(mapping_service, job_store=store)
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
