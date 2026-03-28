"""Polars-based spreadsheet parser implementing IngestorPort."""

from pathlib import Path

import polars as pl


class PolarsIngestor:
    """Reads CSV and Excel files using Polars.

    For Excel files with multiple sheets, pass sheet_name to select
    a specific sheet. Defaults to the first sheet if not specified.
    CSV files ignore sheet_name.
    """

    def get_headers(
        self, file_path: str, *, sheet_name: str | None = None
    ) -> list[str]:
        """Extract column headers from a spreadsheet."""
        self._check_file_exists(file_path)
        if file_path.endswith(".csv"):
            df = pl.read_csv(file_path, n_rows=0)
        else:
            df = self._read_excel(file_path, sheet_name)
        return df.columns

    def get_preview(
        self, file_path: str, n: int = 5, *, sheet_name: str | None = None
    ) -> list[dict[str, object]]:
        """Return first n rows as a list of dicts."""
        self._check_file_exists(file_path)
        if file_path.endswith(".csv"):
            df = pl.read_csv(file_path, n_rows=n)
        else:
            df = self._read_excel(file_path, sheet_name)
            df = df.head(n)
        return df.to_dicts()

    def _read_excel(self, file_path: str, sheet_name: str | None) -> pl.DataFrame:
        """Read an Excel sheet, validating the sheet name exists."""
        if sheet_name is not None:
            try:
                return pl.read_excel(file_path, sheet_name=sheet_name)
            except Exception as e:
                if "not found" in str(e).lower() or "no sheet" in str(e).lower():
                    msg = f"Sheet '{sheet_name}' not found in {file_path}"
                    raise ValueError(msg) from e
                raise
        return pl.read_excel(file_path)

    def get_sheet_names(self, file_path: str) -> list[str]:
        """Return sheet names for Excel files, empty list for CSV."""
        self._check_file_exists(file_path)
        if file_path.endswith(".csv"):
            return []
        import openpyxl

        wb = openpyxl.load_workbook(file_path, read_only=True)
        names = wb.sheetnames
        wb.close()
        return names

    def _check_file_exists(self, file_path: str) -> None:
        if not Path(file_path).exists():
            msg = f"File not found: {file_path}"
            raise FileNotFoundError(msg)
