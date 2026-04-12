"""Tests for Job domain model.

A Job tracks the lifecycle of an async upload:
pending → processing → complete (with result) or failed (with error).
"""

import datetime

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


class TestJobMetadata:
    """Tests for filename and created_at metadata on Job."""

    def test_create_with_filename(self) -> None:
        job = Job.create(filename="report.csv")
        assert job.filename == "report.csv"

    def test_create_without_filename_defaults_to_none(self) -> None:
        job = Job.create()
        assert job.filename is None

    def test_filename_with_special_chars(self) -> None:
        """Filenames with spaces, unicode, and special chars are preserved."""
        job = Job.create(filename="Q1 bordereaux (final).xlsx")
        assert job.filename == "Q1 bordereaux (final).xlsx"
        job2 = Job.create(filename="données_réassurance.csv")
        assert job2.filename == "données_réassurance.csv"

    def test_create_sets_created_at(self) -> None:
        """created_at is a UTC datetime."""
        job = Job.create()
        assert isinstance(job.created_at, datetime.datetime)
        assert job.created_at.tzinfo is not None

    def test_created_at_close_to_now(self) -> None:
        """created_at is within 1 second of now."""
        before = datetime.datetime.now(datetime.UTC)
        job = Job.create()
        after = datetime.datetime.now(datetime.UTC)
        assert before <= job.created_at <= after

    def test_created_at_unchanged_after_start(self) -> None:
        job = Job.create()
        original = job.created_at
        job.start()
        assert job.created_at == original

    def test_created_at_unchanged_after_complete(self) -> None:
        job = Job.create()
        original = job.created_at
        job.start()
        job.complete(result={"data": []})
        assert job.created_at == original
