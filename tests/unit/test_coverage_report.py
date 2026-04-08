"""Tests for tools/coverage_report.py — coverage parsing, baseline comparison, and formatting."""

import json
from pathlib import Path

import pytest

from tools.coverage_report import (
    CoverageResult,
    ModuleCoverage,
    compare_baseline,
    format_markdown,
    format_summary,
    load_baseline,
    parse_coverage_json,
    update_baseline,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_coverage_json(
    files: dict[str, tuple[int, int]],
) -> dict:
    """Build a minimal coverage JSON dict.

    Args:
        files: mapping of file path to (covered_lines, num_statements).
    """
    file_entries = {}
    total_covered = 0
    total_stmts = 0
    for path, (covered, stmts) in files.items():
        pct = (covered / stmts * 100) if stmts > 0 else 100.0
        file_entries[path] = {
            "summary": {
                "covered_lines": covered,
                "num_statements": stmts,
                "percent_covered": pct,
                "missing_lines": stmts - covered,
            }
        }
        total_covered += covered
        total_stmts += stmts
    total_pct = (total_covered / total_stmts * 100) if total_stmts > 0 else 100.0
    return {
        "totals": {
            "covered_lines": total_covered,
            "num_statements": total_stmts,
            "percent_covered": total_pct,
            "missing_lines": total_stmts - total_covered,
        },
        "files": file_entries,
    }


# ---------------------------------------------------------------------------
# TestParseCoverageJson
# ---------------------------------------------------------------------------


class TestParseCoverageJson:
    """Parse coverage.json and extract summary."""

    def test_parses_valid_coverage_json(self) -> None:
        data = _make_coverage_json(
            {
                "src/domain/model/schema.py": (50, 60),
                "src/adapters/http/routes.py": (30, 40),
            }
        )
        result = parse_coverage_json(data)
        assert isinstance(result, CoverageResult)
        assert result.total_pct == pytest.approx(80.0)
        assert result.total_covered == 80
        assert result.total_statements == 100

    def test_handles_empty_coverage(self) -> None:
        data = _make_coverage_json({})
        result = parse_coverage_json(data)
        assert result.total_pct == pytest.approx(100.0)
        assert result.total_covered == 0
        assert result.total_statements == 0
        assert result.modules == []

    def test_extracts_module_breakdown(self) -> None:
        data = _make_coverage_json(
            {
                "src/domain/model/schema.py": (50, 50),
                "src/domain/service/mapping_service.py": (40, 50),
                "src/adapters/http/routes.py": (20, 30),
                "src/ports/output/mapper.py": (10, 10),
                "src/entrypoint/main.py": (80, 100),
            }
        )
        result = parse_coverage_json(data)
        module_names = [m.name for m in result.modules]
        assert sorted(module_names) == ["adapters", "domain", "entrypoint", "ports"]

    def test_module_coverage_aggregates_files(self) -> None:
        data = _make_coverage_json(
            {
                "src/domain/model/schema.py": (50, 60),
                "src/domain/service/mapping_service.py": (30, 40),
            }
        )
        result = parse_coverage_json(data)
        domain = next(m for m in result.modules if m.name == "domain")
        assert domain.covered == 80
        assert domain.total == 100
        assert domain.pct == pytest.approx(80.0)

    def test_modules_sorted_alphabetically(self) -> None:
        data = _make_coverage_json(
            {
                "src/ports/output/mapper.py": (10, 10),
                "src/adapters/http/routes.py": (20, 30),
                "src/domain/model/schema.py": (50, 60),
            }
        )
        result = parse_coverage_json(data)
        names = [m.name for m in result.modules]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# TestCompareBaseline
# ---------------------------------------------------------------------------


class TestCompareBaseline:
    """Compare current coverage against a baseline."""

    def test_no_baseline_returns_none_delta(self) -> None:
        result = CoverageResult(total_pct=80.0, total_covered=80, total_statements=100, modules=[])
        compared = compare_baseline(result, None)
        assert compared.delta is None

    def test_improvement_shows_positive_delta(self) -> None:
        result = CoverageResult(total_pct=85.0, total_covered=85, total_statements=100, modules=[])
        baseline = {"total_pct": 80.0}
        compared = compare_baseline(result, baseline)
        assert compared.delta == pytest.approx(5.0)

    def test_regression_shows_negative_delta(self) -> None:
        result = CoverageResult(total_pct=75.0, total_covered=75, total_statements=100, modules=[])
        baseline = {"total_pct": 80.0}
        compared = compare_baseline(result, baseline)
        assert compared.delta == pytest.approx(-5.0)

    def test_no_change_shows_zero_delta(self) -> None:
        result = CoverageResult(total_pct=80.0, total_covered=80, total_statements=100, modules=[])
        baseline = {"total_pct": 80.0}
        compared = compare_baseline(result, baseline)
        assert compared.delta == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TestFormatSummary
# ---------------------------------------------------------------------------


class TestFormatSummary:
    """Format coverage data into human-readable output."""

    def test_summary_includes_total_percentage(self) -> None:
        result = CoverageResult(
            total_pct=85.3, total_covered=853, total_statements=1000, modules=[]
        )
        output = format_summary(result)
        assert "85.3%" in output

    def test_summary_includes_per_module_breakdown(self) -> None:
        result = CoverageResult(
            total_pct=80.0,
            total_covered=80,
            total_statements=100,
            modules=[
                ModuleCoverage(name="domain", covered=50, total=60, pct=83.3),
                ModuleCoverage(name="adapters", covered=30, total=40, pct=75.0),
            ],
        )
        output = format_summary(result)
        assert "domain" in output
        assert "adapters" in output

    def test_summary_includes_delta_when_present(self) -> None:
        result = CoverageResult(
            total_pct=85.0, total_covered=85, total_statements=100, modules=[], delta=5.0
        )
        output = format_summary(result)
        assert "+5.0" in output

    def test_summary_omits_delta_when_no_baseline(self) -> None:
        result = CoverageResult(
            total_pct=85.0, total_covered=85, total_statements=100, modules=[], delta=None
        )
        output = format_summary(result)
        assert "delta" not in output.lower()
        assert "baseline" not in output.lower()


# ---------------------------------------------------------------------------
# TestFormatMarkdown
# ---------------------------------------------------------------------------


class TestFormatMarkdown:
    """Format coverage data as a Markdown table."""

    def test_produces_markdown_table(self) -> None:
        result = CoverageResult(
            total_pct=80.0,
            total_covered=80,
            total_statements=100,
            modules=[
                ModuleCoverage(name="domain", covered=50, total=60, pct=83.3),
                ModuleCoverage(name="adapters", covered=30, total=40, pct=75.0),
            ],
        )
        md = format_markdown(result)
        assert "| Module" in md
        assert "| domain" in md
        assert "| adapters" in md
        # Table separator
        assert "|---" in md

    def test_includes_total_line(self) -> None:
        result = CoverageResult(total_pct=80.0, total_covered=80, total_statements=100, modules=[])
        md = format_markdown(result)
        assert "80.0%" in md

    def test_includes_delta_when_present(self) -> None:
        result = CoverageResult(
            total_pct=85.0, total_covered=85, total_statements=100, modules=[], delta=2.5
        )
        md = format_markdown(result)
        assert "+2.5" in md

    def test_negative_delta_shown(self) -> None:
        result = CoverageResult(
            total_pct=78.0, total_covered=78, total_statements=100, modules=[], delta=-3.0
        )
        md = format_markdown(result)
        assert "-3.0" in md


# ---------------------------------------------------------------------------
# TestLoadBaseline
# ---------------------------------------------------------------------------


class TestLoadBaseline:
    """Load baseline from JSON file."""

    def test_loads_valid_baseline_file(self, tmp_path: Path) -> None:
        baseline_file = tmp_path / "coverage-baseline.json"
        baseline_file.write_text(json.dumps({"total_pct": 80.0, "modules": {}}))
        result = load_baseline(baseline_file)
        assert result is not None
        assert result["total_pct"] == 80.0

    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        result = load_baseline(tmp_path / "nonexistent.json")
        assert result is None

    def test_returns_none_when_file_malformed(self, tmp_path: Path) -> None:
        baseline_file = tmp_path / "coverage-baseline.json"
        baseline_file.write_text("not valid json {{{")
        result = load_baseline(baseline_file)
        assert result is None


# ---------------------------------------------------------------------------
# TestUpdateBaseline
# ---------------------------------------------------------------------------


class TestUpdateBaseline:
    """Write current coverage as baseline JSON."""

    def test_writes_valid_json(self, tmp_path: Path) -> None:
        result = CoverageResult(
            total_pct=85.123,
            total_covered=851,
            total_statements=1000,
            modules=[
                ModuleCoverage(name="domain", covered=500, total=600, pct=83.333),
                ModuleCoverage(name="adapters", covered=351, total=400, pct=87.75),
            ],
        )
        baseline_file = tmp_path / "coverage-baseline.json"
        update_baseline(result, baseline_file)

        written = json.loads(baseline_file.read_text())
        assert written["total_pct"] == 85.12
        assert written["total_covered"] == 851
        assert written["total_statements"] == 1000
        assert written["modules"]["domain"] == 83.33
        assert written["modules"]["adapters"] == 87.75

    def test_roundtrip_with_load_baseline(self, tmp_path: Path) -> None:
        result = CoverageResult(
            total_pct=96.5,
            total_covered=1277,
            total_statements=1324,
            modules=[ModuleCoverage(name="ports", covered=31, total=31, pct=100.0)],
        )
        baseline_file = tmp_path / "coverage-baseline.json"
        update_baseline(result, baseline_file)
        loaded = load_baseline(baseline_file)
        assert loaded is not None
        assert loaded["total_pct"] == 96.5
