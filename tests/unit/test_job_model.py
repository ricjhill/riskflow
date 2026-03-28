"""Tests for Job domain model.

A Job tracks the lifecycle of an async upload:
pending → processing → complete (with result) or failed (with error).
"""

import pytest

from src.domain.model.job import Job, JobStatus


class TestJobCreation:
    def test_new_job_is_pending(self) -> None:
        job = Job.create()
        assert job.status == JobStatus.PENDING

    def test_new_job_has_unique_id(self) -> None:
        job1 = Job.create()
        job2 = Job.create()
        assert job1.id != job2.id

    def test_new_job_has_no_result(self) -> None:
        job = Job.create()
        assert job.result is None
        assert job.error is None


class TestJobTransitions:
    def test_start_processing(self) -> None:
        job = Job.create()
        job.start()
        assert job.status == JobStatus.PROCESSING

    def test_complete_with_result(self) -> None:
        job = Job.create()
        job.start()
        job.complete(result={"mapping": {}, "valid_records": []})
        assert job.status == JobStatus.COMPLETE
        assert job.result is not None

    def test_fail_with_error(self) -> None:
        job = Job.create()
        job.start()
        job.fail(error="SLM timeout")
        assert job.status == JobStatus.FAILED
        assert job.error == "SLM timeout"

    def test_cannot_complete_pending_job(self) -> None:
        job = Job.create()
        with pytest.raises(ValueError, match="PROCESSING"):
            job.complete(result={})

    def test_cannot_fail_pending_job(self) -> None:
        job = Job.create()
        with pytest.raises(ValueError, match="PROCESSING"):
            job.fail(error="oops")

    def test_cannot_start_completed_job(self) -> None:
        job = Job.create()
        job.start()
        job.complete(result={})
        with pytest.raises(ValueError, match="PENDING"):
            job.start()
