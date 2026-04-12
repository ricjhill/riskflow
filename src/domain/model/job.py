"""Job model for tracking async upload lifecycle.

A Job moves through: PENDING → PROCESSING → COMPLETE or FAILED.
Invalid transitions raise ValueError.
"""

import datetime
import enum
import uuid
from typing import Any


class JobStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class Job:
    """Tracks the state of an async file processing task."""

    def __init__(
        self,
        job_id: str,
        status: JobStatus,
        *,
        filename: str | None = None,
        created_at: datetime.datetime | None = None,
    ) -> None:
        self.id = job_id
        self.status = status
        self.filename = filename
        self.created_at = created_at or datetime.datetime.now(datetime.UTC)
        self.result: dict[str, Any] | None = None
        self.error: str | None = None

    @classmethod
    def create(cls, *, filename: str | None = None) -> "Job":
        return cls(job_id=str(uuid.uuid4()), status=JobStatus.PENDING, filename=filename)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Job":
        """Reconstruct a Job from a dict (e.g. Redis JSON)."""
        job = cls(
            job_id=str(data["id"]),
            status=JobStatus(str(data["status"])),
            filename=str(data["filename"]) if data.get("filename") is not None else None,
            created_at=datetime.datetime.fromisoformat(str(data["created_at"])),
        )
        job.result = data.get("result")  # type: ignore[assignment]
        job.error = str(data["error"]) if data.get("error") is not None else None
        return job

    def to_dict(self) -> dict[str, object]:
        """Serialize to a dict for Redis persistence."""
        return {
            "id": self.id,
            "status": self.status.value,
            "filename": self.filename,
            "created_at": self.created_at.isoformat(),
            "result": self.result,
            "error": self.error,
        }

    def start(self) -> None:
        if self.status != JobStatus.PENDING:
            msg = f"Can only start a PENDING job, got {self.status.value}"
            raise ValueError(msg)
        self.status = JobStatus.PROCESSING

    def complete(self, result: dict[str, Any]) -> None:
        if self.status != JobStatus.PROCESSING:
            msg = f"Can only complete a PROCESSING job, got {self.status.value}"
            raise ValueError(msg)
        self.status = JobStatus.COMPLETE
        self.result = result

    def fail(self, error: str) -> None:
        if self.status != JobStatus.PROCESSING:
            msg = f"Can only fail a PROCESSING job, got {self.status.value}"
            raise ValueError(msg)
        self.status = JobStatus.FAILED
        self.error = error
