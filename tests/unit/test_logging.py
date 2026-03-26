"""Tests for structlog configuration and log output.

Verifies that structlog is properly configured in create_app and that
key operations produce structured log events at adapter boundaries.
"""

import io
import json
import logging
from unittest.mock import AsyncMock, patch

import pytest
import structlog

from src.domain.model.schema import ColumnMapping, MappingResult
from src.entrypoint.main import configure_logging


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


class TestConfigureLogging:
    def test_configures_structlog(self) -> None:
        configure_logging()
        logger = structlog.get_logger()
        assert logger is not None

    def test_produces_json_output(self, capfd: pytest.CaptureFixture[str]) -> None:
        configure_logging()
        logger = structlog.get_logger()
        logger.info("test_event", key="value")

        captured = capfd.readouterr()
        lines = [l for l in captured.out.strip().split("\n") if l.strip()]
        # Find the line with our test event
        test_lines = [l for l in lines if "test_event" in l]
        assert len(test_lines) >= 1
        parsed = json.loads(test_lines[-1])
        assert parsed["event"] == "test_event"
        assert parsed["key"] == "value"


class TestRequestLogging:
    """Verify that HTTP requests produce structured log events."""

    def test_upload_logs_file_received(self, capfd: pytest.CaptureFixture[str]) -> None:
        with patch("src.entrypoint.main.GroqMapper") as MockMapper:
            mock_mapper = AsyncMock()
            mock_mapper.map_headers.return_value = _make_mapping_result()
            MockMapper.return_value = mock_mapper

            from src.entrypoint.main import create_app

            app = create_app()

            from fastapi.testclient import TestClient

            client = TestClient(app)
            client.post(
                "/upload",
                files={"file": ("test.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
            )

        captured = capfd.readouterr()
        lines = [l for l in captured.out.strip().split("\n") if l.strip()]
        json_lines = []
        for line in lines:
            try:
                json_lines.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        events = [l["event"] for l in json_lines]
        assert "file_received" in events

    def test_upload_logs_mapping_complete(self, capfd: pytest.CaptureFixture[str]) -> None:
        with patch("src.entrypoint.main.GroqMapper") as MockMapper:
            mock_mapper = AsyncMock()
            mock_mapper.map_headers.return_value = _make_mapping_result()
            MockMapper.return_value = mock_mapper

            from src.entrypoint.main import create_app

            app = create_app()

            from fastapi.testclient import TestClient

            client = TestClient(app)
            client.post(
                "/upload",
                files={"file": ("test.csv", io.BytesIO(b"ID\n1\n"), "text/csv")},
            )

        captured = capfd.readouterr()
        lines = [l for l in captured.out.strip().split("\n") if l.strip()]
        json_lines = []
        for line in lines:
            try:
                json_lines.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        events = [l["event"] for l in json_lines]
        assert "mapping_complete" in events

        # Verify mapping_complete has expected fields
        complete_event = next(l for l in json_lines if l["event"] == "mapping_complete")
        assert "duration_ms" in complete_event
        assert "mapped_count" in complete_event
        assert "filename" in complete_event
