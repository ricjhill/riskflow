"""Test coverage measurement and reporting.

Parses coverage.json output from pytest-cov, compares against a committed
baseline, and produces human-readable or Markdown summaries. Designed to
run locally (with test execution) or in CI (parsing pre-existing reports).

Usage:
    uv run python -m tools.coverage_report                # run tests + print summary
    uv run python -m tools.coverage_report --no-run       # parse existing reports/coverage.json
    uv run python -m tools.coverage_report --update-baseline  # also update coverage-baseline.json
    uv run python -m tools.coverage_report --json         # output JSON to stdout

Exit codes:
    0 — success
    1 — error (missing report, test failure, etc.)
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

BASELINE_PATH = Path("coverage-baseline.json")
COVERAGE_JSON_PATH = Path("reports/coverage.json")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ModuleCoverage:
    """Coverage stats for a top-level module (e.g. domain, adapters)."""

    name: str
    covered: int
    total: int
    pct: float


@dataclass
class CoverageResult:
    """Parsed coverage data with optional baseline delta."""

    total_pct: float
    total_covered: int
    total_statements: int
    modules: list[ModuleCoverage]
    delta: float | None = field(default=None)


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def parse_coverage_json(data: dict) -> CoverageResult:
    """Extract coverage summary and per-module breakdown from coverage JSON."""
    totals = data.get("totals", {})
    total_covered = totals.get("covered_lines", 0)
    total_stmts = totals.get("num_statements", 0)
    total_pct = totals.get("percent_covered", 100.0) if total_stmts > 0 else 100.0

    # Group files by top-level module under src/
    module_stats: dict[str, tuple[int, int]] = {}
    for file_path, file_data in data.get("files", {}).items():
        parts = file_path.replace("src/", "", 1).split("/")
        if not parts:
            continue
        module_name = parts[0]
        summary = file_data.get("summary", {})
        covered = summary.get("covered_lines", 0)
        stmts = summary.get("num_statements", 0)
        prev_covered, prev_total = module_stats.get(module_name, (0, 0))
        module_stats[module_name] = (prev_covered + covered, prev_total + stmts)

    modules = []
    for name in sorted(module_stats):
        covered, total = module_stats[name]
        pct = (covered / total * 100) if total > 0 else 100.0
        modules.append(ModuleCoverage(name=name, covered=covered, total=total, pct=pct))

    return CoverageResult(
        total_pct=total_pct,
        total_covered=total_covered,
        total_statements=total_stmts,
        modules=modules,
    )


def load_baseline(path: Path) -> dict | None:
    """Load baseline JSON. Returns None if missing or malformed."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def compare_baseline(result: CoverageResult, baseline: dict | None) -> CoverageResult:
    """Set result.delta based on baseline comparison. Returns the same result."""
    if baseline is None:
        result.delta = None
    else:
        result.delta = result.total_pct - baseline.get("total_pct", 0.0)
    return result


def format_summary(result: CoverageResult) -> str:
    """Human-readable multiline summary for terminal output."""
    lines = [
        f"Total coverage: {result.total_pct:.1f}% ({result.total_covered}/{result.total_statements} lines)",
    ]
    if result.delta is not None:
        sign = "+" if result.delta >= 0 else ""
        lines[0] += f"  ({sign}{result.delta:.1f}% vs baseline)"

    if result.modules:
        lines.append("")
        lines.append("  Module          Coverage   Lines")
        lines.append("  " + "-" * 40)
        for m in result.modules:
            lines.append(f"  {m.name:<16} {m.pct:>6.1f}%   {m.covered}/{m.total}")

    return "\n".join(lines)


def format_markdown(result: CoverageResult) -> str:
    """Markdown table suitable for PR comments and GITHUB_STEP_SUMMARY."""
    delta_str = ""
    if result.delta is not None:
        sign = "+" if result.delta >= 0 else ""
        delta_str = f" ({sign}{result.delta:.1f}% vs baseline)"

    lines = [
        "## Test Coverage",
        "",
        f"**Total: {result.total_pct:.1f}%**{delta_str} ({result.total_covered}/{result.total_statements} lines)",
        "",
    ]

    if result.modules:
        lines.append("| Module | Coverage | Lines |")
        lines.append("|--------|----------|-------|")
        for m in result.modules:
            lines.append(f"| {m.name} | {m.pct:.1f}% | {m.covered}/{m.total} |")
        lines.append("")

    return "\n".join(lines)


def update_baseline(result: CoverageResult, path: Path) -> None:
    """Write current coverage as the new baseline."""
    data = {
        "total_pct": round(result.total_pct, 2),
        "total_covered": result.total_covered,
        "total_statements": result.total_statements,
        "modules": {m.name: round(m.pct, 2) for m in result.modules},
    }
    path.write_text(json.dumps(data, indent=2) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run_tests_with_coverage() -> bool:
    """Run pytest with coverage flags. Returns True if tests passed."""
    cmd = [
        "uv",
        "run",
        "pytest",
        "-x",
        "tests/unit/",
        "--cov=src",
        "--cov-report=json:" + str(COVERAGE_JSON_PATH),
        "--cov-report=xml:reports/coverage.xml",
        "--cov-report=term-missing",
    ]
    proc = subprocess.run(cmd, check=False)
    return proc.returncode == 0


def main() -> int:
    """Orchestrate coverage reporting. Returns exit code."""
    import argparse

    parser = argparse.ArgumentParser(description="Coverage report tool")
    parser.add_argument(
        "--no-run", action="store_true", help="Skip running tests, parse existing report"
    )
    parser.add_argument(
        "--update-baseline", action="store_true", help="Update coverage-baseline.json"
    )
    parser.add_argument(
        "--json", action="store_true", dest="output_json", help="Output JSON to stdout"
    )
    parser.add_argument("--markdown", action="store_true", help="Output Markdown (for PR comments)")
    args = parser.parse_args()

    if not args.no_run:
        if not run_tests_with_coverage():
            print("Tests failed — coverage report not generated.", file=sys.stderr)
            return 1

    if not COVERAGE_JSON_PATH.exists():
        print(f"Coverage report not found: {COVERAGE_JSON_PATH}", file=sys.stderr)
        return 1

    data = json.loads(COVERAGE_JSON_PATH.read_text())
    result = parse_coverage_json(data)
    baseline = load_baseline(BASELINE_PATH)
    result = compare_baseline(result, baseline)

    if args.update_baseline:
        update_baseline(result, BASELINE_PATH)
        print(f"Baseline updated: {BASELINE_PATH}", file=sys.stderr)

    if args.output_json:
        out = {
            "total_pct": round(result.total_pct, 2),
            "total_covered": result.total_covered,
            "total_statements": result.total_statements,
            "delta": round(result.delta, 2) if result.delta is not None else None,
            "modules": {m.name: round(m.pct, 2) for m in result.modules},
        }
        print(json.dumps(out, indent=2))
    elif args.markdown:
        print(format_markdown(result))
    else:
        print(format_summary(result))

    return 0


if __name__ == "__main__":
    sys.exit(main())
