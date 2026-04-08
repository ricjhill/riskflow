# Test Coverage Measurement and Tracking

**RiskFlow Engineering Session — 8 April 2026**

---

## Agenda

| # | Section | Time |
|---|---------|------|
| 1 | What We Did | 3 min |
| 2 | Why Coverage Tracking | 3 min |
| 3 | The Coverage Tool | 5 min |
| 4 | Pre-commit Hook Integration | 3 min |
| 5 | CI Integration & PR Comments | 5 min |
| 6 | The CI Fix: Cobertura vs JUnit | 3 min |
| 7 | By the Numbers | 3 min |
| 8 | What's Next | 2 min |

---

## 1. What We Did (3 min)

One PR, two commits, one GitHub issue:

| PR/Issue | Title | Theme |
|----------|-------|-------|
| #127 | Add test coverage measurement and tracking | Issue (plan) |
| #128 | Add test coverage measurement and tracking | PR |

Starting point: 729+ unit tests but no way to know which lines they cover, no coverage trends, no coverage data in PRs.

Ending point: pytest-cov integrated, a reporting tool with 22 tests, coverage in pre-commit hook output, CI step summary, and sticky PR comments. Initial baseline: 96.5%.

---

## 2. Why Coverage Tracking (3 min)

### The problem

We had been doing test coverage audits manually — reading every production module against the testing rules and listing gaps by eye (PRs #119, #123). This worked for one-off gap-filling but:

- No way to tell if a new PR regressed coverage
- No way to see which modules are weakest at a glance
- No data in PRs for reviewers to assess test quality
- No baseline to measure progress against

### The approach

Self-contained, no external services. Three integration points:

```
Developer          CI                     PR
┌──────────┐     ┌──────────────┐     ┌──────────────┐
│ pre-commit│     │ unit tests   │     │ sticky       │
│ hook      │     │ + --cov      │     │ coverage     │
│ shows     │     │              │     │ comment      │
│ TOTAL %   │     │ ↓            │     │ (upserted)   │
└──────────┘     │ coverage.json│     └──────────────┘
                  │ ↓            │
                  │ STEP_SUMMARY │
                  └──────────────┘
```

---

## 3. The Coverage Tool (5 min)

### Design

`tools/coverage_report.py` follows the existing tools/ pattern — module docstring, pure functions, `main()` with argparse, `__main__` block.

**CLI interface:**

```
uv run python -m tools.coverage_report                # run tests + print summary
uv run python -m tools.coverage_report --no-run       # parse existing reports/coverage.json
uv run python -m tools.coverage_report --markdown     # output Markdown for PR comments
uv run python -m tools.coverage_report --json         # output JSON
uv run python -m tools.coverage_report --update-baseline  # write coverage-baseline.json
```

### Pure functions (tested independently)

| Function | Purpose |
|----------|---------|
| `parse_coverage_json(data)` | Extract totals + per-module breakdown from coverage JSON |
| `load_baseline(path)` | Read baseline file, return None if missing/malformed |
| `compare_baseline(result, baseline)` | Set delta on result |
| `format_summary(result)` | Human-readable terminal output |
| `format_markdown(result)` | Markdown table for PR comments and `$GITHUB_STEP_SUMMARY` |
| `update_baseline(result, path)` | Write current coverage as new baseline JSON |

### Data structures

```python
@dataclass
class ModuleCoverage:
    name: str       # e.g. "domain", "adapters"
    covered: int
    total: int
    pct: float

@dataclass
class CoverageResult:
    total_pct: float
    total_covered: int
    total_statements: int
    modules: list[ModuleCoverage]
    delta: float | None = None  # vs baseline
```

### Baseline file (`coverage-baseline.json`)

```json
{
  "total_pct": 96.45,
  "total_covered": 1277,
  "total_statements": 1324,
  "modules": {
    "adapters": 97.47,
    "domain": 97.18,
    "entrypoint": 87.88,
    "ports": 100.0
  }
}
```

Committed to the repo, updated manually via `--update-baseline`. No auto-ratchet — developers decide when to raise the bar.

### Tests (22 unit tests)

| Class | Tests | What it covers |
|-------|-------|----------------|
| `TestParseCoverageJson` | 5 | Valid input, empty coverage, module grouping, aggregation, sort order |
| `TestCompareBaseline` | 4 | No baseline, improvement, regression, no change |
| `TestFormatSummary` | 4 | Total %, module breakdown, delta present, delta absent |
| `TestFormatMarkdown` | 4 | Table structure, total line, positive delta, negative delta |
| `TestLoadBaseline` | 3 | Valid file, missing file, malformed JSON |
| `TestUpdateBaseline` | 2 | Writes valid JSON with rounding, roundtrip with load |

---

## 4. Pre-commit Hook Integration (3 min)

### What changed in `.claude/hooks/pre-commit.sh`

The hook already ran `uv run pytest -x -v tests/unit/`. Two changes:

1. **Added `--cov=src --cov-report=term-missing`** to the existing pytest command — piggybacks coverage measurement on the test run, no double execution.

2. **Echoes TOTAL line on success** — after all four checks (mypy, pytest, ruff check, ruff format) pass, extracts and prints the coverage total.

### The `$OUTPUT` bug (caught by code-reviewer)

The original implementation reused the `$OUTPUT` variable across all four steps. By the time the TOTAL grep ran, `$OUTPUT` held ruff format output, not pytest output. The coverage line was never displayed.

**Fix:** Pytest output is captured as `$PYTEST_OUTPUT` and referenced separately at the end:

```bash
PYTEST_OUTPUT=$(uv run pytest -x -v tests/unit/ --cov=src --cov-report=term-missing 2>&1)
# ... later ...
COV_LINE=$(echo "$PYTEST_OUTPUT" | grep "^TOTAL" | head -1)
```

---

## 5. CI Integration & PR Comments (5 min)

### Coverage flags on unit test step

```yaml
- name: Run unit tests
  run: >-
    uv run pytest -x -v tests/unit/
    --junitxml=reports/unit.xml
    --cov=src
    --cov-report=xml:reports/coverage.xml
    --cov-report=json:reports/coverage.json
    --cov-report=term-missing
```

Three coverage formats generated alongside the existing JUnit XML:
- **XML (Cobertura)** — for future integrations (e.g. GitHub coverage annotations)
- **JSON** — parsed by the coverage tool for summaries
- **term-missing** — visible in CI step logs

### Step summary

```yaml
- name: Coverage summary
  if: always() && hashFiles('reports/coverage.json') != ''
  run: uv run python -m tools.coverage_report --no-run >> $GITHUB_STEP_SUMMARY
```

Writes the human-readable summary to the workflow run page. Uses `--no-run` to parse the already-generated JSON without re-running tests.

### Sticky PR comment

```yaml
- name: Comment coverage on PR
  if: github.event_name == 'pull_request' && hashFiles('reports/coverage.json') != ''
  uses: actions/github-script@v7
```

Uses `--markdown` flag to get formatted output, then upserts via a `<!-- coverage-report -->` HTML marker. Finds existing comment and updates it in place, or creates a new one — no comment spam on multi-push PRs.

Required adding `pull-requests: write` to the quality job permissions.

---

## 6. The CI Fix: Cobertura vs JUnit (3 min)

### What broke

The first CI run on PR #128 failed at the "Publish test report" step:

```
Processing test results from reports/coverage.xml failed
TypeError: Cannot read properties of undefined (reading '$')
```

### Why

`dorny/test-reporter@v3` used `reports/*.xml` which now matched both JUnit files (`unit.xml`, `integration.xml`, etc.) and the new `coverage.xml` (Cobertura format). The reporter tried to parse Cobertura XML as JUnit and crashed.

### The fix

Switched from a wildcard to an explicit list:

```yaml
path: "reports/unit.xml,reports/integration.xml,reports/contract.xml,reports/benchmark.xml,reports/load.xml"
```

Coverage XML is still uploaded as an artifact (the `upload-artifact` step uses `reports/` which includes everything), but it's no longer fed to the JUnit parser.

---

## 7. By the Numbers (3 min)

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Unit tests | 729 | 751 | +22 |
| Coverage measurement | none | 96.5% | — |
| Coverage in PRs | none | sticky comment | — |
| Coverage in CI | none | step summary + artifacts | — |
| Coverage in pre-commit | none | TOTAL line echo | — |
| Files created | — | 3 | — |
| Files modified | — | 7 | — |

### New files

```
tools/coverage_report.py         — 241 lines
tests/unit/test_coverage_report.py — 310 lines
coverage-baseline.json           — 11 lines
```

### Coverage by module

```
adapters     97.5%   579/594
domain       97.2%   551/567
entrypoint   87.9%   116/132
ports       100.0%    31/31
─────────────────────────────
TOTAL        96.5%  1277/1324
```

---

## 8. What's Next (2 min)

### Immediate
- Monitor CI run on PR #128 to confirm the Cobertura/JUnit fix works
- Merge once CI is green

### Short-term
- Add `--cov-fail-under` threshold once baseline is stable (ratchet enforcement)
- Extend coverage to integration tests (separate `--cov-append` step or combined run)
- Add per-file coverage to PR comments (not just per-module)

### Medium-term
- Coverage trend tracking across PRs (store historical baselines)
- Coverage annotations in GitHub (map uncovered lines to PR diff)
- Wire `tools/` directory into mypy strict checking in CI

---

## Key Takeaway

> You can't improve what you don't measure. 729 tests sounded impressive, but without coverage data we couldn't tell if they were testing the right things. Now every commit shows the TOTAL line, every PR gets a coverage comment, and every CI run records exactly which lines are — and aren't — tested.
