"""Thin HTTP client for the RiskFlow API.

The GUI talks to the API via HTTP — it never imports domain code.
This preserves the hexagonal architecture: the GUI is just another
adapter consuming the same REST endpoints as any other client.
"""

import httpx


class RiskFlowClient:
    """Stateless HTTP client for the RiskFlow API."""

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self.base_url = base_url.rstrip("/")

    def health(self) -> dict:
        """GET /health"""
        r = httpx.get(f"{self.base_url}/health", timeout=5)
        r.raise_for_status()
        return r.json()

    def list_schemas(self) -> list[str]:
        """GET /schemas → list of schema names."""
        r = httpx.get(f"{self.base_url}/schemas", timeout=5)
        r.raise_for_status()
        return r.json()["schemas"]

    def upload(
        self,
        file_bytes: bytes,
        filename: str,
        *,
        schema: str | None = None,
        sheet_name: str | None = None,
        cedent_id: str | None = None,
    ) -> dict:
        """POST /upload → full ProcessingResult as dict."""
        params: dict[str, str] = {}
        if schema:
            params["schema"] = schema
        if sheet_name:
            params["sheet_name"] = sheet_name
        if cedent_id:
            params["cedent_id"] = cedent_id

        r = httpx.post(
            f"{self.base_url}/upload",
            files={"file": (filename, file_bytes)},
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def list_sheets(self, file_bytes: bytes, filename: str) -> list[str]:
        """POST /sheets → list of sheet names."""
        r = httpx.post(
            f"{self.base_url}/sheets",
            files={"file": (filename, file_bytes)},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()["sheets"]

    def submit_corrections(self, cedent_id: str, corrections: list[dict[str, str]]) -> int:
        """POST /corrections → number of corrections stored."""
        r = httpx.post(
            f"{self.base_url}/corrections",
            json={"cedent_id": cedent_id, "corrections": corrections},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()["stored"]

    def create_session(
        self,
        file_bytes: bytes,
        filename: str,
        *,
        schema: str | None = None,
        sheet_name: str | None = None,
    ) -> dict:
        """POST /sessions → session dict with SLM suggestions."""
        params: dict[str, str] = {}
        if schema:
            params["schema"] = schema
        if sheet_name:
            params["sheet_name"] = sheet_name
        r = httpx.post(
            f"{self.base_url}/sessions",
            files={"file": (filename, file_bytes)},
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def get_session(self, session_id: str) -> dict:
        """GET /sessions/{id} → current session state."""
        r = httpx.get(f"{self.base_url}/sessions/{session_id}", timeout=5)
        r.raise_for_status()
        return r.json()

    def update_mappings(
        self,
        session_id: str,
        *,
        mappings: list[dict],
        unmapped_headers: list[str],
    ) -> dict:
        """PUT /sessions/{id}/mappings → updated session state."""
        r = httpx.put(
            f"{self.base_url}/sessions/{session_id}/mappings",
            json={"mappings": mappings, "unmapped_headers": unmapped_headers},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def finalise_session(self, session_id: str) -> dict:
        """POST /sessions/{id}/finalise → session with ProcessingResult."""
        r = httpx.post(
            f"{self.base_url}/sessions/{session_id}/finalise",
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def delete_session(self, session_id: str) -> None:
        """DELETE /sessions/{id} → cleanup session + temp file."""
        r = httpx.delete(f"{self.base_url}/sessions/{session_id}", timeout=5)
        r.raise_for_status()
