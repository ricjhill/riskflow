import polars as pl
from typing import List


def get_headers(file_path: str) -> List[str]:
    """Extracts headers from CSV or Excel files using Polars."""
    if file_path.endswith(".csv"):
        df = pl.read_csv(file_path, n_rows=0)
    else:
        # Excel requires the openpyxl engine
        df = pl.read_excel(file_path, read_options={"n_rows": 0})
    return df.columns


def get_preview(file_path: str, n: int = 5) -> List[dict]:
    """Returns first n rows as a list of dicts for SLM context."""
    if file_path.endswith(".csv"):
        df = pl.read_csv(file_path, n_rows=n)
    else:
        df = pl.read_excel(file_path, read_options={"n_rows": n})
    return df.to_dicts()
