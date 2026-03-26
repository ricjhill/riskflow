"""Tests for PolarsIngestor adapter."""

import csv
from pathlib import Path

import pytest

from src.adapters.parsers.ingestor import PolarsIngestor
from src.ports.input.ingestor import IngestorPort


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> str:
    """Helper to create a CSV fixture."""
    file_path = str(path / "test.csv")
    with open(file_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
    return file_path


class TestPolarsIngestorProtocol:
    def test_satisfies_ingestor_port(self) -> None:
        assert isinstance(PolarsIngestor(), IngestorPort)


class TestGetHeaders:
    def test_returns_headers_from_csv(self, tmp_path: Path) -> None:
        path = _write_csv(
            tmp_path,
            ["Policy No.", "Start Date", "GWP"],
            [["P001", "2024-01-01", "50000"]],
        )
        headers = PolarsIngestor().get_headers(path)
        assert headers == ["Policy No.", "Start Date", "GWP"]

    def test_headers_from_csv_with_no_rows(self, tmp_path: Path) -> None:
        path = _write_csv(tmp_path, ["A", "B", "C"], [])
        headers = PolarsIngestor().get_headers(path)
        assert headers == ["A", "B", "C"]

    def test_headers_with_special_characters(self, tmp_path: Path) -> None:
        path = _write_csv(
            tmp_path,
            ["Policy #", "Sum (USD)", "Date/Time"],
            [["P001", "100000", "2024-01-01"]],
        )
        headers = PolarsIngestor().get_headers(path)
        assert headers == ["Policy #", "Sum (USD)", "Date/Time"]

    def test_many_columns(self, tmp_path: Path) -> None:
        cols = [f"Col_{i}" for i in range(50)]
        path = _write_csv(tmp_path, cols, [["val"] * 50])
        headers = PolarsIngestor().get_headers(path)
        assert len(headers) == 50

    def test_raises_on_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            PolarsIngestor().get_headers("/nonexistent/file.csv")


class TestGetPreview:
    def test_returns_first_n_rows(self, tmp_path: Path) -> None:
        path = _write_csv(
            tmp_path,
            ["ID", "Value"],
            [["1", "a"], ["2", "b"], ["3", "c"], ["4", "d"], ["5", "e"]],
        )
        preview = PolarsIngestor().get_preview(path, n=3)
        assert len(preview) == 3
        # Polars infers numeric types from CSV
        assert preview[0]["ID"] == 1
        assert preview[2]["ID"] == 3

    def test_default_n_is_five(self, tmp_path: Path) -> None:
        rows = [[str(i), f"val_{i}"] for i in range(10)]
        path = _write_csv(tmp_path, ["ID", "Value"], rows)
        preview = PolarsIngestor().get_preview(path)
        assert len(preview) == 5

    def test_returns_all_rows_when_fewer_than_n(self, tmp_path: Path) -> None:
        path = _write_csv(tmp_path, ["ID"], [["1"], ["2"]])
        preview = PolarsIngestor().get_preview(path, n=10)
        assert len(preview) == 2

    def test_empty_csv_returns_empty_list(self, tmp_path: Path) -> None:
        path = _write_csv(tmp_path, ["ID", "Value"], [])
        preview = PolarsIngestor().get_preview(path)
        assert preview == []

    def test_preview_rows_are_dicts(self, tmp_path: Path) -> None:
        path = _write_csv(
            tmp_path,
            ["Name", "Amount"],
            [["Alice", "100"]],
        )
        preview = PolarsIngestor().get_preview(path, n=1)
        assert isinstance(preview[0], dict)
        assert "Name" in preview[0]
        assert "Amount" in preview[0]

    def test_raises_on_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            PolarsIngestor().get_preview("/nonexistent/file.csv")
