"""Domain model for interactive mapping sessions.

A MappingSession tracks the lifecycle of an interactive mapping workflow:
Upload → SLM suggests → User edits → Finalise (validate rows).

Status transitions: CREATED → FINALISED (one-way).
"""

import enum
import uuid

from pydantic import BaseModel

from src.domain.model.schema import ColumnMapping


class SessionStatus(enum.StrEnum):
    CREATED = "created"
    FINALISED = "finalised"


class MappingSession(BaseModel):
    """Tracks state for an interactive mapping workflow."""

    id: str
    status: SessionStatus
    schema_name: str
    file_path: str
    sheet_name: str | None
    source_headers: list[str]
    target_fields: list[str]
    mappings: list[ColumnMapping]
    unmapped_headers: list[str]
    preview_rows: list[dict[str, object]]
    result: dict[str, object] | None = None

    @classmethod
    def create(
        cls,
        *,
        schema_name: str,
        file_path: str,
        sheet_name: str | None,
        source_headers: list[str],
        target_fields: list[str],
        mappings: list[ColumnMapping],
        unmapped_headers: list[str],
        preview_rows: list[dict[str, object]],
    ) -> "MappingSession":
        return cls(
            id=str(uuid.uuid4()),
            status=SessionStatus.CREATED,
            schema_name=schema_name,
            file_path=file_path,
            sheet_name=sheet_name,
            source_headers=source_headers,
            target_fields=target_fields,
            mappings=mappings,
            unmapped_headers=unmapped_headers,
            preview_rows=preview_rows,
        )

    def update_mappings(
        self,
        *,
        mappings: list[ColumnMapping],
        unmapped_headers: list[str],
    ) -> None:
        """Replace mappings with user-edited values.

        Validates that all target fields are in the session's target_fields
        and that no target field is mapped twice. Raises ValueError on
        invalid input or if the session is already finalised.
        """
        if self.status == SessionStatus.FINALISED:
            msg = "Cannot update mappings on a FINALISED session"
            raise ValueError(msg)

        valid = set(self.target_fields)
        for m in mappings:
            if m.target_field not in valid:
                msg = f"Target field '{m.target_field}' not in target fields: {sorted(valid)}"
                raise ValueError(msg)

        targets = [m.target_field for m in mappings]
        dupes = {t for t in targets if targets.count(t) > 1}
        if dupes:
            msg = f"Duplicate target fields: {sorted(dupes)}"
            raise ValueError(msg)

        self.mappings = mappings
        self.unmapped_headers = unmapped_headers

    def finalise(self, *, result: dict[str, object]) -> None:
        """Transition CREATED → FINALISED and store the processing result."""
        if self.status == SessionStatus.FINALISED:
            msg = "Cannot finalise a FINALISED session"
            raise ValueError(msg)
        self.status = SessionStatus.FINALISED
        self.result = result
