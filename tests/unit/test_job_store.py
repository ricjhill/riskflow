"""Tests for InMemoryJobStore adapter."""


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
