"""Job store adapters for async upload tracking."""

import json
from typing import Any

import redis as redis_lib

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

    def list_all(self) -> list[Job]:
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

    def save(self, job: Job) -> None:
        try:
            self._client.setex(
                f"{KEY_PREFIX}{job.id}",
                self._ttl,
                json.dumps(job.to_dict()),
            )
        except (ConnectionError, redis_lib.RedisError):
            pass

    def get(self, job_id: str) -> Job | None:
        try:
            data = self._client.get(f"{KEY_PREFIX}{job_id}")
        except (ConnectionError, redis_lib.RedisError):
            return None
        if data is None:
            return None
        try:
            parsed = json.loads(data)
            return Job.from_dict(parsed)
        except (ValueError, TypeError, json.JSONDecodeError, KeyError):
            return None

    def list_all(self) -> list[Job]:
        jobs: list[Job] = []
        try:
            cursor = 0
            while True:
                cursor, keys = self._client.scan(cursor, match=f"{KEY_PREFIX}*")
                for key in keys:
                    data = self._client.get(key)
                    if data is not None:
                        try:
                            jobs.append(Job.from_dict(json.loads(data)))
                        except (ValueError, TypeError, json.JSONDecodeError, KeyError):
                            continue
                if cursor == 0:
                    break
        except (ConnectionError, redis_lib.RedisError):
            return []
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)
