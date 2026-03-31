"""Tests for per-request schema selection via query param.

Loop 15: Users can select which target schema to use when uploading.
Schemas are loaded from the schemas/ directory at startup and indexed
by name. The ?schema= query param selects one. Default is used when
omitted.

Security: only schema names are accepted, not file paths. Path
traversal attempts are rejected.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.domain.model.schema import (
    ColumnMapping,
    ConfidenceReport,
    MappingResult,
    ProcessingResult,
)


def _make_mock_service(schema_name: str = "default") -> MagicMock:
    """Create a mock MappingService that returns a valid ProcessingResult."""
    service = MagicMock()
    mapping = MappingResult(
        mappings=[
            ColumnMapping(
                source_header="Col1", target_field="Policy_ID", confidence=0.95
            )
        ],
        unmapped_headers=[],
    )
    service.process_file = AsyncMock(
        return_value=ProcessingResult(
            mapping=mapping,
            confidence_report=ConfidenceReport(
                min_confidence=0.95,
                avg_confidence=0.95,
                low_confidence_fields=[],
                missing_fields=[],
            ),
            valid_records=[],
            invalid_records=[],
            errors=[],
        )
    )
    return service


class TestSchemaSelection:
    """Schema selection via ?schema= query param on /upload."""

    def test_upload_with_schema_param_uses_named_schema(
        self, tmp_path: Path
    ) -> None:
        """When ?schema=custom is passed, the service for that schema is used."""
        from src.adapters.http.routes import create_router

        default_service = _make_mock_service("default")
        custom_service = _make_mock_service("custom")
        schema_registry = {
            "standard_reinsurance": default_service,
            "custom": custom_service,
        }

        router = create_router(
            default_service,
            schema_registry=schema_registry,
        )
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        csv_content = b"Col1\nval1"
        response = client.post(
            "/upload?schema=custom",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        assert response.status_code == 200
        custom_service.process_file.assert_called_once()
        default_service.process_file.assert_not_called()

    def test_upload_without_schema_param_uses_default(self) -> None:
        """When ?schema= is omitted, the default service is used."""
        from src.adapters.http.routes import create_router

        default_service = _make_mock_service("default")
        custom_service = _make_mock_service("custom")
        schema_registry = {
            "standard_reinsurance": default_service,
            "custom": custom_service,
        }

        router = create_router(
            default_service,
            schema_registry=schema_registry,
        )
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        csv_content = b"Col1\nval1"
        response = client.post(
            "/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        assert response.status_code == 200
        default_service.process_file.assert_called_once()

    def test_upload_with_nonexistent_schema_returns_404(self) -> None:
        """When ?schema=unknown is passed, 404 is returned."""
        from src.adapters.http.routes import create_router

        default_service = _make_mock_service()
        schema_registry = {"standard_reinsurance": default_service}

        router = create_router(
            default_service,
            schema_registry=schema_registry,
        )
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        csv_content = b"Col1\nval1"
        response = client.post(
            "/upload?schema=nonexistent",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        assert response.status_code == 404
        assert "nonexistent" in response.json()["detail"]["message"]

    def test_get_schemas_lists_available(self) -> None:
        """GET /schemas returns all loaded schema names."""
        from src.adapters.http.routes import create_router

        default_service = _make_mock_service()
        custom_service = _make_mock_service()
        schema_registry = {
            "standard_reinsurance": default_service,
            "marine": custom_service,
        }

        router = create_router(
            default_service,
            schema_registry=schema_registry,
        )
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/schemas")
        assert response.status_code == 200
        schemas = response.json()["schemas"]
        assert sorted(schemas) == ["marine", "standard_reinsurance"]

    @pytest.mark.parametrize(
        "schema_param",
        [
            "../../etc/passwd",
            "../schemas/default",
            "/etc/shadow",
            "..%2f..%2fetc%2fpasswd",
        ],
    )
    def test_path_traversal_rejected(self, schema_param: str) -> None:
        """Path traversal attempts in ?schema= are rejected with 400."""
        from src.adapters.http.routes import create_router

        default_service = _make_mock_service()
        schema_registry = {"standard_reinsurance": default_service}

        router = create_router(
            default_service,
            schema_registry=schema_registry,
        )
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        csv_content = b"Col1\nval1"
        response = client.post(
            f"/upload?schema={schema_param}",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        assert response.status_code == 400
        assert "invalid" in response.json()["detail"]["message"].lower()

    def test_schema_name_with_spaces_rejected(self) -> None:
        """Schema names with whitespace are rejected."""
        from src.adapters.http.routes import create_router

        default_service = _make_mock_service()
        schema_registry = {"standard_reinsurance": default_service}

        router = create_router(
            default_service,
            schema_registry=schema_registry,
        )
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        csv_content = b"Col1\nval1"
        response = client.post(
            "/upload?schema=my schema",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        assert response.status_code == 400

    def test_empty_schema_param_uses_default(self) -> None:
        """An empty ?schema= falls through to the default service."""
        from src.adapters.http.routes import create_router

        default_service = _make_mock_service()
        schema_registry = {"standard_reinsurance": default_service}

        router = create_router(
            default_service,
            schema_registry=schema_registry,
        )
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        csv_content = b"Col1\nval1"
        response = client.post(
            "/upload?schema=",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        assert response.status_code == 200
        default_service.process_file.assert_called_once()
