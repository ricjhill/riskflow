"""Tests for gui/api_client.py — RiskFlowClient HTTP methods.

Tests mock httpx to verify correct URLs, methods, params, and response
parsing without a running API server.
"""

from unittest.mock import MagicMock, patch

import pytest

from gui.api_client import RiskFlowClient


@pytest.fixture
def client() -> RiskFlowClient:
    return RiskFlowClient(base_url="http://test:8000")


class TestCreateSession:
    """POST /sessions — upload file, get session with SLM suggestions."""

    @patch("gui.api_client.httpx.post")
    def test_posts_to_sessions_endpoint(self, mock_post: MagicMock, client: RiskFlowClient) -> None:
        mock_post.return_value = MagicMock(
            json=lambda: {"id": "abc", "status": "created"},
            raise_for_status=MagicMock(),
        )
        client.create_session(b"csv-data", "test.csv")
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://test:8000/sessions"

    @patch("gui.api_client.httpx.post")
    def test_passes_file_bytes(self, mock_post: MagicMock, client: RiskFlowClient) -> None:
        mock_post.return_value = MagicMock(
            json=lambda: {"id": "abc"},
            raise_for_status=MagicMock(),
        )
        client.create_session(b"csv-data", "test.csv")
        files = mock_post.call_args[1]["files"]
        assert files["file"][0] == "test.csv"
        assert files["file"][1] == b"csv-data"

    @patch("gui.api_client.httpx.post")
    def test_passes_schema_param(self, mock_post: MagicMock, client: RiskFlowClient) -> None:
        mock_post.return_value = MagicMock(
            json=lambda: {"id": "abc"},
            raise_for_status=MagicMock(),
        )
        client.create_session(b"data", "f.csv", schema="marine_cargo")
        params = mock_post.call_args[1]["params"]
        assert params["schema"] == "marine_cargo"

    @patch("gui.api_client.httpx.post")
    def test_passes_sheet_name_param(self, mock_post: MagicMock, client: RiskFlowClient) -> None:
        mock_post.return_value = MagicMock(
            json=lambda: {"id": "abc"},
            raise_for_status=MagicMock(),
        )
        client.create_session(b"data", "f.xlsx", sheet_name="Sheet2")
        params = mock_post.call_args[1]["params"]
        assert params["sheet_name"] == "Sheet2"

    @patch("gui.api_client.httpx.post")
    def test_returns_session_dict(self, mock_post: MagicMock, client: RiskFlowClient) -> None:
        expected = {"id": "abc", "status": "created", "mappings": []}
        mock_post.return_value = MagicMock(
            json=lambda: expected,
            raise_for_status=MagicMock(),
        )
        result = client.create_session(b"data", "f.csv")
        assert result == expected

    @patch("gui.api_client.httpx.post")
    def test_calls_raise_for_status(self, mock_post: MagicMock, client: RiskFlowClient) -> None:
        mock_response = MagicMock()
        mock_post.return_value = mock_response
        client.create_session(b"data", "f.csv")
        mock_response.raise_for_status.assert_called_once()


class TestGetSession:
    """GET /sessions/{id} — retrieve current session state."""

    @patch("gui.api_client.httpx.get")
    def test_gets_correct_url(self, mock_get: MagicMock, client: RiskFlowClient) -> None:
        mock_get.return_value = MagicMock(
            json=lambda: {"id": "abc", "status": "created"},
            raise_for_status=MagicMock(),
        )
        client.get_session("abc")
        assert mock_get.call_args[0][0] == "http://test:8000/sessions/abc"

    @patch("gui.api_client.httpx.get")
    def test_returns_session_dict(self, mock_get: MagicMock, client: RiskFlowClient) -> None:
        expected = {"id": "abc", "status": "created", "mappings": []}
        mock_get.return_value = MagicMock(
            json=lambda: expected,
            raise_for_status=MagicMock(),
        )
        assert client.get_session("abc") == expected


class TestUpdateMappings:
    """PUT /sessions/{id}/mappings — user edits mappings."""

    @patch("gui.api_client.httpx.put")
    def test_puts_correct_url(self, mock_put: MagicMock, client: RiskFlowClient) -> None:
        mock_put.return_value = MagicMock(
            json=lambda: {"id": "abc"},
            raise_for_status=MagicMock(),
        )
        client.update_mappings("abc", mappings=[], unmapped_headers=[])
        assert mock_put.call_args[0][0] == "http://test:8000/sessions/abc/mappings"

    @patch("gui.api_client.httpx.put")
    def test_sends_json_body(self, mock_put: MagicMock, client: RiskFlowClient) -> None:
        mock_put.return_value = MagicMock(
            json=lambda: {"id": "abc"},
            raise_for_status=MagicMock(),
        )
        mappings = [{"source_header": "A", "target_field": "B", "confidence": 1.0}]
        client.update_mappings("abc", mappings=mappings, unmapped_headers=["C"])
        body = mock_put.call_args[1]["json"]
        assert body["mappings"] == mappings
        assert body["unmapped_headers"] == ["C"]

    @patch("gui.api_client.httpx.put")
    def test_returns_updated_session(self, mock_put: MagicMock, client: RiskFlowClient) -> None:
        expected = {"id": "abc", "mappings": [{"target_field": "B"}]}
        mock_put.return_value = MagicMock(
            json=lambda: expected,
            raise_for_status=MagicMock(),
        )
        assert client.update_mappings("abc", mappings=[], unmapped_headers=[]) == expected


class TestFinaliseSession:
    """POST /sessions/{id}/finalise — validate rows with user's mapping."""

    @patch("gui.api_client.httpx.post")
    def test_posts_correct_url(self, mock_post: MagicMock, client: RiskFlowClient) -> None:
        mock_post.return_value = MagicMock(
            json=lambda: {"id": "abc", "status": "finalised"},
            raise_for_status=MagicMock(),
        )
        client.finalise_session("abc")
        assert mock_post.call_args[0][0] == "http://test:8000/sessions/abc/finalise"

    @patch("gui.api_client.httpx.post")
    def test_returns_finalised_session(self, mock_post: MagicMock, client: RiskFlowClient) -> None:
        expected = {"id": "abc", "status": "finalised", "result": {"valid_records": []}}
        mock_post.return_value = MagicMock(
            json=lambda: expected,
            raise_for_status=MagicMock(),
        )
        assert client.finalise_session("abc") == expected


class TestDeleteSession:
    """DELETE /sessions/{id} — cleanup session + temp file."""

    @patch("gui.api_client.httpx.delete")
    def test_deletes_correct_url(self, mock_delete: MagicMock, client: RiskFlowClient) -> None:
        mock_delete.return_value = MagicMock(raise_for_status=MagicMock())
        client.delete_session("abc")
        assert mock_delete.call_args[0][0] == "http://test:8000/sessions/abc"

    @patch("gui.api_client.httpx.delete")
    def test_returns_none(self, mock_delete: MagicMock, client: RiskFlowClient) -> None:
        mock_delete.return_value = MagicMock(raise_for_status=MagicMock())
        assert client.delete_session("abc") is None

    @patch("gui.api_client.httpx.delete")
    def test_calls_raise_for_status(self, mock_delete: MagicMock, client: RiskFlowClient) -> None:
        mock_response = MagicMock()
        mock_delete.return_value = mock_response
        client.delete_session("abc")
        mock_response.raise_for_status.assert_called_once()
