"""Tests for schema CRUD endpoints: GET/POST/DELETE /schemas/{name}.

These endpoints allow runtime schema management — add custom schemas
and delete them without restarting the service. Built-in schemas
loaded from YAML at startup are protected from deletion.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.adapters.http.routes import create_router
from src.adapters.parsers.ingestor import PolarsIngestor
from src.adapters.storage.schema_store import NullSchemaStore
from src.domain.model.schema import ColumnMapping, MappingResult
from src.domain.model.target_schema import FieldDefinition, FieldType, TargetSchema
from src.domain.service.mapping_service import MappingService


def _make_schema(name: str = "test_schema") -> TargetSchema:
    return TargetSchema(
        name=name,
        fields={
            "ID": FieldDefinition(type=FieldType.STRING, not_empty=True),
            "Amount": FieldDefinition(type=FieldType.FLOAT, non_negative=True),
        },
    )


def _make_service(schema: TargetSchema | None = None) -> MappingService:
    mapper = AsyncMock()
    mapper.map_headers.return_value = MappingResult(
        mappings=[
            ColumnMapping(source_header="ID", target_field="ID", confidence=0.95),
        ],
        unmapped_headers=[],
    )
    cache = MagicMock()
    cache.get_mapping.return_value = None
    return MappingService(
        ingestor=PolarsIngestor(),
        mapper=mapper,
        cache=cache,
        schema=schema or _make_schema("default"),
    )


def _service_factory(schema: TargetSchema) -> MappingService:
    """Test factory that creates a MappingService for any schema."""
    return _make_service(schema)


@pytest.fixture
def client() -> TestClient:
    """TestClient with CRUD endpoints enabled."""
    default_schema = _make_schema("builtin_schema")
    default_service = _make_service(default_schema)
    registry: dict[str, MappingService] = {"builtin_schema": default_service}
    definitions: dict[str, TargetSchema] = {"builtin_schema": default_schema}

    router = create_router(
        default_service,
        schema_registry=registry,
        schema_definitions=definitions,
        builtin_schema_names={"builtin_schema"},
        schema_store=NullSchemaStore(),
        service_factory=_service_factory,
    )

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestGetSchemaByName:
    """GET /schemas/{name} — view a schema's full definition."""

    def test_returns_known_schema(self, client: TestClient) -> None:
        resp = client.get("/schemas/builtin_schema")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "builtin_schema"
        assert "ID" in body["fields"]
        assert "Amount" in body["fields"]

    def test_returns_404_for_unknown(self, client: TestClient) -> None:
        resp = client.get("/schemas/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.parametrize("bad_name", ["a b", "x;y", "bad!name"])
    def test_rejects_invalid_name(self, client: TestClient, bad_name: str) -> None:
        resp = client.get(f"/schemas/{bad_name}")
        assert resp.status_code == 400


class TestPostSchema:
    """POST /schemas — create a new runtime schema."""

    def test_creates_schema(self, client: TestClient) -> None:
        schema_data = {
            "name": "new_schema",
            "fields": {
                "Policy": {"type": "string", "not_empty": True},
                "Premium": {"type": "float", "non_negative": True},
            },
        }
        resp = client.post("/schemas", json=schema_data)
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "new_schema"
        assert "fingerprint" in body

    def test_appears_in_list_after_creation(self, client: TestClient) -> None:
        schema_data = {
            "name": "added_schema",
            "fields": {"X": {"type": "string"}},
        }
        client.post("/schemas", json=schema_data)
        resp = client.get("/schemas")
        assert "added_schema" in resp.json()["schemas"]

    def test_retrievable_by_name_after_creation(self, client: TestClient) -> None:
        schema_data = {
            "name": "retrievable",
            "fields": {"Y": {"type": "float"}},
        }
        client.post("/schemas", json=schema_data)
        resp = client.get("/schemas/retrievable")
        assert resp.status_code == 200
        assert resp.json()["name"] == "retrievable"

    def test_rejects_invalid_schema(self, client: TestClient) -> None:
        resp = client.post("/schemas", json={"name": "bad"})
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        "bad_name",
        ["../etc/passwd", "schema with spaces", "schema;drop", ""],
        ids=["path-traversal", "spaces", "semicolon", "empty"],
    )
    def test_rejects_invalid_name_in_body(self, client: TestClient, bad_name: str) -> None:
        resp = client.post(
            "/schemas",
            json={"name": bad_name, "fields": {"X": {"type": "string"}}},
        )
        assert resp.status_code in (400, 422)

    def test_rejects_duplicate_name(self, client: TestClient) -> None:
        resp = client.post(
            "/schemas",
            json={
                "name": "builtin_schema",
                "fields": {"Z": {"type": "string"}},
            },
        )
        assert resp.status_code == 409

    def test_rejects_empty_body(self, client: TestClient) -> None:
        resp = client.post("/schemas", json={})
        assert resp.status_code == 422


class TestDeleteSchema:
    """DELETE /schemas/{name} — remove a runtime schema."""

    def test_deletes_runtime_schema(self, client: TestClient) -> None:
        # First create one
        client.post(
            "/schemas",
            json={"name": "deletable", "fields": {"A": {"type": "string"}}},
        )
        # Then delete it
        resp = client.delete("/schemas/deletable")
        assert resp.status_code == 204

        # Gone from list
        schemas = client.get("/schemas").json()["schemas"]
        assert "deletable" not in schemas

    def test_rejects_delete_builtin(self, client: TestClient) -> None:
        resp = client.delete("/schemas/builtin_schema")
        assert resp.status_code == 403

    def test_rejects_delete_unknown(self, client: TestClient) -> None:
        resp = client.delete("/schemas/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.parametrize("bad_name", ["a b", "x;y", "bad!name"])
    def test_rejects_delete_invalid_name(self, client: TestClient, bad_name: str) -> None:
        resp = client.delete(f"/schemas/{bad_name}")
        assert resp.status_code == 400
