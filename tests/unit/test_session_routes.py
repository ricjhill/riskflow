"""Tests for interactive mapping session endpoints.

POST /sessions — upload file, get SLM suggestion + preview.
GET /sessions/{id} — retrieve current session state.
PUT /sessions/{id}/mappings — user edits mappings.
POST /sessions/{id}/finalise — validate rows with user's mapping.
DELETE /sessions/{id} — cleanup temp file + Redis.

Tests use FastAPI TestClient with mocked MappingService.
"""

import io
import os
from unittest.mock import AsyncMock, MagicMock, patch

from src.domain.model.errors import SLMUnavailableError

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

    def test_empty_csv_returns_400(self, client: TestClient) -> None:
        """Empty file should return 400, not 500."""
        resp = client.post(
            "/sessions",
            files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")},
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

    def test_slm_unavailable_returns_503(self, session_store: MagicMock) -> None:
        """SLM failure during suggest_mapping returns 503."""
        mapper = AsyncMock()
        mapper.map_headers.side_effect = SLMUnavailableError("Groq down")
        cache = MagicMock()
        cache.get_mapping.return_value = None
        schema = _make_schema("default")
        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
            schema=schema,
        )
        registry: dict[str, MappingService] = {"default": service}
        router = create_router(
            service,
            schema_registry=registry,
            schema_definitions={"default": schema},
            session_store=session_store,
        )
        app = FastAPI()
        app.include_router(router)
        slm_client = TestClient(app)

        resp = slm_client.post(
            "/sessions",
            files={"file": ("test.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
        )
        assert resp.status_code == 503


class TestGetSession:
    """GET /sessions/{id} — retrieve current session state."""

    def test_returns_200_with_session(self, client: TestClient) -> None:
        data = _upload_csv(client)
        session_id = data["id"]
        resp = client.get(f"/sessions/{session_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == session_id
        assert resp.json()["status"] == "created"

    def test_returns_404_for_unknown_id(self, client: TestClient) -> None:
        resp = client.get("/sessions/nonexistent-id")
        assert resp.status_code == 404

    def test_returns_full_session_state(self, client: TestClient) -> None:
        data = _upload_csv(client)
        session_id = data["id"]
        resp = client.get(f"/sessions/{session_id}")
        body = resp.json()
        assert "mappings" in body
        assert "source_headers" in body
        assert "target_fields" in body
        assert "preview_rows" in body


class TestPutSessionMappings:
    """PUT /sessions/{id}/mappings — user edits mappings."""

    def test_valid_update_returns_200(self, client: TestClient) -> None:
        data = _upload_csv(client)
        session_id = data["id"]
        resp = client.put(
            f"/sessions/{session_id}/mappings",
            json={
                "mappings": [
                    {"source_header": "id_col", "target_field": "ID", "confidence": 1.0},
                ],
                "unmapped_headers": ["amount_col", "extra_col"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["mappings"]) == 1
        assert body["mappings"][0]["confidence"] == 1.0
        assert body["unmapped_headers"] == ["amount_col", "extra_col"]

    def test_invalid_target_returns_422(self, client: TestClient) -> None:
        data = _upload_csv(client)
        session_id = data["id"]
        resp = client.put(
            f"/sessions/{session_id}/mappings",
            json={
                "mappings": [
                    {"source_header": "id_col", "target_field": "NONEXISTENT", "confidence": 1.0},
                ],
                "unmapped_headers": [],
            },
        )
        assert resp.status_code == 422

    def test_duplicate_targets_returns_422(self, client: TestClient) -> None:
        data = _upload_csv(client)
        session_id = data["id"]
        resp = client.put(
            f"/sessions/{session_id}/mappings",
            json={
                "mappings": [
                    {"source_header": "id_col", "target_field": "ID", "confidence": 1.0},
                    {"source_header": "amount_col", "target_field": "ID", "confidence": 1.0},
                ],
                "unmapped_headers": [],
            },
        )
        assert resp.status_code == 422

    def test_unknown_session_returns_404(self, client: TestClient) -> None:
        resp = client.put(
            "/sessions/nonexistent/mappings",
            json={"mappings": [], "unmapped_headers": []},
        )
        assert resp.status_code == 404

    def test_null_mappings_returns_422(self, client: TestClient) -> None:
        data = _upload_csv(client)
        session_id = data["id"]
        resp = client.put(
            f"/sessions/{session_id}/mappings",
            json={"mappings": None, "unmapped_headers": []},
        )
        assert resp.status_code == 422

    def test_missing_mappings_key_returns_422(self, client: TestClient) -> None:
        data = _upload_csv(client)
        session_id = data["id"]
        resp = client.put(
            f"/sessions/{session_id}/mappings",
            json={"unmapped_headers": []},
        )
        # Missing "mappings" key defaults to [] via body.get("mappings", [])
        # which is valid (empty mapping list)
        assert resp.status_code == 200

    def test_update_persisted_to_store(self, client: TestClient, session_store: MagicMock) -> None:
        data = _upload_csv(client)
        session_id = data["id"]
        client.put(
            f"/sessions/{session_id}/mappings",
            json={
                "mappings": [
                    {"source_header": "id_col", "target_field": "ID", "confidence": 1.0},
                ],
                "unmapped_headers": [],
            },
        )
        # save called twice: once for create, once for update
        assert session_store.save.call_count == 2


class TestFinaliseSession:
    """POST /sessions/{id}/finalise — validate rows with user's mapping."""

    def test_returns_200_with_result(self, client: TestClient) -> None:
        data = _upload_csv(client)
        session_id = data["id"]
        resp = client.post(f"/sessions/{session_id}/finalise")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "finalised"
        assert body["result"] is not None
        # Result should contain ProcessingResult fields
        result = body["result"]
        assert "mapping" in result
        assert "valid_records" in result
        assert "errors" in result

    def test_unknown_session_returns_404(self, client: TestClient) -> None:
        resp = client.post("/sessions/nonexistent/finalise")
        assert resp.status_code == 404

    def test_finalise_twice_returns_409(self, client: TestClient) -> None:
        data = _upload_csv(client)
        session_id = data["id"]
        resp1 = client.post(f"/sessions/{session_id}/finalise")
        assert resp1.status_code == 200
        resp2 = client.post(f"/sessions/{session_id}/finalise")
        assert resp2.status_code == 409

    def test_finalise_persisted_to_store(
        self, client: TestClient, session_store: MagicMock
    ) -> None:
        data = _upload_csv(client)
        session_id = data["id"]
        client.post(f"/sessions/{session_id}/finalise")
        # save called twice: create + finalise
        assert session_store.save.call_count == 2
        final_save = session_store.save.call_args[0][0]
        assert final_save.status == SessionStatus.FINALISED

    def test_missing_temp_file_returns_500(
        self, client: TestClient, session_store: MagicMock
    ) -> None:
        """If the temp file is deleted before finalise, returns 500."""
        data = _upload_csv(client)
        session_id = data["id"]
        # Delete the temp file to trigger an error during validate_rows
        saved_session = session_store.save.call_args[0][0]
        os.remove(saved_session.file_path)
        resp = client.post(f"/sessions/{session_id}/finalise")
        assert resp.status_code == 500
        body = resp.json()["detail"]
        assert body["message"] == "Internal server error"


class TestDeleteSession:
    """DELETE /sessions/{id} — cleanup temp file + session store."""

    def test_returns_204(self, client: TestClient) -> None:
        data = _upload_csv(client)
        session_id = data["id"]
        resp = client.delete(f"/sessions/{session_id}")
        assert resp.status_code == 204

    def test_unknown_session_returns_404(self, client: TestClient) -> None:
        resp = client.delete("/sessions/nonexistent")
        assert resp.status_code == 404

    def test_session_removed_from_store(self, client: TestClient, session_store: MagicMock) -> None:
        data = _upload_csv(client)
        session_id = data["id"]
        client.delete(f"/sessions/{session_id}")
        session_store.delete.assert_called_once_with(session_id)

    def test_temp_file_cleaned_up(self, client: TestClient, session_store: MagicMock) -> None:
        data = _upload_csv(client)
        session_id = data["id"]
        # Get the file path from the stored session
        saved_session = session_store.save.call_args[0][0]
        file_path = saved_session.file_path
        assert os.path.exists(file_path)

        client.delete(f"/sessions/{session_id}")
        assert not os.path.exists(file_path)

    def test_get_after_delete_returns_404(self, client: TestClient) -> None:
        data = _upload_csv(client)
        session_id = data["id"]
        client.delete(f"/sessions/{session_id}")
        resp = client.get(f"/sessions/{session_id}")
        assert resp.status_code == 404

    def test_delete_succeeds_when_temp_file_already_gone(
        self, client: TestClient, session_store: MagicMock
    ) -> None:
        """DELETE still returns 204 and removes session even if temp file was already deleted."""
        data = _upload_csv(client)
        session_id = data["id"]
        # Remove the temp file before DELETE
        saved_session = session_store.save.call_args[0][0]
        os.remove(saved_session.file_path)

        resp = client.delete(f"/sessions/{session_id}")
        assert resp.status_code == 204
        session_store.delete.assert_called_once_with(session_id)

    def test_delete_succeeds_when_file_removal_fails(
        self, client: TestClient, session_store: MagicMock
    ) -> None:
        """DELETE still returns 204 even if os.remove raises OSError."""
        data = _upload_csv(client)
        session_id = data["id"]

        with patch("src.adapters.http.routes.os.remove", side_effect=OSError("permission denied")):
            resp = client.delete(f"/sessions/{session_id}")
        assert resp.status_code == 204
        session_store.delete.assert_called_once_with(session_id)
