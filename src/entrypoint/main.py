"""Composition root — wires all adapters to ports and starts the app.

This is the ONLY place where:
- Environment variables are read
- Concrete adapters are instantiated
- Dependencies are injected into the domain service

Nothing in domain/, ports/, or adapters/ reads env vars or constructs
other adapters. All wiring happens here.
"""

import os

import openai
from fastapi import FastAPI

from src.adapters.http.routes import create_router
from src.adapters.parsers.ingestor import PolarsIngestor
from src.adapters.slm.mapper import GroqMapper
from src.adapters.storage.cache import NullCache, RedisCache
from src.domain.service.mapping_service import MappingService
from src.ports.output.repo import CachePort


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Reads configuration from environment variables, instantiates all
    adapters, wires them into the domain service, and mounts the routes.
    """
    app = FastAPI(title="RiskFlow API")

    # --- Adapters ---
    ingestor = PolarsIngestor()
    cache = _create_cache()
    groq_client = _create_groq_client()
    mapper = GroqMapper(client=groq_client)

    # --- Domain service ---
    mapping_service = MappingService(
        ingestor=ingestor,
        mapper=mapper,
        cache=cache,
    )

    # --- Routes ---
    router = create_router(mapping_service)
    app.include_router(router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _create_cache() -> CachePort:
    """Create Redis cache if REDIS_URL is set, otherwise NullCache."""
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        import redis

        client = redis.Redis.from_url(redis_url)
        return RedisCache(client=client)
    return NullCache()


def _create_groq_client() -> openai.AsyncOpenAI:
    """Create Groq client from GROQ_API_KEY env var.

    If the key is missing, we still create the client — it will fail
    on first actual API call rather than at startup. This allows the
    app to start and serve /health even without a configured key.
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    return openai.AsyncOpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )


app = create_app()
