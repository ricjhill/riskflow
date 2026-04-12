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


class TestTTL:
    def test_save_calls_setex_with_default_ttl(self) -> None:
        client = MagicMock()
        store = RedisJobStore(client=client)
        job = Job.create()

        store.save(job)

        ttl_arg = client.setex.call_args[0][1]
        assert ttl_arg == 86400

    def test_save_refreshes_ttl_on_update(self) -> None:
        client = MagicMock()
        store = RedisJobStore(client=client)
        job = Job.create()

        store.save(job)
        job.start()
        store.save(job)

        assert client.setex.call_count == 2

    def test_custom_ttl_from_constructor(self) -> None:
        client = MagicMock()
        store = RedisJobStore(client=client, ttl=3600)
        job = Job.create()

        store.save(job)

        ttl_arg = client.setex.call_args[0][1]
        assert ttl_arg == 3600


class TestListAll:
    def test_list_all_uses_scan(self) -> None:
        client = MagicMock()
        job = Job.create(filename="a.csv")
        client.scan.return_value = (0, [f"riskflow:job:{job.id}".encode()])
        client.get.return_value = json.dumps(job.to_dict()).encode()
        store = RedisJobStore(client=client)

        result = store.list_all()

        client.scan.assert_called_once()
        assert len(result) == 1
        assert result[0].filename == "a.csv"

    def test_list_all_empty(self) -> None:
        client = MagicMock()
        client.scan.return_value = (0, [])
        store = RedisJobStore(client=client)

        assert store.list_all() == []

    def test_list_all_skips_corrupt_entries(self) -> None:
        client = MagicMock()
        job = Job.create(filename="good.csv")
        client.scan.return_value = (
            0,
            [b"riskflow:job:good", b"riskflow:job:bad"],
        )
        client.get.side_effect = [
            json.dumps(job.to_dict()).encode(),
            b"not-json",
        ]
        store = RedisJobStore(client=client)

        result = store.list_all()
        assert len(result) == 1
        assert result[0].filename == "good.csv"


class TestGracefulDegradation:
    def test_save_swallows_connection_error(self) -> None:
        client = MagicMock()
        client.setex.side_effect = ConnectionError("gone")
        store = RedisJobStore(client=client)

        store.save(Job.create())  # should not raise

    def test_get_swallows_connection_error(self) -> None:
        client = MagicMock()
        client.get.side_effect = ConnectionError("gone")
        store = RedisJobStore(client=client)

        assert store.get("some-id") is None

    def test_list_all_swallows_connection_error(self) -> None:
        client = MagicMock()
        client.scan.side_effect = ConnectionError("gone")
        store = RedisJobStore(client=client)

        assert store.list_all() == []
