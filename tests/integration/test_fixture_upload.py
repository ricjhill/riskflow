"""Fixture-based upload integration tests.

Uploads the real test fixture files (CSV and Excel) through the full
FastAPI pipeline with a mocked SLM. Proves that file parsing, column
mapping, date coercion, and row validation work end-to-end with
realistic broker data.

This test would have caught the date format issue from PR #90 before
manual testing — the messy Excel file uses DD-Mon-YYYY, DD/MM/YYYY,
YYYY/MM/DD, verbose dates, and ISO 8601 across different rows.

Uses the same fixture files that are provided for manual GUI testing.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.domain.model.schema import ColumnMapping, MappingResult

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _make_reinsurance_mapping(headers: list[str]) -> MappingResult:
    """Mock SLM response for reinsurance fixture headers."""
    known: dict[str, tuple[str, float]] = {
        # CSV fixture headers
        "Policy No.": ("Policy_ID", 0.99),
        "Start Date": ("Inception_Date", 0.95),
        "End Date": ("Expiry_Date", 0.95),
        "Total Sum Insured": ("Sum_Insured", 0.90),
        "GWP": ("Gross_Premium", 0.97),
        "Ccy": ("Currency", 0.98),
        # Messy Excel fixture headers
        "Certificate No": ("Policy_ID", 0.92),
        "Effective From": ("Inception_Date", 0.88),
        "Effective To": ("Expiry_Date", 0.88),
        "TSI (000s)": ("Sum_Insured", 0.85),
        # Multi-sheet Excel clean headers
        "Policy ID": ("Policy_ID", 0.99),
        "Inception Date": ("Inception_Date", 0.99),
        "Expiry Date": ("Expiry_Date", 0.99),
        "Sum Insured": ("Sum_Insured", 0.99),
        "Gross Premium": ("Gross_Premium", 0.99),
        "Currency": ("Currency", 0.99),
    }
    mappings = []
    unmapped = []
    for h in headers:
        if h in known:
            target, conf = known[h]
            mappings.append(ColumnMapping(source_header=h, target_field=target, confidence=conf))
        else:
            unmapped.append(h)
    return MappingResult(mappings=mappings, unmapped_headers=unmapped)


def _make_marine_mapping(headers: list[str]) -> MappingResult:
    """Mock SLM response for marine cargo fixture headers."""
    known: dict[str, tuple[str, float]] = {
        "Ship": ("Vessel_Name", 0.95),
        "Sailing Date": ("Voyage_Date", 0.92),
        "ETA": ("Arrival_Date", 0.90),
        "Cargo Value": ("Cargo_Value", 0.88),
        "GWP": ("Premium", 0.97),
        "Ccy": ("Currency", 0.98),
        "Loading Port": ("Port_Of_Loading", 0.93),
        "Destination": ("Port_Of_Discharge", 0.91),
    }
    mappings = []
    unmapped = []
    for h in headers:
        if h in known:
            target, conf = known[h]
            mappings.append(ColumnMapping(source_header=h, target_field=target, confidence=conf))
        else:
            unmapped.append(h)
    return MappingResult(mappings=mappings, unmapped_headers=unmapped)


@pytest.fixture
def reinsurance_client() -> TestClient:
    """TestClient with mocked SLM returning reinsurance mappings."""
    mock = AsyncMock()

    async def _fake_map(
        source_headers: list[str],
        preview_rows: list[dict[str, object]],
    ) -> MappingResult:
        return _make_reinsurance_mapping(source_headers)

    mock.map_headers.side_effect = _fake_map

    with patch("src.entrypoint.main.GroqMapper") as MockMapper:
        MockMapper.return_value = mock
        from src.entrypoint.main import create_app

        app = create_app()
        yield TestClient(app)


@pytest.fixture
def marine_client() -> TestClient:
    """TestClient with mocked SLM returning marine cargo mappings."""
    mock = AsyncMock()

    async def _fake_map(
        source_headers: list[str],
        preview_rows: list[dict[str, object]],
    ) -> MappingResult:
        return _make_marine_mapping(source_headers)

    mock.map_headers.side_effect = _fake_map

    with patch("src.entrypoint.main.GroqMapper") as MockMapper:
        MockMapper.return_value = mock
        from src.entrypoint.main import create_app

        app = create_app()
        yield TestClient(app)


class TestReinsuranceCSVFixture:
    """Upload sample_bordereaux.csv — the clean CSV fixture."""

    def test_all_rows_valid(self, reinsurance_client: TestClient) -> None:
        """All 5 rows should validate against standard_reinsurance schema."""
        csv_path = FIXTURES / "sample_bordereaux.csv"
        with open(csv_path, "rb") as f:
            resp = reinsurance_client.post(
                "/upload",
                files={"file": ("bordereaux.csv", f, "text/csv")},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["valid_records"]) == 5
        assert len(body["errors"]) == 0

    def test_mapped_fields_present(self, reinsurance_client: TestClient) -> None:
        """All 6 target fields should be mapped."""
        csv_path = FIXTURES / "sample_bordereaux.csv"
        with open(csv_path, "rb") as f:
            resp = reinsurance_client.post(
                "/upload",
                files={"file": ("bordereaux.csv", f, "text/csv")},
            )

        body = resp.json()
        mapped_targets = {m["target_field"] for m in body["mapping"]["mappings"]}
        expected = {
            "Policy_ID",
            "Inception_Date",
            "Expiry_Date",
            "Sum_Insured",
            "Gross_Premium",
            "Currency",
        }
        assert mapped_targets == expected

    def test_unmapped_headers_captured(self, reinsurance_client: TestClient) -> None:
        """Extra headers (Broker Notes) should appear in unmapped list."""
        csv_path = FIXTURES / "sample_bordereaux.csv"
        with open(csv_path, "rb") as f:
            resp = reinsurance_client.post(
                "/upload",
                files={"file": ("bordereaux.csv", f, "text/csv")},
            )

        body = resp.json()
        assert "Broker Notes" in body["mapping"]["unmapped_headers"]


class TestReinsuranceExcelFixture:
    """Upload reinsurance_bordereaux_messy.xlsx — mixed date formats.

    This is the test that would have caught the DD-Mon-YYYY date parsing
    failure from PR #90. The fixture contains 10 rows with 6 different
    date formats across rows: DD-Mon-YYYY, DD/MM/YYYY, ISO 8601,
    DD Month YYYY, Month DD YYYY, and YYYY/MM/DD.
    """

    def test_all_rows_valid_with_mixed_dates(self, reinsurance_client: TestClient) -> None:
        """All 10 rows should validate despite mixed date formats."""
        xlsx_path = FIXTURES / "reinsurance_bordereaux_messy.xlsx"
        with open(xlsx_path, "rb") as f:
            resp = reinsurance_client.post(
                "/upload",
                files={
                    "file": (
                        "messy.xlsx",
                        f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["errors"]) == 0, (
            f"Expected 0 errors but got {len(body['errors'])}:\n"
            + "\n".join(f"  Row {e['row']}: {e['error']}" for e in body["errors"])
        )
        assert len(body["valid_records"]) == 10

    def test_extra_columns_unmapped(self, reinsurance_client: TestClient) -> None:
        """Non-schema columns (Insured Name, Broker, etc.) should be unmapped."""
        xlsx_path = FIXTURES / "reinsurance_bordereaux_messy.xlsx"
        with open(xlsx_path, "rb") as f:
            resp = reinsurance_client.post(
                "/upload",
                files={
                    "file": (
                        "messy.xlsx",
                        f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

        body = resp.json()
        unmapped = body["mapping"]["unmapped_headers"]
        assert "Insured Name" in unmapped
        assert "Risk Location" in unmapped
        assert "Broker" in unmapped

    def test_yyyy_slash_row_parsed_correctly(self, reinsurance_client: TestClient) -> None:
        """Row 10 uses YYYY/MM/DD format (2025/07/01). Must parse as July 1,
        not January 7 (the dateutil dayfirst=True misparsing)."""

        xlsx_path = FIXTURES / "reinsurance_bordereaux_messy.xlsx"
        with open(xlsx_path, "rb") as f:
            resp = reinsurance_client.post(
                "/upload",
                files={
                    "file": (
                        "messy.xlsx",
                        f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["valid_records"]) >= 10, (
            f"Expected at least 10 valid records but got {len(body['valid_records'])}"
        )
        # Row 10 (index 9) has Inception_Date=2025/07/01, Expiry_Date=2026/06/30
        row10 = body["valid_records"][9]
        assert row10["Inception_Date"] == "2025-07-01", (
            f"Expected July 1 but got {row10['Inception_Date']}"
        )

    def test_confidence_report_present(self, reinsurance_client: TestClient) -> None:
        """Confidence report should have reasonable values."""
        xlsx_path = FIXTURES / "reinsurance_bordereaux_messy.xlsx"
        with open(xlsx_path, "rb") as f:
            resp = reinsurance_client.post(
                "/upload",
                files={
                    "file": (
                        "messy.xlsx",
                        f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

        body = resp.json()
        cr = body["confidence_report"]
        assert cr["min_confidence"] > 0.0
        assert cr["avg_confidence"] > 0.0


class TestMarineCargoCSVFixture:
    """Upload sample_marine_cargo.csv with marine_cargo schema."""

    def test_all_rows_valid(self, marine_client: TestClient) -> None:
        """All 5 rows should validate against marine_cargo schema."""
        csv_path = FIXTURES / "sample_marine_cargo.csv"
        with open(csv_path, "rb") as f:
            resp = marine_client.post(
                "/upload?schema=marine_cargo",
                files={"file": ("cargo.csv", f, "text/csv")},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["valid_records"]) == 5
        assert len(body["errors"]) == 0

    def test_mapped_fields_include_ports(self, marine_client: TestClient) -> None:
        """Marine schema should map port fields."""
        csv_path = FIXTURES / "sample_marine_cargo.csv"
        with open(csv_path, "rb") as f:
            resp = marine_client.post(
                "/upload?schema=marine_cargo",
                files={"file": ("cargo.csv", f, "text/csv")},
            )

        body = resp.json()
        mapped_targets = {m["target_field"] for m in body["mapping"]["mappings"]}
        assert "Port_Of_Loading" in mapped_targets
        assert "Port_Of_Discharge" in mapped_targets
        assert "Vessel_Name" in mapped_targets


class TestMultiSheetExcelFixture:
    """Upload multi_sheet_bordereaux.xlsx — two sheets, one per schema."""

    def test_reinsurance_sheet_valid(self, reinsurance_client: TestClient) -> None:
        """Property Treaty sheet should validate against reinsurance schema."""
        xlsx_path = FIXTURES / "multi_sheet_bordereaux.xlsx"
        with open(xlsx_path, "rb") as f:
            resp = reinsurance_client.post(
                "/upload?sheet_name=Property Treaty",
                files={
                    "file": (
                        "multi.xlsx",
                        f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["valid_records"]) == 5
        assert len(body["errors"]) == 0

    def test_sheets_endpoint_returns_both(self, reinsurance_client: TestClient) -> None:
        """POST /sheets should list both sheets."""
        xlsx_path = FIXTURES / "multi_sheet_bordereaux.xlsx"
        with open(xlsx_path, "rb") as f:
            resp = reinsurance_client.post(
                "/sheets",
                files={
                    "file": (
                        "multi.xlsx",
                        f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

        assert resp.status_code == 200
        sheets = resp.json()["sheets"]
        assert "Property Treaty" in sheets
        assert "Marine Facultative" in sheets
