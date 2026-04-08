# Test Coverage Tracking, Cross-Repo Parity & Housekeeping

**RiskFlow Engineering Session — 8 April 2026**

---

## Agenda

| # | Section | Time |
|---|---------|------|
| 1 | What We Did | 3 min |
| 2 | Why Coverage Tracking | 3 min |
| 3 | The Coverage Tool (riskflow) | 5 min |
| 4 | Pre-commit Hook Integration | 3 min |
| 5 | CI Integration & PR Comments | 5 min |
| 6 | The CI Fix: Cobertura vs JUnit | 3 min |
| 7 | Coverage Parity: riskflow-ui | 4 min |
| 8 | PR Template: Tested-at Version | 2 min |
| 9 | Session Presentation Update | 2 min |
| 10 | By the Numbers | 3 min |
| 11 | What's Next | 2 min |

---

## 1. What We Did (3 min)

Four PRs merged across two repos, two GitHub issues created:

**riskflow:**

| PR/Issue | Title | Theme |
|----------|-------|-------|
| #127 | Add test coverage measurement and tracking | Issue (plan) |
| #128 | Add test coverage measurement and tracking | Coverage |
| #129 | Add tested version info to PR template | Issue (plan) |
| #130 | Add tested-at version and SHA to PR template | PR template |

**riskflow-ui:**

| PR/Issue | Title | Theme |
|----------|-------|-------|
| #50 | Code coverage gating with vitest | Issue (existing) |
| #81 | Add vitest code coverage with V8 provider | Coverage |
| #80 | Auto-invoke issue-lifecycle agent from /create-pr | Merge (rebase fix) |

Starting point: no coverage measurement in either repo, no version tracking in PRs, session presentation missing 4 PRs.

Ending point: both repos have coverage measurement with CI integration and sticky PR comments, PR template includes tested-at version/SHA, session presentation fully up to date.

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

## 7. Coverage Parity: riskflow-ui (4 min)

### Why parity matters

Having coverage in the backend but not the frontend creates a blind spot. Reviewers can assess backend test quality from the PR comment but have to guess for the frontend.

### What we added (PR riskflow-ui#81)

Installed `@vitest/coverage-v8` and configured coverage in `vite.config.ts`:

```typescript
coverage: {
  provider: 'v8',
  include: ['src/**/*.{ts,tsx}'],
  exclude: ['src/test/**', 'src/types/**', '**/*.test.{ts,tsx}', '**/*.d.ts'],
  reporter: ['text', 'json-summary', 'lcov'],
  reportsDirectory: 'reports/coverage',
}
```

CI changes mirror riskflow's pattern:
- Tests run with `--coverage` flag
- Coverage summary written to `$GITHUB_STEP_SUMMARY`
- Sticky PR comment via `actions/github-script@v7` with `<!-- coverage-report -->` marker
- `reports/unit.xml` explicitly listed for JUnit reporter (learned from riskflow's Cobertura fix)

### Bonus: Vite security fix

The `npm audit` step caught 3 high-severity CVEs in vite 8.0.4 (path traversal, fs.deny bypass, arbitrary file read via WebSocket). Fixed by upgrading to 8.0.7 in the same PR.

### Initial baseline

```
Statements  89.8%
Branches    80.2%
Functions   89.7%
Lines       92.4%
```

---

## 8. PR Template: Tested-at Version (2 min)

### The problem

PRs show test results but not which commit they ran against. If a PR is rebased after tests ran, the reported results may be stale with no way to tell.

### The solution (PR #130)

Two lines added to `.claude/skills/create-pr/SKILL.md`:

1. **Phase 1 step 9:** Gather git SHA and riskflow version
2. **Phase 4 Checks table:** New `tested at` row showing `v0.1.0 (cef765b)`

No new tools, tests, or dependencies — just a template change. Reviewers can now compare the SHA in the PR against the branch HEAD to verify freshness.

---

## 9. Session Presentation Update (2 min)

The 2026-04-06 presentation was missing coverage of 4 PRs that landed the same day but after the presentation was committed:

| PR | What was missing |
|----|-----------------|
| #121 | Structured row errors (`FieldError` model) |
| #123 | 11 medium-priority test gaps filled |
| #125 | `RequestIdMiddleware` with structlog contextvars |
| #126 | CLAUDE.md architecture tree cleanup |

Updated the presentation with new sections, corrected test counts (729 not 716), and revised the "What's Next" section.

---

## 10. By the Numbers (3 min)

### riskflow

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Unit tests | 729 | 751 | +22 |
| Coverage measurement | none | 96.5% | — |
| Coverage in PRs | none | sticky comment | — |
| Coverage in CI | none | step summary + artifacts | — |
| Coverage in pre-commit | none | TOTAL line echo | — |
| PR version tracking | none | tested-at row | — |
| PRs merged | — | 2 (#128, #130) | — |

### riskflow-ui

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Coverage measurement | none | 89.8% stmts | — |
| Coverage in PRs | none | sticky comment | — |
| Coverage in CI | none | step summary + artifacts | — |
| Vite CVEs | 3 high | 0 | -3 |
| PRs merged | — | 2 (#80, #81) | — |

### Coverage by module (riskflow)

```
adapters     97.5%   579/594
domain       97.2%   551/567
entrypoint   87.9%   116/132
ports       100.0%    31/31
─────────────────────────────
TOTAL        96.5%  1277/1324
```

---

## 11. What's Next (2 min)

### Short-term
- Add `--cov-fail-under` threshold to both repos once baselines are stable
- Add vitest coverage thresholds to riskflow-ui (`thresholds` config in vite.config.ts)
- Extend riskflow coverage to integration tests

### Medium-term
- Coverage trend tracking across PRs (store historical baselines)
- Coverage annotations in GitHub (map uncovered lines to PR diff)
- Wire `tools/` directory into mypy strict checking in CI
- riskflow-ui backlog: dependency audit hook (#51), consolidated security checks (#64)

---

## Key Takeaway

> You can't improve what you don't measure — and you can't measure consistently if only half your stack is instrumented. This session brought coverage parity across both repos, gave PRs version traceability, and caught 3 high-severity CVEs along the way. Every commit, every PR, and every CI run now answers: what's tested, how well, and against which code.
