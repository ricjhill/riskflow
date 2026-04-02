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
