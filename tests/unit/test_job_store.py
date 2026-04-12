"""Tests for InMemoryJobStore adapter."""

import datetime

from src.adapters.storage.job_store import InMemoryJobStore
from src.domain.model.job import Job, JobStatus
from src.ports.output.job_store import JobStorePort


class TestInMemoryJobStoreProtocol:
    def test_satisfies_job_store_port(self) -> None:
        assert isinstance(InMemoryJobStore(), JobStorePort)


class TestSaveAndGet:
    def test_save_and_retrieve_job(self) -> None:
        store = InMemoryJobStore()
        job = Job.create()
        store.save(job)
        retrieved = store.get(job.id)
        assert retrieved is not None
        assert retrieved.id == job.id

    def test_get_nonexistent_returns_none(self) -> None:
        store = InMemoryJobStore()
        assert store.get("nonexistent-id") is None

    def test_save_updates_existing_job(self) -> None:
        store = InMemoryJobStore()
        job = Job.create()
        store.save(job)

        job.start()
        store.save(job)

        retrieved = store.get(job.id)
        assert retrieved is not None
        assert retrieved.status == JobStatus.PROCESSING


class TestListAll:
    def test_list_all_empty(self) -> None:
        store = InMemoryJobStore()
        assert store.list_all() == []

    def test_list_all_returns_all(self) -> None:
        store = InMemoryJobStore()
        for _ in range(3):
            job = Job.create()
            store.save(job)
        assert len(store.list_all()) == 3

    def test_list_all_newest_first(self) -> None:
        store = InMemoryJobStore()
        t1 = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        t2 = datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC)
        t3 = datetime.datetime(2026, 12, 1, tzinfo=datetime.UTC)

        job_old = Job("old", JobStatus.PENDING, created_at=t1)
        job_mid = Job("mid", JobStatus.PENDING, created_at=t2)
        job_new = Job("new", JobStatus.PENDING, created_at=t3)

        # Save in random order
        store.save(job_mid)
        store.save(job_old)
        store.save(job_new)

        result = store.list_all()
        assert [j.id for j in result] == ["new", "mid", "old"]

    def test_list_all_includes_filename(self) -> None:
        store = InMemoryJobStore()
        job = Job.create(filename="report.csv")
        store.save(job)
        assert store.list_all()[0].filename == "report.csv"

    def test_list_all_mixed_statuses(self) -> None:
        """Jobs in all states are included in list_all()."""
        store = InMemoryJobStore()

        pending = Job.create(filename="pending.csv")
        store.save(pending)

        complete = Job.create(filename="complete.csv")
        complete.start()
        complete.complete(result={"data": []})
        store.save(complete)

        failed = Job.create(filename="failed.csv")
        failed.start()
        failed.fail(error="timeout")
        store.save(failed)

        result = store.list_all()
        statuses = {j.status for j in result}
        assert statuses == {JobStatus.PENDING, JobStatus.COMPLETE, JobStatus.FAILED}
