"""FastAPI HTTP adapter routes.

Maps domain operations to HTTP endpoints and domain errors to HTTP status
codes. The route handler is a thin adapter — all business logic lives in
MappingService. Logging happens here at the adapter boundary.

Error mapping:
- InvalidCedentDataError → 400 Bad Request
- MappingConfidenceLowError → 422 Unprocessable Entity
- SchemaValidationError → 422 Unprocessable Entity
- InvalidCorrectionError → 422 Unprocessable Entity
- SLMUnavailableError → 503 Service Unavailable
- Unexpected errors → 500 Internal Server Error
"""

import asyncio
import os
import re
import tempfile
import time
from collections.abc import Callable

import structlog
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from src.domain.model.correction import Correction
from src.domain.model.errors import (
    InvalidCedentDataError,
    InvalidCorrectionError,
    MappingConfidenceLowError,
    RiskFlowError,
    SchemaValidationError,
    SLMUnavailableError,
)
from src.domain.model.job import Job
from src.domain.model.schema import ColumnMapping, MappingResult, ProcessingResult
from src.domain.model.session import MappingSession, SessionStatus
from src.domain.model.target_schema import TargetSchema
from src.domain.service.mapping_service import MappingService
from src.ports.output.job_store import JobStorePort
from src.ports.output.schema_store import SchemaStorePort
from src.ports.output.session_store import MappingSessionStorePort

logger = structlog.get_logger()

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB


class CorrectionItem(BaseModel):
    """A single correction in a POST /corrections request."""

    source_header: str
    target_field: str


class CorrectionRequest(BaseModel):
    """Request body for POST /corrections."""

    cedent_id: str
    corrections: list[CorrectionItem]


class UpdateMappingsRequest(BaseModel):
    """Request body for PUT /sessions/{session_id}/mappings."""

    mappings: list[ColumnMapping] = []
    unmapped_headers: list[str] = []


class ExtendTargetFieldsRequest(BaseModel):
    """Request body for PATCH /sessions/{session_id}/target-fields."""

    fields: list[str]


# --- Response models (drive the OpenAPI spec) ---


class ErrorDetail(BaseModel):
    """Structured error response body."""

    error_code: str
    message: str
    suggestion: str


class HealthResponse(BaseModel):
    """GET /health response."""

    status: str
    redis: str = "not_configured"


class SchemaListResponse(BaseModel):
    """GET /schemas response."""

    schemas: list[str]


class SchemaCreatedResponse(BaseModel):
    """POST /schemas response."""

    name: str
    fingerprint: str


class SheetListResponse(BaseModel):
    """POST /sheets response."""

    sheets: list[str]


class CorrectionStoredResponse(BaseModel):
    """POST /corrections response."""

    stored: int


class AsyncJobResponse(BaseModel):
    """POST /upload/async response."""

    job_id: str


class JobStatusResponse(BaseModel):
    """GET /jobs/{job_id} response."""

    job_id: str
    status: str
    result: dict[str, object] | None = None
    error: str | None = None
    filename: str | None = None
    created_at: str | None = None


class JobSummary(BaseModel):
    """One item in the GET /jobs list."""

    job_id: str
    filename: str | None
    created_at: str
    status: str


class JobListResponse(BaseModel):
    """GET /jobs response."""

    jobs: list[JobSummary]


_SCHEMA_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_schema_name(name: str) -> None:
    """Reject schema names that contain path traversal or invalid characters."""
    if not _SCHEMA_NAME_PATTERN.match(name):
        raise HTTPException(
            status_code=400,
            detail=_error_detail(
                "INVALID_SCHEMA_NAME",
                f"Invalid schema name '{name}'. Only alphanumeric, hyphens, and underscores allowed.",
                "Use a valid schema name from GET /schemas.",
            ),
        )


def create_router(
    mapping_service: MappingService,
    job_store: JobStorePort | None = None,
    schema_registry: dict[str, MappingService] | None = None,
    schema_definitions: dict[str, TargetSchema] | None = None,
    builtin_schema_names: set[str] | None = None,
    schema_store: SchemaStorePort | None = None,
    service_factory: Callable[[TargetSchema], MappingService] | None = None,
    session_store: MappingSessionStorePort | None = None,
    async_backend: str = "tasks",
) -> APIRouter:
    """Create a FastAPI router wired to the given MappingService.

    The service is injected — the router never constructs adapters itself.
    This keeps the HTTP adapter decoupled from concrete implementations.
    job_store is optional — async endpoints are only available when provided.
    schema_registry maps schema names to MappingService instances. When
    ?schema= is provided, the named service is used instead of the default.

    Schema CRUD parameters (all optional for backward compatibility):
    - schema_definitions: parallel dict for GET /schemas/{name}
    - builtin_schema_names: names that can't be deleted
    - schema_store: persistence for runtime schemas
    - service_factory: closure to build MappingService for new schemas
    - session_store: interactive mapping session persistence
    """
    router = APIRouter()
    _registry = schema_registry or {}
    _definitions: dict[str, TargetSchema] = dict(schema_definitions) if schema_definitions else {}
    _builtins = builtin_schema_names or set()
    _store = schema_store
    _factory = service_factory
    _schema_lock = asyncio.Lock()

    def _resolve_service(schema_name: str | None) -> MappingService:
        """Resolve which MappingService to use based on ?schema= param."""
        if not schema_name or not schema_name.strip():
            return mapping_service
        _validate_schema_name(schema_name)
        service = _registry.get(schema_name)
        if service is None:
            raise HTTPException(
                status_code=404,
                detail=_error_detail(
                    "SCHEMA_NOT_FOUND",
                    f"Schema '{schema_name}' not found. Available: {sorted(_registry.keys())}",
                    "Use GET /schemas to list available schemas.",
                ),
            )
        return service

    @router.get("/schemas")
    async def list_schemas() -> SchemaListResponse:
        """List all available schema names."""
        return SchemaListResponse(schemas=sorted(_registry.keys()))

    @router.get("/schemas/{name}")
    async def get_schema(name: str) -> TargetSchema:
        """Return the full definition of a schema."""
        _validate_schema_name(name)
        schema = _definitions.get(name)
        if schema is None:
            raise HTTPException(
                status_code=404,
                detail=_error_detail(
                    "SCHEMA_NOT_FOUND",
                    f"Schema '{name}' not found.",
                    "Use GET /schemas to list available schemas.",
                ),
            )
        return schema

    @router.post("/schemas", status_code=201)
    async def create_schema(body: dict[str, object]) -> SchemaCreatedResponse:
        """Create a new runtime schema from a JSON definition."""
        from pydantic import ValidationError as PydanticValidationError

        async with _schema_lock:
            if not body:
                raise HTTPException(
                    status_code=422,
                    detail=_error_detail(
                        "INVALID_SCHEMA",
                        "Request body must not be empty.",
                        "Provide a JSON object with 'name' and 'fields' keys.",
                    ),
                )

            try:
                schema = TargetSchema.model_validate(body)
            except PydanticValidationError as e:
                raise HTTPException(
                    status_code=422,
                    detail=_error_detail(
                        "INVALID_SCHEMA",
                        str(e),
                        "Check the schema format: name (string), fields (dict of field definitions).",
                    ),
                ) from e

            _validate_schema_name(schema.name)

            if schema.name in _registry or schema.name in _definitions:
                raise HTTPException(
                    status_code=409,
                    detail=_error_detail(
                        "SCHEMA_ALREADY_EXISTS",
                        f"Schema '{schema.name}' already exists.",
                        "Use DELETE /schemas/{name} first, or choose a different name.",
                    ),
                )

            # Persist to store
            if _store:
                _store.save(schema)

            # Create service and register
            if _factory:
                _registry[schema.name] = _factory(schema)
            _definitions[schema.name] = schema

            logger.info(
                "schema_created",
                schema_name=schema.name,
                fingerprint=schema.fingerprint,
                field_count=len(schema.fields),
            )
            return SchemaCreatedResponse(name=schema.name, fingerprint=schema.fingerprint)

    @router.delete("/schemas/{name}", status_code=204)
    async def delete_schema(name: str) -> None:
        """Delete a runtime schema. Built-in schemas cannot be deleted."""
        async with _schema_lock:
            _validate_schema_name(name)

            if name in _builtins:
                raise HTTPException(
                    status_code=403,
                    detail=_error_detail(
                        "PROTECTED_SCHEMA",
                        f"Schema '{name}' is a built-in schema and cannot be deleted.",
                        "Only runtime schemas created via POST /schemas can be deleted.",
                    ),
                )

            if name not in _registry and name not in _definitions:
                raise HTTPException(
                    status_code=404,
                    detail=_error_detail(
                        "SCHEMA_NOT_FOUND",
                        f"Schema '{name}' not found.",
                        "Use GET /schemas to list available schemas.",
                    ),
                )

            _registry.pop(name, None)
            _definitions.pop(name, None)
            if _store:
                _store.delete(name)

            logger.info("schema_deleted", schema_name=name)

    @router.post(
        "/upload",
        responses={
            400: {"model": ErrorDetail, "description": "Invalid data or sheet name"},
            422: {"model": ErrorDetail, "description": "Low confidence or schema validation error"},
            503: {"model": ErrorDetail, "description": "SLM unavailable"},
            500: {"model": ErrorDetail, "description": "Internal server error"},
        },
    )
    async def upload_file(
        file: UploadFile = File(...),
        sheet_name: str | None = Query(
            default=None, description="Sheet name for multi-sheet Excel files"
        ),
        cedent_id: str | None = Query(
            default=None, description="Cedent ID for correction cache lookup"
        ),
        schema: str | None = Query(
            default=None, description="Schema name to use (from GET /schemas)"
        ),
    ) -> ProcessingResult:
        """Upload a spreadsheet and map its headers to the target schema."""
        _validate_file(file)
        active_service = _resolve_service(schema)

        logger.info(
            "file_received",
            filename=file.filename,
            sheet_name=sheet_name,
            schema=schema,
        )
        start = time.monotonic()

        temp_path = _save_temp_file(file)
        try:
            result = await active_service.process_file(
                temp_path, sheet_name=sheet_name, cedent_id=cedent_id
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "mapping_complete",
                filename=file.filename,
                mapped_count=len(result.mapping.mappings),
                unmapped_count=len(result.mapping.unmapped_headers),
                valid_count=len(result.valid_records),
                error_count=len(result.errors),
                duration_ms=duration_ms,
            )
            return result
        except MappingConfidenceLowError as e:
            logger.warning("mapping_low_confidence", filename=file.filename, error=str(e))
            raise HTTPException(
                status_code=422,
                detail=_error_detail(
                    "LOW_CONFIDENCE",
                    str(e),
                    "Review the unmapped headers and consider providing more representative sample data.",
                ),
            ) from e
        except SchemaValidationError as e:
            logger.warning("schema_validation_error", filename=file.filename, error=str(e))
            raise HTTPException(
                status_code=422,
                detail=_error_detail(
                    "SCHEMA_VALIDATION",
                    str(e),
                    "Check that the source data matches the expected format for each target field.",
                ),
            ) from e
        except InvalidCedentDataError as e:
            logger.warning("invalid_cedent_data", filename=file.filename, error=str(e))
            raise HTTPException(
                status_code=400,
                detail=_error_detail(
                    "INVALID_DATA",
                    str(e),
                    "Ensure the file is a valid CSV or Excel spreadsheet with headers in the first row.",
                ),
            ) from e
        except SLMUnavailableError as e:
            logger.error("slm_unavailable", filename=file.filename, error=str(e))
            raise HTTPException(
                status_code=503,
                detail=_error_detail(
                    "SLM_UNAVAILABLE",
                    str(e),
                    "The mapping service is temporarily unavailable. Retry in a few seconds.",
                ),
            ) from e
        except InvalidCorrectionError as e:
            logger.warning("invalid_correction", filename=file.filename, error=str(e))
            raise HTTPException(
                status_code=422,
                detail=_error_detail(
                    "INVALID_CORRECTION",
                    str(e),
                    "The correction references a target field not in the active schema.",
                ),
            ) from e
        except ValueError as e:
            logger.warning("invalid_input", filename=file.filename, error=str(e))
            raise HTTPException(
                status_code=400,
                detail=_error_detail(
                    "INVALID_SHEET",
                    str(e),
                    "Check the sheet name and try again. Omit sheet_name to use the first sheet.",
                ),
            ) from e
        except RiskFlowError as e:
            logger.error("domain_error", filename=file.filename, error=str(e))
            raise HTTPException(
                status_code=500,
                detail=_error_detail(
                    "INTERNAL_ERROR", str(e), "Contact support if the problem persists."
                ),
            ) from e
        except Exception as e:
            logger.error("unexpected_error", filename=file.filename, error=str(e))
            raise HTTPException(
                status_code=500,
                detail=_error_detail(
                    "INTERNAL_ERROR",
                    "Internal server error",
                    "Contact support if the problem persists.",
                ),
            ) from e
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @router.post("/sheets")
    async def list_sheets(file: UploadFile = File(...)) -> SheetListResponse:
        """Upload a file and return its sheet names (Excel only)."""
        _validate_file(file)
        temp_path = _save_temp_file(file)
        try:
            names = mapping_service.get_sheet_names(temp_path)
            return SheetListResponse(sheets=names)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @router.post("/corrections", status_code=201)
    async def submit_corrections(request: CorrectionRequest) -> CorrectionStoredResponse:
        """Submit human-verified mapping corrections for a cedent."""
        if not request.cedent_id.strip():
            raise HTTPException(
                status_code=400,
                detail=_error_detail(
                    "INVALID_DATA",
                    "cedent_id must not be empty",
                    "Provide a non-blank cedent_id string.",
                ),
            )
        if not request.corrections:
            raise HTTPException(
                status_code=400,
                detail=_error_detail(
                    "INVALID_DATA",
                    "corrections list must not be empty",
                    "Provide at least one correction with source_header and target_field.",
                ),
            )

        for item in request.corrections:
            correction = Correction(
                cedent_id=request.cedent_id,
                source_header=item.source_header,
                target_field=item.target_field,
            )
            try:
                await mapping_service.store_correction(correction)
            except InvalidCorrectionError as e:
                raise HTTPException(
                    status_code=422,
                    detail=_error_detail(
                        "INVALID_CORRECTION",
                        str(e),
                        "The correction references a target field not in the active schema.",
                    ),
                ) from e

        logger.info(
            "corrections_submitted",
            cedent_id=request.cedent_id,
            count=len(request.corrections),
        )
        return CorrectionStoredResponse(stored=len(request.corrections))

    if session_store is not None:

        @router.post("/sessions", status_code=201)
        async def create_session(
            file: UploadFile = File(...),
            sheet_name: str | None = Query(
                default=None, description="Sheet name for multi-sheet Excel files"
            ),
            schema: str | None = Query(
                default=None, description="Schema name to use (from GET /schemas)"
            ),
        ) -> MappingSession:
            """Upload a file, get SLM suggestion + preview. Creates a session."""
            _validate_file(file)
            active_service = _resolve_service(schema)
            schema_name = (
                schema
                if schema and schema.strip()
                else next(
                    (name for name, svc in _registry.items() if svc is active_service),
                    "default",
                )
            )

            temp_path = _save_temp_file(file)
            try:
                headers = active_service.get_headers(temp_path, sheet_name=sheet_name)
                preview = active_service.get_preview(temp_path, sheet_name=sheet_name)
                suggestion = await active_service.suggest_mapping(headers, preview)

                # Resolve target fields from the schema definition
                schema_def = _definitions.get(schema_name)
                target_fields = sorted(schema_def.field_names) if schema_def else []

                session = MappingSession.create(
                    schema_name=schema_name,
                    file_path=temp_path,
                    sheet_name=sheet_name,
                    source_headers=headers,
                    target_fields=target_fields,
                    mappings=suggestion.mappings,
                    unmapped_headers=suggestion.unmapped_headers,
                    preview_rows=preview,
                )
                session_store.save(session)

                logger.info(
                    "session_created",
                    session_id=session.id,
                    schema_name=schema_name,
                    header_count=len(headers),
                    mapping_count=len(suggestion.mappings),
                )
                return session
            except (InvalidCedentDataError, ValueError) as e:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise HTTPException(
                    status_code=400,
                    detail=_error_detail(
                        "INVALID_DATA",
                        str(e),
                        "Ensure the file is a valid CSV or Excel spreadsheet with headers in the first row.",
                    ),
                ) from e
            except SLMUnavailableError as e:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise HTTPException(
                    status_code=503,
                    detail=_error_detail(
                        "SLM_UNAVAILABLE",
                        str(e),
                        "The mapping service is temporarily unavailable. Retry in a few seconds.",
                    ),
                ) from e
            except Exception as e:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                logger.error("session_create_error", error=str(e))
                raise HTTPException(
                    status_code=500,
                    detail=_error_detail(
                        "INTERNAL_ERROR",
                        "Internal server error",
                        "Contact support if the problem persists.",
                    ),
                ) from e

        @router.get("/sessions/{session_id}")
        async def get_session(session_id: str) -> MappingSession:
            """Return current session state."""
            session = session_store.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")
            return session

        @router.put("/sessions/{session_id}/mappings")
        async def update_session_mappings(
            session_id: str, body: UpdateMappingsRequest
        ) -> MappingSession:
            """Update the session's mappings with user-edited values."""
            session = session_store.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")

            try:
                session.update_mappings(
                    mappings=body.mappings,
                    unmapped_headers=body.unmapped_headers,
                )
            except (ValueError, TypeError) as e:
                raise HTTPException(
                    status_code=422,
                    detail=_error_detail(
                        "INVALID_MAPPING",
                        str(e),
                        "Check that all target fields are valid and not duplicated.",
                    ),
                ) from e

            session_store.save(session)
            return session

        @router.patch("/sessions/{session_id}/target-fields")
        async def extend_target_fields(
            session_id: str, body: ExtendTargetFieldsRequest
        ) -> MappingSession:
            """Add custom target fields to a session."""
            session = session_store.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")

            try:
                session.extend_target_fields(fields=body.fields)
            except ValueError as e:
                raise HTTPException(
                    status_code=422,
                    detail=_error_detail(
                        "INVALID_FIELDS",
                        str(e),
                        "Provide at least one non-empty field name.",
                    ),
                ) from e

            session_store.save(session)
            return session

        @router.post("/sessions/{session_id}/finalise")
        async def finalise_session(session_id: str) -> MappingSession:
            """Validate rows with the session's current mapping."""
            session = session_store.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")

            if session.status == SessionStatus.FINALISED:
                raise HTTPException(status_code=409, detail="Session already finalised")

            active_service = _resolve_service(session.schema_name)
            mapping_result = MappingResult(
                mappings=session.mappings,
                unmapped_headers=session.unmapped_headers,
            )

            try:
                processing_result = active_service.validate_rows_with_mapping(
                    session.file_path,
                    mapping_result,
                    sheet_name=session.sheet_name,
                )
            except Exception as e:
                logger.error("session_finalise_error", session_id=session_id, error=str(e))
                raise HTTPException(
                    status_code=500,
                    detail=_error_detail(
                        "INTERNAL_ERROR",
                        "Internal server error",
                        "Contact support if the problem persists.",
                    ),
                ) from e

            session.finalise(result=processing_result.model_dump())
            session_store.save(session)

            logger.info(
                "session_finalised",
                session_id=session_id,
                valid_count=len(processing_result.valid_records),
                error_count=len(processing_result.errors),
            )
            return session

        @router.delete("/sessions/{session_id}", status_code=204)
        async def delete_session(session_id: str) -> None:
            """Delete a session and clean up its temp file."""
            session = session_store.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")

            try:
                if os.path.exists(session.file_path):
                    os.remove(session.file_path)
            except OSError:
                logger.warning(
                    "session_file_cleanup_failed",
                    session_id=session_id,
                    file_path=session.file_path,
                )
            session_store.delete(session_id)

            logger.info("session_deleted", session_id=session_id)

    if job_store is not None:

        @router.post("/upload/async", status_code=202)
        async def upload_file_async(
            background_tasks: BackgroundTasks,
            file: UploadFile = File(...),
            sheet_name: str | None = Query(
                default=None,
                description="Sheet name for multi-sheet Excel files",
            ),
        ) -> AsyncJobResponse:
            """Accept a file for async processing, return job ID immediately."""
            _validate_file(file)

            job = Job.create(filename=file.filename)
            job_store.save(job)

            temp_path = _save_temp_file(file)
            logger.info(
                "async_job_created",
                job_id=job.id,
                filename=file.filename,
                sheet_name=sheet_name,
            )

            if async_backend == "tasks":
                task = asyncio.create_task(
                    _process_job(job, temp_path, sheet_name, mapping_service, job_store)
                )
                task.add_done_callback(_log_task_exception)
            else:
                background_tasks.add_task(
                    _process_job, job, temp_path, sheet_name, mapping_service, job_store
                )

            return AsyncJobResponse(job_id=job.id)

        @router.get("/jobs")
        async def list_jobs() -> JobListResponse:
            """List all async jobs with filename and upload date."""
            jobs = job_store.list_all()
            return JobListResponse(
                jobs=[
                    JobSummary(
                        job_id=j.id,
                        filename=j.filename,
                        created_at=j.created_at.isoformat(),
                        status=j.status.value,
                    )
                    for j in jobs
                ]
            )

        @router.get("/jobs/{job_id}")
        async def get_job_status(job_id: str) -> JobStatusResponse:
            """Get the status and result of an async job."""
            job = job_store.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Job not found")
            return JobStatusResponse(
                job_id=job.id,
                status=job.status.value,
                result=job.result,
                error=job.error,
                filename=job.filename,
                created_at=job.created_at.isoformat(),
            )

    return router


def _log_task_exception(task: asyncio.Task[None]) -> None:
    """Safety net: log unhandled exceptions from fire-and-forget tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        structlog.get_logger().error(
            "task_unhandled_exception",
            error=str(exc),
            error_type=type(exc).__name__,
        )


async def _process_job(
    job: Job,
    temp_path: str,
    sheet_name: str | None,
    mapping_service: MappingService,
    job_store: JobStorePort,
) -> None:
    """Background task that processes the file and updates the job."""
    logger = structlog.get_logger()
    start = time.monotonic()
    logger.info("task_started", job_id=job.id, filename=job.filename)
    job.start()
    job_store.save(job)
    try:
        result = await mapping_service.process_file(temp_path, sheet_name=sheet_name)
        job.complete(result=result.model_dump())
    except Exception as e:
        job.fail(error=str(e))
    finally:
        job_store.save(job)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "task_completed",
            job_id=job.id,
            duration_ms=duration_ms,
            status=job.status.value,
        )
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _error_detail(error_code: str, message: str, suggestion: str) -> dict[str, str]:
    """Build a structured error response body."""
    return ErrorDetail(
        error_code=error_code,
        message=message,
        suggestion=suggestion,
    ).model_dump()


def _validate_file(file: UploadFile) -> None:
    """Reject files with unsupported extensions or that exceed the size limit."""
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = file.file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File size {len(content)} bytes exceeds limit of {MAX_FILE_SIZE_BYTES} bytes",
        )
    # Reset file position so _save_temp_file can read it again
    file.file.seek(0)


def _save_temp_file(file: UploadFile) -> str:
    """Save uploaded file to a temp path and return the path."""
    suffix = os.path.splitext(file.filename or "upload")[1]
    with tempfile.NamedTemporaryFile(delete=False, prefix="riskflow_", suffix=suffix) as tmp:
        tmp.write(file.file.read())
        return tmp.name
