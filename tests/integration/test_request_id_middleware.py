"""Tests for request_id middleware.

Verifies that every HTTP request gets a unique UUID4 request_id
bound to structlog contextvars, included in all log events during
that request, and cleared afterwards.
"""

import io
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import structlog

from src.domain.model.schema import ColumnMapping, MappingResult


def _make_mapping_result() -> MappingResult:
    return MappingResult(
        mappings=[
            ColumnMapping(
                source_header="GWP",
                target_field="Gross_Premium",
                confidence=0.95,
            ),
        ],
        unmapped_headers=["Extra"],
    )


def _create_test_app():
    """Create app with mocked SLM mapper."""
    with patch("src.entrypoint.main.GroqMapper") as MockMapper:
        mock_mapper = AsyncMock()
        mock_mapper.map_headers.return_value = _make_mapping_result()
        MockMapper.return_value = mock_mapper

        from src.entrypoint.main import create_app

        app = create_app()
    return app


def _extract_json_logs(captured_out: str) -> list[dict]:
    """Parse JSON log lines from captured stdout."""
    lines = [line for line in captured_out.strip().split("\n") if line.strip()]
    result = []
    for line in lines:
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result


class TestRequestIdMiddleware:
    """Every request gets a unique request_id in all log events."""

    def test_log_events_include_request_id(self, capfd: pytest.CaptureFixture[str]) -> None:
        """All log events during a request should contain a request_id."""
        app = _create_test_app()

        from fastapi.testclient import TestClient

        client = TestClient(app)
        client.post(
            "/upload",
            files={"file": ("test.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
        )

        captured = capfd.readouterr()
        json_logs = _extract_json_logs(captured.out)

        # Filter to request-scoped events (not startup logs)
        request_events = [
            log for log in json_logs if log.get("event") in ("file_received", "mapping_complete")
        ]
        assert len(request_events) >= 2

        for log_event in request_events:
            assert "request_id" in log_event, f"event '{log_event['event']}' missing request_id"

    def test_request_id_is_valid_uuid4(self, capfd: pytest.CaptureFixture[str]) -> None:
        """The request_id should be a valid UUID4 string."""
        app = _create_test_app()

        from fastapi.testclient import TestClient

        client = TestClient(app)
        client.post(
            "/upload",
            files={"file": ("test.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
        )

        captured = capfd.readouterr()
        json_logs = _extract_json_logs(captured.out)

        request_events = [
            log for log in json_logs if log.get("event") in ("file_received", "mapping_complete")
        ]
        assert len(request_events) >= 1

        request_id = request_events[0]["request_id"]
        parsed = uuid.UUID(request_id, version=4)
        assert str(parsed) == request_id

    def test_same_request_id_across_all_events_in_single_request(
        self, capfd: pytest.CaptureFixture[str]
    ) -> None:
        """All log events within one request share the same request_id."""
        app = _create_test_app()

        from fastapi.testclient import TestClient

        client = TestClient(app)
        client.post(
            "/upload",
            files={"file": ("test.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
        )

        captured = capfd.readouterr()
        json_logs = _extract_json_logs(captured.out)

        request_events = [
            log for log in json_logs if log.get("event") in ("file_received", "mapping_complete")
        ]
        assert len(request_events) >= 2

        request_ids = {log["request_id"] for log in request_events}
        assert len(request_ids) == 1, f"Expected one request_id across events, got {request_ids}"

    def test_different_requests_get_different_ids(self, capfd: pytest.CaptureFixture[str]) -> None:
        """Two separate requests should have different request_ids."""
        app = _create_test_app()

        from fastapi.testclient import TestClient

        client = TestClient(app)

        client.post(
            "/upload",
            files={"file": ("test1.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
        )
        first_output = capfd.readouterr().out

        client.post(
            "/upload",
            files={"file": ("test2.csv", io.BytesIO(b"ID\n2\n"), "text/csv")},
        )
        second_output = capfd.readouterr().out

        first_logs = _extract_json_logs(first_output)
        second_logs = _extract_json_logs(second_output)

        first_ids = {
            log["request_id"]
            for log in first_logs
            if "request_id" in log and log.get("event") in ("file_received", "mapping_complete")
        }
        second_ids = {
            log["request_id"]
            for log in second_logs
            if "request_id" in log and log.get("event") in ("file_received", "mapping_complete")
        }

        assert len(first_ids) == 1
        assert len(second_ids) == 1
        assert first_ids != second_ids

    def test_request_id_cleared_after_request(self, capfd: pytest.CaptureFixture[str]) -> None:
        """request_id should not leak into logs outside request scope."""
        app = _create_test_app()

        from fastapi.testclient import TestClient

        client = TestClient(app)
        client.post(
            "/upload",
            files={"file": ("test.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
        )
        capfd.readouterr()  # drain

        # Log outside request scope
        logger = structlog.get_logger()
        logger.info("after_request_event")

        captured = capfd.readouterr()
        json_logs = _extract_json_logs(captured.out)

        after_events = [log for log in json_logs if log.get("event") == "after_request_event"]
        assert len(after_events) == 1
        assert "request_id" not in after_events[0]

    def test_response_header_contains_request_id(self) -> None:
        """The response should include X-Request-ID header."""
        app = _create_test_app()

        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/upload",
            files={"file": ("test.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
        )

        assert "x-request-id" in response.headers
        request_id = response.headers["x-request-id"]
        parsed = uuid.UUID(request_id, version=4)
        assert str(parsed) == request_id
