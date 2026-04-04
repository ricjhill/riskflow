"""Tests for tools/export_openapi.py — OpenAPI spec export."""

import json
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def _load_spec(tmp_path: Path) -> dict:
    """Export the OpenAPI spec and return it as a dict."""
    output = tmp_path / "openapi.json"
    with patch.dict(
        "os.environ",
        {"REDIS_URL": "", "GROQ_API_KEY": ""},
        clear=False,
    ):
        from tools.export_openapi import main

        main(str(output))
    return json.loads(output.read_text())


class TestExportOpenapi:
    """Verify the export script produces a valid OpenAPI spec."""

    def test_export_creates_openapi_json(self, tmp_path: Path) -> None:
        """Running main() writes a valid OpenAPI JSON file."""
        spec = _load_spec(tmp_path)
        assert "openapi" in spec
        assert "paths" in spec

    def test_spec_contains_all_endpoints(self, tmp_path: Path) -> None:
        """The exported spec includes every registered route."""
        spec = _load_spec(tmp_path)
        paths = spec["paths"]

        expected_paths = [
            "/health",
            "/schemas",
            "/schemas/{name}",
            "/upload",
            "/upload/async",
            "/sheets",
            "/corrections",
            "/sessions",
            "/sessions/{session_id}",
            "/sessions/{session_id}/mappings",
            "/sessions/{session_id}/target-fields",
            "/sessions/{session_id}/finalise",
            "/jobs/{job_id}",
        ]

        for path in expected_paths:
            assert path in paths, f"Missing endpoint: {path}"

    def test_spec_has_info_metadata(self, tmp_path: Path) -> None:
        """The spec includes title and version in the info block."""
        spec = _load_spec(tmp_path)
        assert spec["info"]["title"] == "RiskFlow API"
        assert "version" in spec["info"]


class TestResponseModelSchemas:
    """Verify the spec contains typed component schemas, not generic objects."""

    def test_spec_includes_domain_model_schemas(self, tmp_path: Path) -> None:
        """Core domain Pydantic models appear as component schemas."""
        spec = _load_spec(tmp_path)
        components = spec.get("components", {}).get("schemas", {})

        expected_models = [
            "ProcessingResult",
            "MappingResult",
            "ColumnMapping",
            "ConfidenceReport",
            "RowError",
            "MappingSession",
        ]
        for model in expected_models:
            assert model in components, f"Missing component schema: {model}"

    def test_spec_includes_response_models(self, tmp_path: Path) -> None:
        """Ad-hoc response models appear as component schemas."""
        spec = _load_spec(tmp_path)
        components = spec.get("components", {}).get("schemas", {})

        expected_models = [
            "SchemaListResponse",
            "SheetListResponse",
            "CorrectionStoredResponse",
            "SchemaCreatedResponse",
            "AsyncJobResponse",
            "JobStatusResponse",
            "HealthResponse",
            "ErrorDetail",
        ]
        for model in expected_models:
            assert model in components, f"Missing component schema: {model}"

    def test_spec_includes_request_models(self, tmp_path: Path) -> None:
        """Request body models appear as component schemas."""
        spec = _load_spec(tmp_path)
        components = spec.get("components", {}).get("schemas", {})

        expected_models = [
            "CorrectionRequest",
            "CorrectionItem",
            "UpdateMappingsRequest",
            "ExtendTargetFieldsRequest",
        ]
        for model in expected_models:
            assert model in components, f"Missing component schema: {model}"

    def test_upload_response_references_processing_result(self, tmp_path: Path) -> None:
        """POST /upload 200 response references ProcessingResult, not generic object."""
        spec = _load_spec(tmp_path)
        upload = spec["paths"]["/upload"]["post"]
        ok_response = upload["responses"]["200"]
        schema = ok_response["content"]["application/json"]["schema"]
        assert "$ref" in schema, "POST /upload should return a $ref to ProcessingResult"
        assert "ProcessingResult" in schema["$ref"]

    def test_session_endpoints_reference_mapping_session(self, tmp_path: Path) -> None:
        """Session endpoints reference MappingSession, not generic object."""
        spec = _load_spec(tmp_path)

        session_paths = [
            ("/sessions", "post", "201"),
            ("/sessions/{session_id}", "get", "200"),
            ("/sessions/{session_id}/mappings", "put", "200"),
            ("/sessions/{session_id}/target-fields", "patch", "200"),
            ("/sessions/{session_id}/finalise", "post", "200"),
        ]
        for path, method, status in session_paths:
            response = spec["paths"][path][method]["responses"][status]
            schema = response["content"]["application/json"]["schema"]
            assert "$ref" in schema, (
                f"{method.upper()} {path} should return a $ref to MappingSession"
            )
            assert "MappingSession" in schema["$ref"]

    def test_job_status_response_has_typed_fields(self, tmp_path: Path) -> None:
        """GET /jobs/{job_id} response has specific fields, not generic object."""
        spec = _load_spec(tmp_path)
        components = spec.get("components", {}).get("schemas", {})
        job_schema = components.get("JobStatusResponse", {})
        properties = job_schema.get("properties", {})
        assert "job_id" in properties
        assert "status" in properties
        assert "result" in properties
        assert "error" in properties

    def test_error_detail_schema_has_structured_fields(self, tmp_path: Path) -> None:
        """ErrorDetail schema has error_code, message, suggestion."""
        spec = _load_spec(tmp_path)
        components = spec.get("components", {}).get("schemas", {})
        error_schema = components.get("ErrorDetail", {})
        properties = error_schema.get("properties", {})
        assert "error_code" in properties
        assert "message" in properties
        assert "suggestion" in properties


class TestCommittedSpecStaleness:
    """Verify the committed openapi.json matches the live app."""

    def test_committed_spec_matches_live_app(self, tmp_path: Path) -> None:
        """openapi.json in the repo root must match what the app generates."""
        committed = ROOT / "openapi.json"
        if not committed.exists():
            return  # skip if not yet committed (e.g. first run)

        live_spec = _load_spec(tmp_path)
        committed_spec = json.loads(committed.read_text())
        assert live_spec == committed_spec, (
            "openapi.json is stale — run: uv run python -m tools.export_openapi"
        )
