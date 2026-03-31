"""FastAPI HTTP adapter routes.

Maps domain operations to HTTP endpoints and domain errors to HTTP status
codes. The route handler is a thin adapter — all business logic lives in
MappingService. Logging happens here at the adapter boundary.

Error mapping:
- InvalidCedentDataError → 400 Bad Request
- MappingConfidenceLowError → 422 Unprocessable Entity
- SchemaValidationError → 422 Unprocessable Entity
- SLMUnavailableError → 503 Service Unavailable
- Unexpected errors → 500 Internal Server Error
"""

import os
import re
import tempfile
import time

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
from src.domain.service.mapping_service import MappingService
from src.ports.output.job_store import JobStorePort

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
) -> APIRouter:
    """Create a FastAPI router wired to the given MappingService.

    The service is injected — the router never constructs adapters itself.
    This keeps the HTTP adapter decoupled from concrete implementations.
    job_store is optional — async endpoints are only available when provided.
    schema_registry maps schema names to MappingService instances. When
    ?schema= is provided, the named service is used instead of the default.
    """
    router = APIRouter()
    _registry = schema_registry or {}

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
    async def list_schemas() -> dict[str, object]:
        """List all available schema names."""
        return {"schemas": sorted(_registry.keys())}

    @router.post("/upload")
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
    ) -> dict[str, object]:
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
            return result.model_dump()
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
    async def list_sheets(file: UploadFile = File(...)) -> dict[str, object]:
        """Upload a file and return its sheet names (Excel only)."""
        _validate_file(file)
        temp_path = _save_temp_file(file)
        try:
            names = mapping_service.get_sheet_names(temp_path)
            return {"sheets": names}
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @router.post("/corrections", status_code=201)
    async def submit_corrections(request: CorrectionRequest) -> dict[str, object]:
        """Submit human-verified mapping corrections for a cedent."""
        if not request.cedent_id.strip():
            raise HTTPException(status_code=400, detail="cedent_id must not be empty")
        if not request.corrections:
            raise HTTPException(status_code=400, detail="corrections list must not be empty")

        for item in request.corrections:
            correction = Correction(
                cedent_id=request.cedent_id,
                source_header=item.source_header,
                target_field=item.target_field,
            )
            try:
                mapping_service.store_correction(correction)
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
        return {"stored": len(request.corrections)}

    if job_store is not None:

        @router.post("/upload/async", status_code=202)
        async def upload_file_async(
            background_tasks: BackgroundTasks,
            file: UploadFile = File(...),
            sheet_name: str | None = Query(
                default=None,
                description="Sheet name for multi-sheet Excel files",
            ),
        ) -> dict[str, object]:
            """Accept a file for async processing, return job ID immediately."""
            _validate_file(file)

            job = Job.create()
            job_store.save(job)

            temp_path = _save_temp_file(file)
            logger.info(
                "async_job_created",
                job_id=job.id,
                filename=file.filename,
                sheet_name=sheet_name,
            )

            background_tasks.add_task(
                _process_job, job, temp_path, sheet_name, mapping_service, job_store
            )

            return {"job_id": job.id}

        @router.get("/jobs/{job_id}")
        async def get_job_status(job_id: str) -> dict[str, object]:
            """Get the status and result of an async job."""
            job = job_store.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Job not found")
            return {
                "job_id": job.id,
                "status": job.status.value,
                "result": job.result,
                "error": job.error,
            }

    return router


async def _process_job(
    job: Job,
    temp_path: str,
    sheet_name: str | None,
    mapping_service: MappingService,
    job_store: JobStorePort,
) -> None:
    """Background task that processes the file and updates the job."""
    job.start()
    job_store.save(job)
    try:
        result = await mapping_service.process_file(temp_path, sheet_name=sheet_name)
        job.complete(result=result.model_dump())
    except Exception as e:
        job.fail(error=str(e))
    finally:
        job_store.save(job)
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _error_detail(error_code: str, message: str, suggestion: str) -> dict[str, str]:
    """Build a structured error response body."""
    return {
        "error_code": error_code,
        "message": message,
        "suggestion": suggestion,
    }


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
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        return tmp.name
