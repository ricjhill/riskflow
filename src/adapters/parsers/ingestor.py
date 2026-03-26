"""Polars-based spreadsheet parser implementing IngestorPort."""

from pathlib import Path

import polars as pl


class PolarsIngestor:
    """Reads CSV and Excel files using Polars."""

    def get_headers(self, file_path: str) -> list[str]:
        """Extract column headers from a spreadsheet."""
        self._check_file_exists(file_path)
        if file_path.endswith(".csv"):
            df = pl.read_csv(file_path, n_rows=0)
        else:
            df = pl.read_excel(file_path)
        return df.columns

    def get_preview(self, file_path: str, n: int = 5) -> list[dict[str, object]]:
        """Return first n rows as a list of dicts."""
        self._check_file_exists(file_path)
        if file_path.endswith(".csv"):
            df = pl.read_csv(file_path, n_rows=n)
        else:
            df = pl.read_excel(file_path)
            df = df.head(n)
        return df.to_dicts()

    def _check_file_exists(self, file_path: str) -> None:
        if not Path(file_path).exists():
            msg = f"File not found: {file_path}"
            raise FileNotFoundError(msg)
