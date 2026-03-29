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
from typing import Any

import openai
import structlog
from fastapi import FastAPI

from src.adapters.http.routes import create_router
from src.adapters.parsers.ingestor import PolarsIngestor
from src.adapters.slm.mapper import GroqMapper
from src.adapters.storage.cache import NullCache, RedisCache
from src.adapters.storage.correction_cache import (
    NullCorrectionCache,
    RedisCorrectionCache,
)
from src.adapters.parsers.schema_loader import YamlSchemaLoader
from src.adapters.storage.job_store import InMemoryJobStore
from src.domain.model.target_schema import TargetSchema
from src.domain.service.mapping_service import MappingService
from src.ports.output.correction_cache import CorrectionCachePort
from src.ports.output.repo import CachePort

SCHEMAS_DIR = "schemas"
DEFAULT_SCHEMA_FILE = "schemas/default.yaml"


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

    # --- Schemas ---
    schemas = _load_all_schemas()
    for name, schema in schemas.items():
        logger.info(
            "schema_loaded",
            schema_name=name,
            schema_fingerprint=schema.fingerprint,
            field_count=len(schema.fields),
        )

    default_schema = schemas.get(
        os.environ.get("DEFAULT_SCHEMA", "standard_reinsurance"),
        next(iter(schemas.values())),
    )

    # --- Adapters ---
    ingestor = PolarsIngestor()
    redis_client = _create_redis_client()
    cache = _create_cache(redis_client)
    correction_cache = _create_correction_cache(redis_client)
    groq_client = _create_groq_client()
    mapper = GroqMapper(client=groq_client)

    logger.info(
        "app_configured",
        cache_type=type(cache).__name__,
        correction_cache_type=type(correction_cache).__name__,
        schema_count=len(schemas),
    )

    # --- Build a MappingService per schema ---
    schema_registry: dict[str, MappingService] = {}
    for name, schema in schemas.items():
        schema_registry[name] = MappingService(
            ingestor=ingestor,
            mapper=mapper,
            cache=cache,
            schema=schema,
            correction_cache=correction_cache,
        )

    # Default service for requests without ?schema=
    mapping_service = schema_registry.get(
        default_schema.name,
        next(iter(schema_registry.values())),
    )

    # --- Job store for async uploads ---
    job_store = InMemoryJobStore()

    # --- Routes ---
    router = create_router(
        mapping_service, job_store=job_store, schema_registry=schema_registry
    )
    app.include_router(router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _load_schema() -> TargetSchema:
    """Load the target schema from SCHEMA_PATH env var or default file.

    If SCHEMA_PATH is set, loads from that path (fatal error if invalid).
    Otherwise loads from schemas/default.yaml.
    Both paths use YamlSchemaLoader which raises InvalidSchemaError on
    any failure — the app refuses to boot with an invalid schema.
    """
    schema_path = os.environ.get("SCHEMA_PATH", DEFAULT_SCHEMA_FILE)
    loader = YamlSchemaLoader()
    return loader.load(schema_path)


def _load_all_schemas() -> dict[str, TargetSchema]:
    """Load all YAML schemas from the schemas/ directory.

    If SCHEMA_PATH is set, loads only that single schema.
    Otherwise scans schemas/ for all .yaml files and loads each.
    Returns a dict keyed by schema name.
    """
    loader = YamlSchemaLoader()

    schema_path = os.environ.get("SCHEMA_PATH")
    if schema_path:
        schema = loader.load(schema_path)
        return {schema.name: schema}

    from pathlib import Path

    schemas_dir = Path(SCHEMAS_DIR)
    if not schemas_dir.exists():
        schema = loader.load(DEFAULT_SCHEMA_FILE)
        return {schema.name: schema}

    schemas: dict[str, TargetSchema] = {}
    for yaml_file in sorted(schemas_dir.glob("*.yaml")):
        schema = loader.load(str(yaml_file))
        schemas[schema.name] = schema

    if not schemas:
        schema = loader.load(DEFAULT_SCHEMA_FILE)
        return {schema.name: schema}

    return schemas


def _create_redis_client() -> Any:
    """Create a shared Redis client if REDIS_URL is set, otherwise None."""
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        import redis

        return redis.Redis.from_url(redis_url)
    return None


def _create_cache(redis_client: Any) -> CachePort:
    """Create Redis cache if client is available, otherwise NullCache."""
    if redis_client:
        return RedisCache(client=redis_client)
    return NullCache()


def _create_correction_cache(redis_client: Any) -> CorrectionCachePort:
    """Create Redis correction cache if client is available, otherwise NullCorrectionCache."""
    if redis_client:
        return RedisCorrectionCache(client=redis_client)
    return NullCorrectionCache()


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
