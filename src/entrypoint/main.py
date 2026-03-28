"""Composition root — wires all adapters to ports and starts the app.

This is the ONLY place where:
- Environment variables are read
- Concrete adapters are instantiated
- Dependencies are injected into the domain service
- Logging is configured

Nothing in domain/, ports/, or adapters/ reads env vars or constructs
other adapters. All wiring happens here.
"""

import logging
import os
import sys

import openai
import structlog
from fastapi import FastAPI

from src.adapters.http.routes import create_router
from src.adapters.parsers.ingestor import PolarsIngestor
from src.adapters.slm.mapper import GroqMapper
from src.adapters.storage.cache import NullCache, RedisCache
from src.adapters.storage.job_store import InMemoryJobStore
from src.domain.service.mapping_service import MappingService
from src.ports.output.repo import CachePort


def configure_logging() -> None:
    """Configure structlog for JSON output via stdlib logging.

    Called once at app startup. All logging throughout the app should
    use structlog.get_logger() — never stdlib logging directly.

    Uses stdlib logging as the output backend so it works correctly
    with pytest's capfd/capsys and log capture.
    """
    # Configure stdlib to output to stdout
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Reads configuration from environment variables, instantiates all
    adapters, wires them into the domain service, and mounts the routes.
    """
    configure_logging()
    logger = structlog.get_logger()

    app = FastAPI(title="RiskFlow API")

    # --- Adapters ---
    ingestor = PolarsIngestor()
    cache = _create_cache()
    groq_client = _create_groq_client()
    mapper = GroqMapper(client=groq_client)

    logger.info("app_configured", cache_type=type(cache).__name__)

    # --- Domain service ---
    mapping_service = MappingService(
        ingestor=ingestor,
        mapper=mapper,
        cache=cache,
    )

    # --- Job store for async uploads ---
    job_store = InMemoryJobStore()

    # --- Routes ---
    router = create_router(mapping_service, job_store=job_store)
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
