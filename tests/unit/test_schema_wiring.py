"""Tests for schema loader wiring in the composition root.

Loop 14: Wire YamlSchemaLoader into main.py so the app loads the
target schema from a YAML file at startup instead of relying solely
on the hardcoded DEFAULT_TARGET_SCHEMA.

Env var SCHEMA_PATH controls which file is loaded.
Falls back to schemas/default.yaml when unset.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


SCHEMAS_DIR = Path(__file__).parent.parent.parent / "schemas"
DEFAULT_SCHEMA_PATH = str(SCHEMAS_DIR / "default.yaml")


class TestSchemaLoaderWiring:
    """Composition root loads schema from YAML at startup."""

    def test_loads_schema_from_schema_path_env(self, tmp_path: Path) -> None:
        """When SCHEMA_PATH is set, the app loads that file."""
        schema_file = tmp_path / "custom.yaml"
        schema_file.write_text(
            """
name: custom_schema
fields:
  Policy_ID:
    type: string
    not_empty: true
  Premium:
    type: float
    non_negative: true
"""
        )
        with patch.dict(os.environ, {"SCHEMA_PATH": str(schema_file)}):
            from src.entrypoint.main import create_app

            app = create_app()
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200

    def test_falls_back_to_default_schema_when_no_env(self) -> None:
        """When SCHEMA_PATH is not set, loads schemas/default.yaml."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCHEMA_PATH", None)
            from src.entrypoint.main import create_app

            app = create_app()
            # App should start and be functional
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200

    def test_fails_to_start_with_nonexistent_schema_path(self) -> None:
        """InvalidSchemaError is raised at startup if the file doesn't exist."""
        from src.domain.model.errors import InvalidSchemaError

        with (
            patch.dict(os.environ, {"SCHEMA_PATH": "/nonexistent/schema.yaml"}),
            pytest.raises(InvalidSchemaError, match="not found"),
        ):
            from src.entrypoint.main import create_app

            create_app()

    def test_fails_to_start_with_invalid_yaml(self, tmp_path: Path) -> None:
        """InvalidSchemaError is raised if the YAML content is malformed."""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("{{not: valid: yaml: [}")

        from src.domain.model.errors import InvalidSchemaError

        with (
            patch.dict(os.environ, {"SCHEMA_PATH": str(bad_file)}),
            pytest.raises(InvalidSchemaError, match="parse"),
        ):
            from src.entrypoint.main import create_app

            create_app()

    def test_fails_to_start_with_invalid_schema_content(self, tmp_path: Path) -> None:
        """InvalidSchemaError is raised if the YAML is valid but schema is wrong."""
        invalid_schema = tmp_path / "invalid.yaml"
        invalid_schema.write_text(
            """
name: broken
fields:
  Amount:
    type: string
    non_negative: true
"""
        )

        from src.domain.model.errors import InvalidSchemaError

        with (
            patch.dict(os.environ, {"SCHEMA_PATH": str(invalid_schema)}),
            pytest.raises(InvalidSchemaError, match="Invalid schema"),
        ):
            from src.entrypoint.main import create_app

            create_app()

    def test_schema_passed_to_mapping_service(self, tmp_path: Path) -> None:
        """The loaded schema is injected into MappingService."""
        schema_file = tmp_path / "custom.yaml"
        schema_file.write_text(
            """
name: two_field_schema
fields:
  Policy_ID:
    type: string
    not_empty: true
  Premium:
    type: float
    non_negative: true
"""
        )
        with patch.dict(os.environ, {"SCHEMA_PATH": str(schema_file)}):
            with patch(
                "src.entrypoint.main.MappingService"
            ) as mock_service_class:
                from src.entrypoint.main import create_app

                create_app()
                # MappingService should have been called with schema kwarg
                call_kwargs = mock_service_class.call_args
                assert call_kwargs is not None
                schema = call_kwargs.kwargs.get("schema") or call_kwargs[1].get(
                    "schema"
                )
                assert schema is not None
                assert schema.name == "two_field_schema"
                assert "Policy_ID" in schema.field_names
                assert "Premium" in schema.field_names

    def test_schema_fingerprint_logged_at_startup(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Schema fingerprint appears in startup logs for audit trail."""
        schema_file = tmp_path / "custom.yaml"
        schema_file.write_text(
            """
name: logged_schema
fields:
  Policy_ID:
    type: string
    not_empty: true
"""
        )
        with patch.dict(os.environ, {"SCHEMA_PATH": str(schema_file)}):
            from src.entrypoint.main import create_app

            create_app()
            output = capsys.readouterr().out
            assert "schema_loaded" in output
            assert "logged_schema" in output

    def test_relative_schema_path_resolves(self) -> None:
        """A relative SCHEMA_PATH resolves from the working directory."""
        with patch.dict(
            os.environ, {"SCHEMA_PATH": "schemas/default.yaml"}
        ):
            from src.entrypoint.main import create_app

            app = create_app()
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200
