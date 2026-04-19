"""Output port for job persistence."""

from typing import Protocol, runtime_checkable

from src.domain.model.job import Job


@runtime_checkable
class JobStorePort(Protocol):
    """How the domain persists and retrieves async jobs."""

    async def save(self, job: Job) -> None: ...

    async def get(self, job_id: str) -> Job | None: ...

    async def list_all(self) -> list[Job]: ...
