"""Tests for InMemoryJobStore adapter.

InMemoryJobStore is the in-process fallback when Redis is unavailable.
All methods are async to match the JobStorePort protocol.
"""

import datetime

import pytest

from src.adapters.storage.job_store import InMemoryJobStore
from src.domain.model.job import Job, JobStatus
from src.ports.output.job_store import JobStorePort


class TestInMemoryJobStoreProtocol:
    """InMemoryJobStore satisfies JobStorePort protocol for single-process deployments."""

    def test_satisfies_job_store_port(self) -> None:
        assert isinstance(InMemoryJobStore(), JobStorePort)


class TestSaveAndGet:
    """Basic job persistence — save stores, get retrieves, updates overwrite."""

    @pytest.mark.asyncio
    async def test_save_and_retrieve_job(self) -> None:
        store = InMemoryJobStore()
        job = Job.create()
        await store.save(job)
        retrieved = await store.get(job.id)
        assert retrieved is not None
        assert retrieved.id == job.id

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self) -> None:
        store = InMemoryJobStore()
        assert await store.get("nonexistent-id") is None

    @pytest.mark.asyncio
    async def test_save_updates_existing_job(self) -> None:
        """Re-saving a job after status transition overwrites the previous state."""
        store = InMemoryJobStore()
        job = Job.create()
        await store.save(job)

        job.start()
        await store.save(job)

        retrieved = await store.get(job.id)
        assert retrieved is not None
        assert retrieved.status == JobStatus.PROCESSING


class TestListAll:
    """List all jobs sorted newest-first — for the GET /jobs endpoint."""

    @pytest.mark.asyncio
    async def test_list_all_empty(self) -> None:
        store = InMemoryJobStore()
        assert await store.list_all() == []

    @pytest.mark.asyncio
    async def test_list_all_returns_all(self) -> None:
        store = InMemoryJobStore()
        for _ in range(3):
            job = Job.create()
            await store.save(job)
        assert len(await store.list_all()) == 3

    @pytest.mark.asyncio
    async def test_list_all_newest_first(self) -> None:
        store = InMemoryJobStore()
        t1 = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        t2 = datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC)
        t3 = datetime.datetime(2026, 12, 1, tzinfo=datetime.UTC)

        job_old = Job("old", JobStatus.PENDING, created_at=t1)
        job_mid = Job("mid", JobStatus.PENDING, created_at=t2)
        job_new = Job("new", JobStatus.PENDING, created_at=t3)

        await store.save(job_mid)
        await store.save(job_old)
        await store.save(job_new)

        result = await store.list_all()
        assert [j.id for j in result] == ["new", "mid", "old"]

    @pytest.mark.asyncio
    async def test_list_all_includes_filename(self) -> None:
        store = InMemoryJobStore()
        job = Job.create(filename="report.csv")
        await store.save(job)
        jobs = await store.list_all()
        assert jobs[0].filename == "report.csv"

    @pytest.mark.asyncio
    async def test_list_all_mixed_statuses(self) -> None:
        """Jobs in all states are included in list_all()."""
        store = InMemoryJobStore()

        pending = Job.create(filename="pending.csv")
        await store.save(pending)

        complete = Job.create(filename="complete.csv")
        complete.start()
        complete.complete(result={"data": []})
        await store.save(complete)

        failed = Job.create(filename="failed.csv")
        failed.start()
        failed.fail(error="timeout")
        await store.save(failed)

        result = await store.list_all()
        statuses = {j.status for j in result}
        assert statuses == {JobStatus.PENDING, JobStatus.COMPLETE, JobStatus.FAILED}
