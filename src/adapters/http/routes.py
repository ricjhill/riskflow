"""FastAPI HTTP adapter routes.

Maps domain operations to HTTP endpoints and domain errors to HTTP status
codes. The route handler is a thin adapter — all business logic lives in
MappingService.

Error mapping:
- InvalidCedentDataError → 400 Bad Request
- MappingConfidenceLowError → 422 Unprocessable Entity
- SchemaValidationError → 422 Unprocessable Entity
- SLMUnavailableError → 503 Service Unavailable
- Unexpected errors → 500 Internal Server Error
"""

import os
import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.domain.model.errors import (
    InvalidCedentDataError,
    MappingConfidenceLowError,
    RiskFlowError,
    SchemaValidationError,
    SLMUnavailableError,
)
from src.domain.service.mapping_service import MappingService


def create_router(mapping_service: MappingService) -> APIRouter:
    """Create a FastAPI router wired to the given MappingService.

    The service is injected — the router never constructs adapters itself.
    This keeps the HTTP adapter decoupled from concrete implementations.
    """
    router = APIRouter()

    @router.post("/upload")
    async def upload_file(file: UploadFile = File(...)) -> dict:
        """Upload a spreadsheet and map its headers to the target schema."""
        temp_path = _save_temp_file(file)
        try:
            result = await mapping_service.process_file(temp_path)
            return result.model_dump()
        except MappingConfidenceLowError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        except SchemaValidationError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        except InvalidCedentDataError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except SLMUnavailableError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        except RiskFlowError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail="Internal server error") from e
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    return router


def _save_temp_file(file: UploadFile) -> str:
    """Save uploaded file to a temp path and return the path."""
    suffix = os.path.splitext(file.filename or "upload")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        return tmp.name
