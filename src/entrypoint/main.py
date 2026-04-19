"""Composition root — wires all adapters to ports and starts the app.

This is the ONLY place where:
- Environment variables are read
- Concrete adapters are instantiated
- Dependencies are injected into the domain service
- Logging is configured

Nothing in domain/, ports/, or adapters/ reads env vars or constructs
other adapters. All wiring happens here.
"""

import asyncio
import glob
import logging
import os
import sys
import time
from typing import Any

import openai
import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.adapters.http.middleware import RequestIdMiddleware
from src.adapters.http.routes import HealthResponse, create_router
from src.adapters.parsers.ingestor import PolarsIngestor
from src.adapters.parsers.schema_loader import YamlSchemaLoader
from src.adapters.slm.mapper import GroqMapper
from src.adapters.storage.cache import NullCache, RedisCache
from src.adapters.storage.correction_cache import (
    NullCorrectionCache,
    RedisCorrectionCache,
)
from src.adapters.storage.job_store import InMemoryJobStore, RedisJobStore
from src.domain.model.target_schema import TargetSchema
from src.domain.service.mapping_service import MappingService
from src.ports.output.correction_cache import CorrectionCachePort
from src.ports.output.repo import CachePort

SCHEMAS_DIR = "schemas"
DEFAULT_SCHEMA_FILE = "schemas/standard_reinsurance.yaml"


def _get_version() -> str:
    """Read the project version from pyproject.toml."""
    try:
        from importlib.metadata import version

        return version("riskflow")
    except Exception:
        # Fallback: parse pyproject.toml directly (e.g. when not installed as a package)
        from pathlib import Path

        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        for line in pyproject.read_text().splitlines():
            if line.strip().startswith("version"):
                return line.split("=", 1)[1].strip().strip('"')
        return "0.0.0"


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
    log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, None)
    if not isinstance(log_level, int) or log_level == logging.NOTSET:
        log_level = logging.INFO
    root.setLevel(log_level)

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

    # Bind worker PID so multi-worker logs can be filtered per process
    structlog.contextvars.bind_contextvars(worker_pid=os.getpid())


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Reads configuration from environment variables, instantiates all
    adapters, wires them into the domain service, and mounts the routes.
    """
    configure_logging()
    logger = structlog.get_logger()

    app = FastAPI(title="RiskFlow API", version=_get_version())
    app.add_middleware(RequestIdMiddleware)

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

    # --- SLM concurrency limiter ---
    slm_concurrency = int(os.environ.get("SLM_CONCURRENCY", "3"))
    slm_semaphore = asyncio.Semaphore(slm_concurrency) if slm_concurrency > 0 else None

    # app_configured is logged after all components are created (see below)

    # --- Build a MappingService per schema ---
    # Each schema gets its own GroqMapper so the SLM prompt is
    # tailored to that schema's fields and hints.
    schema_registry: dict[str, MappingService] = {}
    for name, schema in schemas.items():
        mapper = GroqMapper(client=groq_client, schema=schema, semaphore=slm_semaphore)
        schema_registry[name] = MappingService(
            ingestor=ingestor,
            mapper=mapper,
            cache=cache,
            schema=schema,
            correction_cache=correction_cache,
            logger=logger,
        )

    # Default service for requests without ?schema=
    mapping_service = schema_registry.get(
        default_schema.name,
        next(iter(schema_registry.values())),
    )

    # --- Schema store for runtime schemas ---
    schema_store = _create_schema_store(redis_client)

    # Track which schemas are built-in (from YAML, undeletable)
    # Must capture before merging Redis schemas
    builtin_schema_names = set(schemas.keys())

    # Load runtime schemas from Redis and merge with YAML schemas.
    # These are async calls but create_app() is sync (called during Uvicorn
    # startup before the event loop serves requests). Use the event loop
    # directly for these one-time startup operations.
    _loop = asyncio.get_event_loop()
    for runtime_name in _loop.run_until_complete(schema_store.list_all()):
        if runtime_name not in schemas:
            runtime_schema = _loop.run_until_complete(schema_store.get(runtime_name))
            if runtime_schema:
                mapper = GroqMapper(
                    client=groq_client, schema=runtime_schema, semaphore=slm_semaphore
                )
                schema_registry[runtime_name] = MappingService(
                    ingestor=ingestor,
                    mapper=mapper,
                    cache=cache,
                    schema=runtime_schema,
                    correction_cache=correction_cache,
                    logger=logger,
                )
                schemas[runtime_name] = runtime_schema
                logger.info(
                    "runtime_schema_loaded",
                    schema_name=runtime_name,
                    schema_fingerprint=runtime_schema.fingerprint,
                )

    # Factory closure for creating MappingService at runtime
    def _make_service(schema: TargetSchema) -> MappingService:
        mapper = GroqMapper(client=groq_client, schema=schema, semaphore=slm_semaphore)
        return MappingService(
            ingestor=ingestor,
            mapper=mapper,
            cache=cache,
            schema=schema,
            correction_cache=correction_cache,
            logger=logger,
        )

    # --- Job store for async uploads ---
    job_store_type = os.environ.get("JOB_STORE", "redis")
    job_ttl = int(os.environ.get("JOB_TTL", "86400"))
    if job_store_type == "redis" and redis_client:
        job_store: InMemoryJobStore | RedisJobStore = RedisJobStore(
            client=redis_client, ttl=job_ttl
        )
    else:
        job_store = InMemoryJobStore()

    logger.info(
        "app_configured",
        cache_type=type(cache).__name__,
        correction_cache_type=type(correction_cache).__name__,
        schema_count=len(schemas),
        job_store_type=type(job_store).__name__,
    )

    # --- Session store for interactive mapping ---
    session_store = _create_session_store(redis_client)

    # --- Async backend for background tasks ---
    async_backend = os.environ.get("ASYNC_BACKEND", "tasks")

    # --- Routes ---
    router = create_router(
        mapping_service,
        job_store=job_store,
        schema_registry=schema_registry,
        schema_definitions=schemas,
        builtin_schema_names=builtin_schema_names,
        schema_store=schema_store,
        service_factory=_make_service,
        session_store=session_store,
        async_backend=async_backend,
    )
    app.include_router(router)

    @app.get("/health")
    async def health() -> HealthResponse:
        if redis_client is None:
            return HealthResponse(status="ok", redis="not_configured")
        try:
            await redis_client.ping()
            return HealthResponse(status="ok", redis="connected")
        except Exception:
            return HealthResponse(status="degraded", redis="unreachable")

    @app.get("/ready")
    async def ready() -> Any:
        """Readiness probe: can this instance accept requests?

        Returns 200 if Redis is connected (or not configured).
        Returns 503 if Redis is configured but unreachable.
        """
        if redis_client is not None:
            try:
                await redis_client.ping()
            except Exception:
                return JSONResponse(
                    status_code=503,
                    content={"status": "not_ready", "reason": "redis_unreachable"},
                )
        return {"status": "ready"}

    @app.get("/live")
    async def live() -> dict[str, str]:
        """Liveness probe: is this process alive?

        Always returns 200. If this fails, the process is dead.
        """
        return {"status": "alive"}

    _cleanup_orphaned_temp_files(logger)

    return app


def _cleanup_orphaned_temp_files(logger: Any) -> None:
    """Remove temp files from expired sessions.

    Session data expires via Redis TTL (1 hour), but the temp file
    on disk stays forever. This cleanup removes files older than
    the session TTL to prevent disk fill at scale.
    """
    import tempfile as _tempfile

    temp_dir = _tempfile.gettempdir()
    session_ttl = 3600  # matches session_store.DEFAULT_TTL
    cutoff = time.time() - session_ttl
    cleaned = 0
    for path in glob.glob(os.path.join(temp_dir, "riskflow_*")):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                cleaned += 1
        except OSError:
            pass
    if cleaned:
        logger.info("temp_files_cleaned", count=cleaned)


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
    """Create a shared async Redis client if REDIS_URL is set, otherwise None."""
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        import redis.asyncio

        return redis.asyncio.Redis.from_url(redis_url)
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


def _create_session_store(redis_client: Any) -> Any:
    """Create Redis session store if client is available, otherwise NullMappingSessionStore."""
    if redis_client:
        from src.adapters.storage.session_store import RedisMappingSessionStore

        return RedisMappingSessionStore(client=redis_client)
    from src.adapters.storage.session_store import NullMappingSessionStore

    return NullMappingSessionStore()


def _create_schema_store(redis_client: Any) -> Any:
    """Create Redis schema store if client is available, otherwise NullSchemaStore."""
    if redis_client:
        from src.adapters.storage.schema_store import RedisSchemaStore

        return RedisSchemaStore(client=redis_client)
    from src.adapters.storage.schema_store import NullSchemaStore

    return NullSchemaStore()


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
