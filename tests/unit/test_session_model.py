"""Tests for MappingSession domain model.

Covers: creation, update_mappings (valid + invalid), finalise transitions,
serialization roundtrip, and invariant enforcement.
"""

import pytest

from src.domain.model.schema import ColumnMapping
from src.domain.model.session import MappingSession, SessionStatus


class TestMappingSessionCreation:
    """Factory method creates a valid session with CREATED status."""

    def test_create_returns_created_status(self) -> None:
        session = MappingSession.create(
            schema_name="standard_reinsurance",
            file_path="/tmp/test.csv",
            sheet_name=None,
            source_headers=["Premium", "PolicyNum"],
            target_fields=["Gross_Premium", "Policy_ID"],
            mappings=[
                ColumnMapping(
                    source_header="Premium",
                    target_field="Gross_Premium",
                    confidence=0.95,
                ),
            ],
            unmapped_headers=["PolicyNum"],
            preview_rows=[{"Premium": 1000, "PolicyNum": "P001"}],
        )
        assert session.status == SessionStatus.CREATED
        assert len(session.id) == 36  # UUID format
        assert session.schema_name == "standard_reinsurance"
        assert session.file_path == "/tmp/test.csv"
        assert session.sheet_name is None
        assert session.source_headers == ["Premium", "PolicyNum"]
        assert session.target_fields == ["Gross_Premium", "Policy_ID"]
        assert len(session.mappings) == 1
        assert session.unmapped_headers == ["PolicyNum"]
        assert session.preview_rows == [{"Premium": 1000, "PolicyNum": "P001"}]
        assert session.result is None

    def test_create_with_sheet_name(self) -> None:
        session = MappingSession.create(
            schema_name="marine_cargo",
            file_path="/tmp/test.xlsx",
            sheet_name="Sheet2",
            source_headers=["Col1"],
            target_fields=["Field1"],
            mappings=[],
            unmapped_headers=["Col1"],
            preview_rows=[],
        )
        assert session.sheet_name == "Sheet2"

    def test_create_generates_unique_ids(self) -> None:
        s1 = MappingSession.create(
            schema_name="s",
            file_path="/tmp/a.csv",
            sheet_name=None,
            source_headers=[],
            target_fields=[],
            mappings=[],
            unmapped_headers=[],
            preview_rows=[],
        )
        s2 = MappingSession.create(
            schema_name="s",
            file_path="/tmp/b.csv",
            sheet_name=None,
            source_headers=[],
            target_fields=[],
            mappings=[],
            unmapped_headers=[],
            preview_rows=[],
        )
        assert s1.id != s2.id


class TestUpdateMappings:
    """update_mappings validates targets and replaces the current mapping."""

    @pytest.fixture()
    def session(self) -> MappingSession:
        return MappingSession.create(
            schema_name="standard_reinsurance",
            file_path="/tmp/test.csv",
            sheet_name=None,
            source_headers=["Premium", "PolicyNum", "Start"],
            target_fields=["Gross_Premium", "Policy_ID", "Inception_Date"],
            mappings=[
                ColumnMapping(
                    source_header="Premium",
                    target_field="Gross_Premium",
                    confidence=0.95,
                ),
            ],
            unmapped_headers=["PolicyNum", "Start"],
            preview_rows=[],
        )

    def test_valid_update_replaces_mappings(self, session: MappingSession) -> None:
        new_mappings = [
            ColumnMapping(
                source_header="Premium",
                target_field="Gross_Premium",
                confidence=1.0,
            ),
            ColumnMapping(
                source_header="PolicyNum",
                target_field="Policy_ID",
                confidence=1.0,
            ),
        ]
        session.update_mappings(
            mappings=new_mappings,
            unmapped_headers=["Start"],
        )
        assert len(session.mappings) == 2
        assert session.unmapped_headers == ["Start"]

    def test_invalid_target_field_raises(self, session: MappingSession) -> None:
        bad_mappings = [
            ColumnMapping(
                source_header="Premium",
                target_field="NONEXISTENT",
                confidence=1.0,
            ),
        ]
        with pytest.raises(ValueError, match="not in target fields"):
            session.update_mappings(mappings=bad_mappings, unmapped_headers=[])

    def test_duplicate_target_fields_raises(self, session: MappingSession) -> None:
        dupes = [
            ColumnMapping(
                source_header="Premium",
                target_field="Gross_Premium",
                confidence=1.0,
            ),
            ColumnMapping(
                source_header="PolicyNum",
                target_field="Gross_Premium",
                confidence=1.0,
            ),
        ]
        with pytest.raises(ValueError, match="Duplicate target"):
            session.update_mappings(mappings=dupes, unmapped_headers=[])

    def test_update_on_finalised_session_raises(self, session: MappingSession) -> None:
        session.finalise(result={"valid_records": []})
        with pytest.raises(ValueError, match="Cannot update.*FINALISED"):
            session.update_mappings(mappings=[], unmapped_headers=[])


class TestExtendTargetFields:
    """extend_target_fields appends new fields, deduplicates, and validates."""

    @pytest.fixture()
    def session(self) -> MappingSession:
        return MappingSession.create(
            schema_name="s",
            file_path="/tmp/test.csv",
            sheet_name=None,
            source_headers=["A", "B"],
            target_fields=["Field_1", "Field_2"],
            mappings=[],
            unmapped_headers=["A", "B"],
            preview_rows=[],
        )

    def test_appends_new_fields(self, session: MappingSession) -> None:
        session.extend_target_fields(fields=["Field_3", "Field_4"])
        assert "Field_3" in session.target_fields
        assert "Field_4" in session.target_fields
        assert len(session.target_fields) == 4

    def test_deduplicates_existing_fields(self, session: MappingSession) -> None:
        session.extend_target_fields(fields=["Field_1", "Field_3"])
        assert session.target_fields.count("Field_1") == 1
        assert "Field_3" in session.target_fields
        assert len(session.target_fields) == 3

    def test_rejects_empty_field_names(self, session: MappingSession) -> None:
        with pytest.raises(ValueError, match="empty"):
            session.extend_target_fields(fields=[""])

    def test_rejects_whitespace_only_field_names(self, session: MappingSession) -> None:
        with pytest.raises(ValueError, match="empty"):
            session.extend_target_fields(fields=["  "])

    def test_rejects_on_finalised_session(self, session: MappingSession) -> None:
        session.finalise(result={})
        with pytest.raises(ValueError, match="FINALISED"):
            session.extend_target_fields(fields=["New"])

    def test_rejects_empty_list(self, session: MappingSession) -> None:
        with pytest.raises(ValueError, match="at least one"):
            session.extend_target_fields(fields=[])


class TestFinalise:
    """finalise transitions CREATED → FINALISED and stores the result."""

    @pytest.fixture()
    def session(self) -> MappingSession:
        return MappingSession.create(
            schema_name="s",
            file_path="/tmp/test.csv",
            sheet_name=None,
            source_headers=["A"],
            target_fields=["B"],
            mappings=[],
            unmapped_headers=["A"],
            preview_rows=[],
        )

    def test_finalise_sets_status_and_result(self, session: MappingSession) -> None:
        result = {"valid_records": [{"B": 1}], "errors": []}
        session.finalise(result=result)
        assert session.status == SessionStatus.FINALISED
        assert session.result == result

    def test_finalise_twice_raises(self, session: MappingSession) -> None:
        session.finalise(result={})
        with pytest.raises(ValueError, match="Cannot finalise.*FINALISED"):
            session.finalise(result={})


class TestSerialization:
    """JSON roundtrip via model_dump / model_validate."""

    def test_roundtrip(self) -> None:
        session = MappingSession.create(
            schema_name="standard_reinsurance",
            file_path="/tmp/test.csv",
            sheet_name="Sheet1",
            source_headers=["Premium"],
            target_fields=["Gross_Premium"],
            mappings=[
                ColumnMapping(
                    source_header="Premium",
                    target_field="Gross_Premium",
                    confidence=0.9,
                ),
            ],
            unmapped_headers=[],
            preview_rows=[{"Premium": 500}],
        )
        data = session.model_dump()
        restored = MappingSession.model_validate(data)
        assert restored.id == session.id
        assert restored.status == session.status
        assert restored.schema_name == session.schema_name
        assert restored.file_path == session.file_path
        assert restored.sheet_name == session.sheet_name
        assert restored.source_headers == session.source_headers
        assert restored.target_fields == session.target_fields
        assert len(restored.mappings) == 1
        assert restored.mappings[0].source_header == "Premium"
        assert restored.unmapped_headers == session.unmapped_headers
        assert restored.preview_rows == session.preview_rows
        assert restored.result is None

    def test_roundtrip_with_result(self) -> None:
        session = MappingSession.create(
            schema_name="s",
            file_path="/tmp/x.csv",
            sheet_name=None,
            source_headers=[],
            target_fields=[],
            mappings=[],
            unmapped_headers=[],
            preview_rows=[],
        )
        session.finalise(result={"records": [1, 2, 3]})
        data = session.model_dump()
        restored = MappingSession.model_validate(data)
        assert restored.status == SessionStatus.FINALISED
        assert restored.result == {"records": [1, 2, 3]}
