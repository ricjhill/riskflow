"""Tests for the composition root (main.py).

Verifies that main.py wires all adapters correctly and the app is
functional. Tests use environment variable mocking — no real Redis
or Groq connections.
"""

import logging
import os
from unittest.mock import MagicMock, patch

import pytest
import structlog
from fastapi.testclient import TestClient


class TestAppCreation:
    """Test that create_app wires dependencies correctly."""

    def test_creates_fastapi_app(self) -> None:
        from src.entrypoint.main import create_app

        app = create_app()
        assert app.title == "RiskFlow API"

    def test_health_endpoint_works(self) -> None:
        from src.entrypoint.main import create_app

        app = create_app()
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_upload_endpoint_is_registered(self) -> None:
        from src.entrypoint.main import create_app

        app = create_app()
        routes = [route.path for route in app.routes]
        assert "/upload" in routes

    def test_uses_null_cache_when_redis_unavailable(self) -> None:
        """When Redis is not configured, the app should still start with NullCache."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove REDIS_URL if present
            os.environ.pop("REDIS_URL", None)
            from src.entrypoint.main import create_app

            app = create_app()
            assert app is not None

    def test_reads_groq_api_key_from_env(self) -> None:
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key-123"}):
            from src.entrypoint.main import create_app

            app = create_app()
            # App should create successfully with the key
            assert app is not None


class TestAppConfiguration:
    """Test environment variable handling."""

    def test_app_starts_without_groq_key(self) -> None:
        """App should start even without GROQ_API_KEY — it fails on first request instead."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GROQ_API_KEY", None)
            from src.entrypoint.main import create_app

            app = create_app()
            assert app is not None


class TestCorrectionCacheWiring:
    """Correction cache is wired from Redis when available."""

    def test_corrections_endpoint_registered(self) -> None:
        from src.entrypoint.main import create_app

        app = create_app()
        routes = [route.path for route in app.routes]
        assert "/corrections" in routes

    def test_app_creates_with_null_correction_cache_when_no_redis(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDIS_URL", None)
            from src.entrypoint.main import create_app

            app = create_app()
            # Should start without error
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200

    def test_app_creates_with_redis_correction_cache(self) -> None:
        """When REDIS_URL is set, RedisCorrectionCache is used."""
        mock_client = MagicMock()
        with (
            patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}),
            patch("src.entrypoint.main._create_redis_client", return_value=mock_client),
        ):
            from src.entrypoint.main import create_app

            app = create_app()
            assert app is not None
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200


class TestSessionStoreWiring:
    """Session store is wired from Redis when available."""

    def test_session_endpoints_registered(self) -> None:
        from src.entrypoint.main import create_app

        app = create_app()
        routes = [route.path for route in app.routes]
        assert "/sessions" in routes
        assert "/sessions/{session_id}" in routes
        assert "/sessions/{session_id}/mappings" in routes
        assert "/sessions/{session_id}/finalise" in routes


class TestConfigurableLogLevel:
    """LOG_LEVEL env var controls the root logger level."""

    @pytest.mark.parametrize(
        ("env_value", "expected_level"),
        [
            ("DEBUG", logging.DEBUG),
            ("debug", logging.DEBUG),
            ("WARNING", logging.WARNING),
            ("ERROR", logging.ERROR),
            ("CRITICAL", logging.CRITICAL),
        ],
        ids=["uppercase-debug", "lowercase-debug", "warning", "error", "critical"],
    )
    def test_log_level_from_env(self, env_value: str, expected_level: int) -> None:
        with patch.dict(os.environ, {"LOG_LEVEL": env_value}):
            from src.entrypoint.main import configure_logging

            configure_logging()
            assert logging.getLogger().level == expected_level

    def test_default_log_level_is_info(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOG_LEVEL", None)
            from src.entrypoint.main import configure_logging

            configure_logging()
            assert logging.getLogger().level == logging.INFO

    @pytest.mark.parametrize(
        "env_value",
        ["GARBAGE", "NOTSET", ""],
        ids=["invalid-string", "notset-is-zero", "empty-string"],
    )
    def test_invalid_log_level_falls_back_to_info(self, env_value: str) -> None:
        with patch.dict(os.environ, {"LOG_LEVEL": env_value}):
            from src.entrypoint.main import configure_logging

            configure_logging()
            assert logging.getLogger().level == logging.INFO


class TestWorkerPidInLogs:
    """Worker PID is bound into structlog context for multi-worker identification."""

    def test_worker_pid_bound_in_structlog(self) -> None:
        from src.entrypoint.main import configure_logging

        configure_logging()

        # Capture the log event to check for worker_pid
        captured: list[dict] = []

        def capture(
            logger: object, method_name: str, event_dict: dict[str, object]
        ) -> dict[str, object]:
            captured.append(event_dict.copy())
            raise structlog.DropEvent

        old_config = structlog.get_config()
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                capture,
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=False,
        )
        try:
            structlog.get_logger().info("test_event")
            assert len(captured) == 1
            assert "worker_pid" in captured[0]
            assert captured[0]["worker_pid"] == os.getpid()
        finally:
            structlog.configure(**old_config)


class TestJobStoreWiring:
    """JOB_STORE env var controls which job store is used."""

    def test_job_store_is_redis_when_redis_available(self) -> None:
        mock_client = MagicMock()
        with (
            patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}),
            patch("src.entrypoint.main._create_redis_client", return_value=mock_client),
        ):
            from src.entrypoint.main import create_app

            app = create_app()
            # The app should start — verify via health endpoint
            client = TestClient(app)
            assert client.get("/health").status_code == 200

    def test_job_store_falls_back_to_inmemory_without_redis(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDIS_URL", None)
            from src.entrypoint.main import create_app

            app = create_app()
            client = TestClient(app)
            assert client.get("/health").status_code == 200

    def test_job_store_memory_when_env_set(self) -> None:
        """JOB_STORE=memory forces InMemoryJobStore even with Redis available."""
        mock_client = MagicMock()
        with (
            patch.dict(
                os.environ,
                {"REDIS_URL": "redis://localhost:6379", "JOB_STORE": "memory"},
            ),
            patch("src.entrypoint.main._create_redis_client", return_value=mock_client),
        ):
            from src.entrypoint.main import create_app

            app = create_app()
            client = TestClient(app)
            assert client.get("/health").status_code == 200

    def test_app_configured_logs_job_store_type(self, capfd: pytest.CaptureFixture[str]) -> None:
        import json as json_mod

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDIS_URL", None)
            from src.entrypoint.main import create_app

            create_app()

        captured = capfd.readouterr()
        lines = [l for l in captured.out.strip().split("\n") if l.strip()]
        config_events = [json_mod.loads(l) for l in lines if "app_configured" in l]
        assert len(config_events) >= 1
        assert "job_store_type" in config_events[-1]


class TestSemaphoreWiring:
    """SLM_CONCURRENCY env var controls the Groq semaphore."""

    def test_groq_mapper_created_with_semaphore(self) -> None:
        """Default SLM_CONCURRENCY=3 creates a semaphore on the mapper."""
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("src.entrypoint.main.GroqMapper") as MockMapper,
        ):
            os.environ.pop("SLM_CONCURRENCY", None)
            from src.entrypoint.main import create_app

            create_app()
            # Verify GroqMapper was called with a semaphore kwarg
            assert MockMapper.call_count >= 1
            first_call_kwargs = MockMapper.call_args_list[0].kwargs
            assert "semaphore" in first_call_kwargs
            assert first_call_kwargs["semaphore"] is not None

    def test_semaphore_disabled_when_zero(self) -> None:
        """SLM_CONCURRENCY=0 disables the semaphore (no concurrency limit)."""
        with (
            patch.dict(os.environ, {"SLM_CONCURRENCY": "0"}),
            patch("src.entrypoint.main.GroqMapper") as MockMapper,
        ):
            from src.entrypoint.main import create_app

            create_app()
            assert MockMapper.call_count >= 1
            first_call_kwargs = MockMapper.call_args_list[0].kwargs
            assert first_call_kwargs.get("semaphore") is None
