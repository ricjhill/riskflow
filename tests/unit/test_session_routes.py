"""Tests for interactive mapping session endpoints.

POST /sessions — upload file, get SLM suggestion + preview.
GET /sessions/{id} — retrieve current session state.
PUT /sessions/{id}/mappings — user edits mappings.
POST /sessions/{id}/finalise — validate rows with user's mapping.
DELETE /sessions/{id} — cleanup temp file + Redis.

Tests use FastAPI TestClient with mocked MappingService.
"""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.adapters.http.routes import create_router
from src.adapters.parsers.ingestor import PolarsIngestor
from src.adapters.storage.session_store import NullMappingSessionStore
from src.domain.model.schema import ColumnMapping, MappingResult
from src.domain.model.session import MappingSession, SessionStatus
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


def _make_mapping_result() -> MappingResult:
    return MappingResult(
        mappings=[
            ColumnMapping(source_header="id_col", target_field="ID", confidence=0.95),
            ColumnMapping(source_header="amount_col", target_field="Amount", confidence=0.90),
        ],
        unmapped_headers=["extra_col"],
    )


def _make_service() -> MappingService:
    mapper = AsyncMock()
    mapper.map_headers.return_value = _make_mapping_result()
    cache = MagicMock()
    cache.get_mapping.return_value = None
    return MappingService(
        ingestor=PolarsIngestor(),
        mapper=mapper,
        cache=cache,
        schema=_make_schema("default"),
    )


def _make_session_store() -> MagicMock:
    """A mock session store that stores sessions in a dict."""
    store = MagicMock()
    sessions: dict[str, MappingSession] = {}

    def save(session: MappingSession) -> None:
        sessions[session.id] = session

    def get(session_id: str) -> MappingSession | None:
        return sessions.get(session_id)

    def delete(session_id: str) -> None:
        sessions.pop(session_id, None)

    store.save = MagicMock(side_effect=save)
    store.get = MagicMock(side_effect=get)
    store.delete = MagicMock(side_effect=delete)
    store._sessions = sessions
    return store


@pytest.fixture
def session_store() -> MagicMock:
    return _make_session_store()


@pytest.fixture
def client(session_store: MagicMock) -> TestClient:
    """TestClient with session endpoints enabled."""
    schema = _make_schema("default")
    service = _make_service()
    registry: dict[str, MappingService] = {"default": service}

    router = create_router(
        service,
        schema_registry=registry,
        schema_definitions={"default": schema},
        session_store=session_store,
    )

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _upload_csv(
    client: TestClient, csv_content: str = "id_col,amount_col,extra_col\nP001,1000,x\n"
) -> dict:
    """Helper to POST /sessions with a CSV file."""
    return client.post(
        "/sessions",
        files={"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    ).json()


class TestPostSessions:
    """POST /sessions — upload file, get SLM suggestion + preview."""

    def test_returns_201_with_session(self, client: TestClient) -> None:
        resp = client.post(
            "/sessions",
            files={
                "file": (
                    "test.csv",
                    io.BytesIO(b"id_col,amount_col,extra_col\nP001,1000,x\n"),
                    "text/csv",
                )
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["status"] == "created"
        assert data["schema_name"] == "default"
        assert "source_headers" in data
        assert "target_fields" in data
        assert "mappings" in data
        assert "unmapped_headers" in data
        assert "preview_rows" in data
        assert data["result"] is None

    def test_includes_slm_suggested_mappings(self, client: TestClient) -> None:
        data = _upload_csv(client)
        assert len(data["mappings"]) == 2
        targets = {m["target_field"] for m in data["mappings"]}
        assert "ID" in targets
        assert "Amount" in targets

    def test_includes_source_headers(self, client: TestClient) -> None:
        data = _upload_csv(client)
        assert "id_col" in data["source_headers"]
        assert "amount_col" in data["source_headers"]
        assert "extra_col" in data["source_headers"]

    def test_includes_target_fields_from_schema(self, client: TestClient) -> None:
        data = _upload_csv(client)
        assert set(data["target_fields"]) == {"ID", "Amount"}

    def test_includes_preview_rows(self, client: TestClient) -> None:
        data = _upload_csv(client)
        assert len(data["preview_rows"]) >= 1

    def test_with_schema_param(self, client: TestClient) -> None:
        resp = client.post(
            "/sessions?schema=default",
            files={"file": ("test.csv", io.BytesIO(b"id_col,amount_col\nP001,1000\n"), "text/csv")},
        )
        assert resp.status_code == 201
        assert resp.json()["schema_name"] == "default"

    def test_bad_file_extension_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/sessions",
            files={"file": ("test.txt", io.BytesIO(b"data"), "text/plain")},
        )
        assert resp.status_code == 400

    def test_unknown_schema_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/sessions?schema=nonexistent",
            files={"file": ("test.csv", io.BytesIO(b"a\n1\n"), "text/csv")},
        )
        assert resp.status_code == 404

    def test_session_persisted_to_store(self, client: TestClient, session_store: MagicMock) -> None:
        _upload_csv(client)
        session_store.save.assert_called_once()
        saved = session_store.save.call_args[0][0]
        assert isinstance(saved, MappingSession)
        assert saved.status == SessionStatus.CREATED
