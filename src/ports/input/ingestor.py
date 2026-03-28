"""Input port for spreadsheet ingestion."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class IngestorPort(Protocol):
    """How data enters the domain from spreadsheets."""

    def get_headers(
        self, file_path: str, *, sheet_name: str | None = None
    ) -> list[str]: ...

    def get_preview(
        self, file_path: str, n: int = 5, *, sheet_name: str | None = None
    ) -> list[dict[str, object]]: ...
