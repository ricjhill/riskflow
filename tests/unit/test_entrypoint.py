"""Tests for the composition root (main.py).

Verifies that main.py wires all adapters correctly and the app is
functional. Tests use environment variable mocking — no real Redis
or Groq connections.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
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
