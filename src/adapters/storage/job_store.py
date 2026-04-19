"""Job store adapters for async upload tracking."""

import json
import time
from typing import Any

import redis as redis_lib
import structlog

from src.domain.model.job import Job


class InMemoryJobStore:
    """Stores jobs in a dict. Suitable for single-process deployments.

    For multi-process or persistent job tracking, a Redis-backed
    implementation should be used instead.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    async def save(self, job: Job) -> None:
        self._jobs[job.id] = job

    async def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def list_all(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)


KEY_PREFIX = "riskflow:job:"
DEFAULT_TTL = 86400  # 24 hours


class RedisJobStore:
    """Redis-backed job store. Jobs expire after TTL.

    Each save() resets the TTL, so jobs that progress through status
    transitions stay alive. A completed job expires TTL seconds after
    its last status change.
    """

    def __init__(self, client: Any, ttl: int = DEFAULT_TTL) -> None:
        self._client = client
        self._ttl = ttl
        self._logger = structlog.get_logger()

    async def save(self, job: Job) -> None:
        start = time.monotonic()
        try:
            await self._client.setex(
                f"{KEY_PREFIX}{job.id}",
                self._ttl,
                json.dumps(job.to_dict()),
            )
        except (ConnectionError, redis_lib.RedisError) as exc:
            self._logger.error("job_store_save_failed", job_id=job.id, error=str(exc))
        duration_ms = int((time.monotonic() - start) * 1000)
        self._logger.debug("job_store_save", job_id=job.id, duration_ms=duration_ms)

    async def get(self, job_id: str) -> Job | None:
        try:
            data = await self._client.get(f"{KEY_PREFIX}{job_id}")
        except (ConnectionError, redis_lib.RedisError) as exc:
            self._logger.error("job_store_get_failed", job_id=job_id, error=str(exc))
            return None
        if data is None:
            return None
        try:
            parsed = json.loads(data)
            return Job.from_dict(parsed)
        except (ValueError, TypeError, json.JSONDecodeError, KeyError):
            return None

    async def list_all(self) -> list[Job]:
        start = time.monotonic()
        jobs: list[Job] = []
        try:
            cursor = 0
            while True:
                cursor, keys = await self._client.scan(cursor, match=f"{KEY_PREFIX}*")
                for key in keys:
                    data = await self._client.get(key)
                    if data is not None:
                        try:
                            jobs.append(Job.from_dict(json.loads(data)))
                        except (ValueError, TypeError, json.JSONDecodeError, KeyError):
                            continue
                if cursor == 0:
                    break
        except (ConnectionError, redis_lib.RedisError) as exc:
            self._logger.error("job_store_list_failed", error=str(exc))
            return []
        result = sorted(jobs, key=lambda j: j.created_at, reverse=True)
        duration_ms = int((time.monotonic() - start) * 1000)
        self._logger.debug("job_store_list", count=len(result), duration_ms=duration_ms)
        return result
