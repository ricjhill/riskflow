"""In-memory job store for async upload tracking."""

from src.domain.model.job import Job


class InMemoryJobStore:
    """Stores jobs in a dict. Suitable for single-process deployments.

    For multi-process or persistent job tracking, a Redis-backed
    implementation should be used instead.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def save(self, job: Job) -> None:
        self._jobs[job.id] = job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)
