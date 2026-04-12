"""Tests for RedisJobStore adapter.

All tests mock the Redis client — no real Redis connection.
Tests follow the pattern established in test_cache_adapter.py
and test_session_store (not yet in unit/).
"""

import json
from unittest.mock import MagicMock

from src.adapters.storage.job_store import RedisJobStore
from src.domain.model.job import Job
from src.ports.output.job_store import JobStorePort


class TestRedisJobStoreProtocol:
    def test_satisfies_job_store_port(self) -> None:
        assert isinstance(RedisJobStore(client=MagicMock()), JobStorePort)


class TestSaveAndGet:
    def test_save_and_get_roundtrip(self) -> None:
        client = MagicMock()
        store = RedisJobStore(client=client)
        job = Job.create(filename="test.csv")

        # Capture what save writes
        store.save(job)
        call_args = client.setex.call_args
        key = call_args[0][0]
        stored_json = call_args[0][2]

        # Feed it back via get
        client.get.return_value = (
            stored_json.encode() if isinstance(stored_json, str) else stored_json
        )
        retrieved = store.get(job.id)

        assert retrieved is not None
        assert retrieved.id == job.id
        assert retrieved.filename == "test.csv"
        assert retrieved.status == job.status

    def test_save_calls_setex_with_correct_key(self) -> None:
        client = MagicMock()
        store = RedisJobStore(client=client)
        job = Job.create()

        store.save(job)

        call_args = client.setex.call_args[0]
        assert call_args[0] == f"riskflow:job:{job.id}"

    def test_get_returns_none_on_miss(self) -> None:
        client = MagicMock()
        client.get.return_value = None
        store = RedisJobStore(client=client)

        assert store.get("nonexistent") is None

    def test_get_returns_none_on_corrupt_data(self) -> None:
        client = MagicMock()
        client.get.return_value = b"not-valid-json"
        store = RedisJobStore(client=client)

        assert store.get("some-id") is None
