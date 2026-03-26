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
import tempfile
import time

import structlog
from fastapi import APIRouter, File, HTTPException, UploadFile

from src.domain.model.errors import (
    InvalidCedentDataError,
    MappingConfidenceLowError,
    RiskFlowError,
    SchemaValidationError,
    SLMUnavailableError,
)
from src.domain.service.mapping_service import MappingService

logger = structlog.get_logger()

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB


def create_router(mapping_service: MappingService) -> APIRouter:
    """Create a FastAPI router wired to the given MappingService.

    The service is injected — the router never constructs adapters itself.
    This keeps the HTTP adapter decoupled from concrete implementations.
    """
    router = APIRouter()

    @router.post("/upload")
    async def upload_file(file: UploadFile = File(...)) -> dict:
        """Upload a spreadsheet and map its headers to the target schema."""
        _validate_file(file)

        logger.info("file_received", filename=file.filename)
        start = time.monotonic()

        temp_path = _save_temp_file(file)
        try:
            result = await mapping_service.process_file(temp_path)
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "mapping_complete",
                filename=file.filename,
                mapped_count=len(result.mappings),
                unmapped_count=len(result.unmapped_headers),
                duration_ms=duration_ms,
            )
            return result.model_dump()
        except MappingConfidenceLowError as e:
            logger.warning(
                "mapping_low_confidence", filename=file.filename, error=str(e)
            )
            raise HTTPException(status_code=422, detail=str(e)) from e
        except SchemaValidationError as e:
            logger.warning(
                "schema_validation_error", filename=file.filename, error=str(e)
            )
            raise HTTPException(status_code=422, detail=str(e)) from e
        except InvalidCedentDataError as e:
            logger.warning("invalid_cedent_data", filename=file.filename, error=str(e))
            raise HTTPException(status_code=400, detail=str(e)) from e
        except SLMUnavailableError as e:
            logger.error("slm_unavailable", filename=file.filename, error=str(e))
            raise HTTPException(status_code=503, detail=str(e)) from e
        except RiskFlowError as e:
            logger.error("domain_error", filename=file.filename, error=str(e))
            raise HTTPException(status_code=500, detail=str(e)) from e
        except Exception as e:
            logger.error("unexpected_error", filename=file.filename, error=str(e))
            raise HTTPException(status_code=500, detail="Internal server error") from e
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    return router


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
