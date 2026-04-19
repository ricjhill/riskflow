"""Tests for RedisJobStore adapter.

All tests mock the Redis client — no real Redis connection.
Tests follow the pattern established in test_cache_adapter.py
and test_session_store (not yet in unit/).
"""

import json

import pytest
from unittest.mock import AsyncMock

import structlog

from src.adapters.storage.job_store import RedisJobStore
from src.domain.model.job import Job
from src.ports.output.job_store import JobStorePort


class TestRedisJobStoreProtocol:
    """RedisJobStore satisfies JobStorePort protocol for dependency injection."""

    @pytest.mark.asyncio
    async def test_satisfies_job_store_port(self) -> None:
        assert isinstance(RedisJobStore(client=AsyncMock()), JobStorePort)


class TestSaveAndGet:
    """Job persistence via Redis SETEX — save serializes to JSON, get deserializes."""

    @pytest.mark.asyncio
    async def test_save_and_get_roundtrip(self) -> None:
        client = AsyncMock()
        store = RedisJobStore(client=client)
        job = Job.create(filename="test.csv")

        # Capture what save writes
        await store.save(job)
        call_args = client.setex.call_args
        key = call_args[0][0]
        stored_json = call_args[0][2]

        # Feed it back via get
        client.get.return_value = (
            stored_json.encode() if isinstance(stored_json, str) else stored_json
        )
        retrieved = await store.get(job.id)

        assert retrieved is not None
        assert retrieved.id == job.id
        assert retrieved.filename == "test.csv"
        assert retrieved.status == job.status

    @pytest.mark.asyncio
    async def test_save_calls_setex_with_correct_key(self) -> None:
        client = AsyncMock()
        store = RedisJobStore(client=client)
        job = Job.create()

        await store.save(job)

        call_args = client.setex.call_args[0]
        assert call_args[0] == f"riskflow:job:{job.id}"

    @pytest.mark.asyncio
    async def test_get_returns_none_on_miss(self) -> None:
        """Missing key returns None — job appears as 'not found', not an error."""
        client = AsyncMock()
        client.get.return_value = None
        store = RedisJobStore(client=client)

        assert await store.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_returns_none_on_corrupt_data(self) -> None:
        """Corrupt JSON in Redis returns None instead of crashing the API."""
        client = AsyncMock()
        client.get.return_value = b"not-valid-json"
        store = RedisJobStore(client=client)

        assert await store.get("some-id") is None


class TestTTL:
    """Job TTL management — jobs expire after configurable duration, refreshed on each save."""

    @pytest.mark.asyncio
    async def test_save_calls_setex_with_default_ttl(self) -> None:
        client = AsyncMock()
        store = RedisJobStore(client=client)
        job = Job.create()

        await store.save(job)

        ttl_arg = client.setex.call_args[0][1]
        assert ttl_arg == 86400

    @pytest.mark.asyncio
    async def test_save_refreshes_ttl_on_update(self) -> None:
        """Each save resets the TTL — jobs that progress through status transitions stay alive."""
        client = AsyncMock()
        store = RedisJobStore(client=client)
        job = Job.create()

        await store.save(job)
        job.start()
        await store.save(job)

        assert client.setex.call_count == 2

    @pytest.mark.asyncio
    async def test_custom_ttl_from_constructor(self) -> None:
        client = AsyncMock()
        store = RedisJobStore(client=client, ttl=3600)
        job = Job.create()

        await store.save(job)

        ttl_arg = client.setex.call_args[0][1]
        assert ttl_arg == 3600


class TestListAll:
    """List all jobs via SCAN — returns newest-first, skips corrupt entries."""

    @pytest.mark.asyncio
    async def test_list_all_uses_scan(self) -> None:
        client = AsyncMock()
        job = Job.create(filename="a.csv")
        client.scan.return_value = (0, [f"riskflow:job:{job.id}".encode()])
        client.get.return_value = json.dumps(job.to_dict()).encode()
        store = RedisJobStore(client=client)

        result = await store.list_all()

        client.scan.assert_called_once()
        assert len(result) == 1
        assert result[0].filename == "a.csv"

    @pytest.mark.asyncio
    async def test_list_all_empty(self) -> None:
        client = AsyncMock()
        client.scan.return_value = (0, [])
        store = RedisJobStore(client=client)

        assert await store.list_all() == []

    @pytest.mark.asyncio
    async def test_list_all_skips_corrupt_entries(self) -> None:
        """One bad entry in Redis doesn't break the entire listing — it's silently skipped."""
        client = AsyncMock()
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

        result = await store.list_all()
        assert len(result) == 1
        assert result[0].filename == "good.csv"


class TestGracefulDegradation:
    """Redis failures degrade to no-op — the API stays up even when Redis is down."""

    def _capture_structlog(self) -> tuple[list[dict[str, object]], dict]:
        """Set up structlog capture, return (events_list, old_config)."""
        captured: list[dict[str, object]] = []
        old_config = structlog.get_config()

        def capture(
            logger: object, method_name: str, event_dict: dict[str, object]
        ) -> dict[str, object]:
            captured.append(event_dict.copy())
            raise structlog.DropEvent

        structlog.configure(
            processors=[capture],
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=False,
        )
        return captured, old_config

    @pytest.mark.asyncio
    async def test_save_swallows_connection_error(self) -> None:
        """Save failure logs an error but does not raise — the job proceeds without persistence."""
        captured, old_config = self._capture_structlog()
        try:
            client = AsyncMock()
            client.setex.side_effect = ConnectionError("gone")
            store = RedisJobStore(client=client)

            await store.save(Job.create())  # should not raise

            error_events = [e for e in captured if e.get("event") == "job_store_save_failed"]
            assert len(error_events) == 1
            assert "error" in error_events[0]
        finally:
            structlog.configure(**old_config)

    @pytest.mark.asyncio
    async def test_get_swallows_connection_error(self) -> None:
        """Get failure logs an error and returns None — job appears as 'not found', not a 500 error."""
        captured, old_config = self._capture_structlog()
        try:
            client = AsyncMock()
            client.get.side_effect = ConnectionError("gone")
            store = RedisJobStore(client=client)

            assert await store.get("some-id") is None

            error_events = [e for e in captured if e.get("event") == "job_store_get_failed"]
            assert len(error_events) == 1
            assert "error" in error_events[0]
        finally:
            structlog.configure(**old_config)

    @pytest.mark.asyncio
    async def test_list_all_swallows_connection_error(self) -> None:
        """List failure logs an error and returns empty list — the endpoint returns no jobs, not a 500."""
        captured, old_config = self._capture_structlog()
        try:
            client = AsyncMock()
            client.scan.side_effect = ConnectionError("gone")
            store = RedisJobStore(client=client)

            assert await store.list_all() == []

            error_events = [e for e in captured if e.get("event") == "job_store_list_failed"]
            assert len(error_events) == 1
            assert "error" in error_events[0]
        finally:
            structlog.configure(**old_config)

    @pytest.mark.asyncio
    async def test_save_error_logs_job_id(self) -> None:
        """Save error log includes the job_id so operators can correlate failures to specific jobs."""
        captured, old_config = self._capture_structlog()
        try:
            client = AsyncMock()
            client.setex.side_effect = ConnectionError("connection refused")
            store = RedisJobStore(client=client)
            job = Job.create(filename="important.csv")

            await store.save(job)

            error_events = [e for e in captured if e.get("event") == "job_store_save_failed"]
            assert len(error_events) == 1
            assert error_events[0]["job_id"] == job.id
            assert error_events[0]["error"] == "connection refused"
        finally:
            structlog.configure(**old_config)

    @pytest.mark.asyncio
    async def test_get_error_logs_job_id(self) -> None:
        """Get error log includes the job_id so operators can correlate failures to specific jobs."""
        captured, old_config = self._capture_structlog()
        try:
            client = AsyncMock()
            client.get.side_effect = ConnectionError("timeout")
            store = RedisJobStore(client=client)

            await store.get("job-abc-123")

            error_events = [e for e in captured if e.get("event") == "job_store_get_failed"]
            assert len(error_events) == 1
            assert error_events[0]["job_id"] == "job-abc-123"
            assert error_events[0]["error"] == "timeout"
        finally:
            structlog.configure(**old_config)

    @pytest.mark.asyncio
    async def test_list_error_logs_event(self) -> None:
        """List error log uses the correct event name for filtering in production logs."""
        captured, old_config = self._capture_structlog()
        try:
            client = AsyncMock()
            client.scan.side_effect = ConnectionError("redis down")
            store = RedisJobStore(client=client)

            await store.list_all()

            error_events = [e for e in captured if e.get("event") == "job_store_list_failed"]
            assert len(error_events) == 1
            assert error_events[0]["error"] == "redis down"
        finally:
            structlog.configure(**old_config)


class TestDebugLogging:
    """DEBUG-level log events for RedisJobStore operations."""

    def _capture_structlog(self) -> tuple[list[dict[str, object]], dict]:
        """Set up structlog capture, return (events_list, old_config)."""
        captured: list[dict[str, object]] = []
        old_config = structlog.get_config()

        def capture(
            logger: object, method_name: str, event_dict: dict[str, object]
        ) -> dict[str, object]:
            captured.append(event_dict.copy())
            raise structlog.DropEvent

        structlog.configure(
            processors=[capture],
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=False,
        )
        return captured, old_config

    @pytest.mark.asyncio
    async def test_job_store_save_logged(self) -> None:
        """save() emits job_store_save DEBUG event with job_id and duration_ms."""
        captured, old_config = self._capture_structlog()
        try:
            client = AsyncMock()
            store = RedisJobStore(client=client)
            job = Job.create(filename="test.csv")
            await store.save(job)

            save_events = [e for e in captured if e.get("event") == "job_store_save"]
            assert len(save_events) == 1
            assert save_events[0]["job_id"] == job.id
            assert "duration_ms" in save_events[0]
            assert isinstance(save_events[0]["duration_ms"], int)
        finally:
            structlog.configure(**old_config)

    @pytest.mark.asyncio
    async def test_job_store_list_logged(self) -> None:
        """list_all() emits job_store_list DEBUG event with count and duration_ms."""
        captured, old_config = self._capture_structlog()
        try:
            client = AsyncMock()
            job = Job.create()
            client.scan.return_value = (0, [f"riskflow:job:{job.id}".encode()])
            client.get.return_value = json.dumps(job.to_dict()).encode()
            store = RedisJobStore(client=client)
            await store.list_all()

            list_events = [e for e in captured if e.get("event") == "job_store_list"]
            assert len(list_events) == 1
            assert list_events[0]["count"] == 1
            assert "duration_ms" in list_events[0]
            assert isinstance(list_events[0]["duration_ms"], int)
        finally:
            structlog.configure(**old_config)
