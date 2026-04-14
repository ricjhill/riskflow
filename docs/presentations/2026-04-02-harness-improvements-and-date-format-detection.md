# Harness Improvements & Column-Level Date Format Detection

**RiskFlow Engineering Session — 2 April 2026**
**Duration: 45 minutes**

---

## Agenda

| # | Section | Time |
|---|---------|------|
| 1 | What We Set Out To Do | 3 min |
| 2 | Harness Improvement #1: Runtime Dependency Check Hook | 7 min |
| 3 | Harness Improvement #2: Post-Rename Stale Reference Detection | 5 min |
| 4 | Harness Improvement #3: Fixture-Based Upload Integration Tests | 6 min |
| 5 | The ISO Date Misparsing Bug | 5 min |
| 6 | Auditing the Boundary Tests | 5 min |
| 7 | Column-Level Date Format Detection | 8 min |
| 8 | By the Numbers | 3 min |
| 9 | Lessons Learned | 3 min |

---

## 1. What We Set Out To Do (3 min)

We started with a harness improvement roadmap — four items ranked by value, each traced to a real pain point from the previous session:

| # | Improvement | Triggered by | Status |
|---|-------------|-------------|--------|
| 1 | Runtime dependency check hook | python-dateutil + pyyaml crashed production containers | Done (PR #91) |
| 2 | Post-rename stale reference detection | Renaming default.yaml left 10+ stale references | Done (PR #92) |
| 3 | Fixture-based upload integration tests | Date format bug only found by manual GUI testing | Done (PR #93) |
| 4 | PostToolUse failure context hook | Future — value grows as codebase grows | Deferred |

Then the fixture tests uncovered a real bug that led to a full feature: column-level date format detection (PR #94).

---

## 2. Runtime Dependency Check Hook (7 min)

### The Problem

PR #90 caused two production container crashes:
- `python-dateutil`: imported in `src/`, only installed because `streamlit` (dev dep) pulls it in
- `pyyaml`: same — imported in `src/`, only a transitive dep of streamlit

Both worked locally (dev deps installed) but failed in Docker (`uv sync --no-dev`).

### The Solution

A pre-commit hook that scans all imports in `src/` using AST parsing and verifies each maps to a `[project].dependencies` entry.

```python
def _get_third_party_imports() -> set[str]:
    """Scan all .py files in src/ via ast.parse, extract top-level imports."""
    for py_file in SRC_DIR.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # Extract top-level module name
            elif isinstance(node, ast.ImportFrom):
                # Extract top-level module name
    # Filter out stdlib and internal imports
```

### Import Name Mapping

Python import names don't always match PyPI package names:

```python
IMPORT_TO_PACKAGE = {
    "yaml": "pyyaml",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "pydantic_settings": "pydantic-settings",
}
```

### Already Caught a Bug

During development, the test found `pydantic` was missing from runtime deps — imported everywhere in `src/` but only declared via `pydantic-settings` (which transitively pulls it in). Third production failure prevented.

### PEP 508 Parser

The code reviewer caught that the version specifier parser didn't handle `!=`, `[extras]`, or `; markers`. Fixed with a proper three-step parser:

```python
def _parse_package_name(dep_str: str) -> str:
    # 1. Strip environment markers: "pkg; python>='3.10'" → "pkg"
    name = dep_str.split(";")[0].strip()
    # 2. Strip extras: "requests[security]" → "requests"
    name = re.split(r"\[", name)[0]
    # 3. Strip version specifiers: "fastapi>=0.135" → "fastapi"
    name = re.split(r"[><=!~]", name)[0].strip()
    return name
```

### Hook Wiring

```
PreToolUse (Bash) → triggers on git commit → runs pytest test → blocks if deps missing
```

**16 tests:** import scan, known-problematic packages, 4 mapping cases, 8 PEP 508 parser cases, stdlib exclusion, internal import exclusion.

---

## 3. Post-Rename Stale Reference Detection (5 min)

### The Problem

Renaming `schemas/default.yaml` to `standard_reinsurance.yaml` left 10+ stale references across docs, rules, agents, and tests. Found manually over two days.

### The Solution

PostToolUse hook on Bash that fires after `mv` or `git mv`:

```bash
# Extract old filename via Python shlex parser
OLD_PATH=$(python3 -c "
import sys, shlex
args = shlex.split(sys.argv[1])
paths = [a for a in args[1:] if not a.startswith('-')]
print(paths[0])
" "$COMMAND")

# Grep for stale references
REFS=$(grep -r --include='*.py' --include='*.md' --include='*.yaml' \
  --include='*.json' --include='*.toml' --include='*.sh' \
  -l "$OLD_NAME" . | grep -v '\.git/')
```

### Non-Blocking by Design

The hook outputs `hookSpecificOutput.additionalContext` JSON — injects findings into the agent context so it fixes them proactively. Doesn't block because the rename is already done.

### What It Catches

| Scenario | Result |
|----------|--------|
| `mv old.yaml new.yaml` (refs exist) | Lists files with stale references |
| `git mv old.yaml new.yaml` | Same detection |
| `ls -la` (not a rename) | Silent skip |
| `mv old.yaml new.yaml` (no refs) | Silent — nothing to report |

---

## 4. Fixture-Based Upload Integration Tests (6 min)

### The Problem

The date format bug (DD-Mon-YYYY rejection) was only caught by manual GUI testing. 27 unit tests existed but none uploaded a real file through the full pipeline.

### The Solution

10 integration tests uploading real fixture files through FastAPI TestClient with mocked SLM:

| Test Class | Fixture | Rows | What It Proves |
|------------|---------|------|----------------|
| TestReinsuranceCSVFixture | sample_bordereaux.csv | 5 | CSV → all valid, fields mapped, unmapped captured |
| TestReinsuranceExcelFixture | reinsurance_bordereaux_messy.xlsx | 10 | Mixed date formats all validate, extra columns unmapped |
| TestMarineCargoCSVFixture | sample_marine_cargo.csv | 5 | Marine schema, port fields mapped |
| TestMultiSheetExcelFixture | multi_sheet_bordereaux.xlsx | 5+3 | Sheet selection, /sheets endpoint |

### Found a Real Bug Immediately

The marine cargo CSV had 3 out of 5 rows failing:

```
Arrival_Date must not be before Voyage_Date
```

`dateutil.parser.parse("2024-04-02", dayfirst=True)` returns **February 4** instead of April 2. The `dayfirst=True` flag reassigns the second component (04) as the day and the third (02) as the month after identifying the year.

---

## 5. The ISO Date Misparsing Bug (5 min)

### Root Cause

With `dayfirst=True`, dateutil correctly identifies 2025 as the year (too large for day/month), but then assigns the remaining components with day-first ordering:

```
"2024-04-02" → year=2024, day=04, month=02 → February 4 (WRONG)
"2024-08-15" → year=2024, day=15, month=08 → August 15 (CORRECT — 15 > 12)
```

Only dates where the day component is 1-12 are affected — roughly 40% of all dates.

### The Fix (PR #93)

Try `datetime.date.fromisoformat()` first (unambiguous for YYYY-MM-DD), fall back to dateutil only for non-ISO formats:

```python
def coerce_date(value):
    # 1. ISO 8601 first — unambiguous
    try:
        return datetime.date.fromisoformat(stripped)
    except ValueError:
        pass
    # 2. YYYY/MM/DD — year-first with slashes
    # 3. dateutil with dayfirst=True — broker formats
```

---

## 6. Auditing the Boundary Tests (5 min)

### Why the Tests Missed It

The existing ISO test case was `"2025-01-15"` — day=15 is > 12, so dateutil can't misparse it regardless of `dayfirst`. The boundary that matters is **both month and day are valid month numbers (1-12)**.

### Confirmed Gaps

| Gap | Input | Confirmed? | Risk |
|-----|-------|-----------|------|
| DD/MM/YYYY dayfirst verification | `"02/04/2024"` | Works correctly | No bug, but untested |
| Feb 30 DD-Mon format | `"30-Feb-2025"` | Rejected by dateutil | No bug |
| Jun 31 DD-Mon format | `"31-Jun-2025"` | Rejected by dateutil | No bug |
| **Month 13 ISO** | `"2025-13-05"` | **Silently becomes May 13** | Data integrity risk |
| YYYY/MM/DD misparsing | `"2025/07/01"` | **Becomes January 7** | Data integrity risk |

### Tests Added

- `"2024-04-02"` and `"2024-09-06"` — ISO ambiguous boundary
- `"02/04/2024"` — DD/MM/YYYY dayfirst verification
- `"2025-13-05"` — documented lenient behavior (month 13 silently accepted)

---

## 7. Column-Level Date Format Detection (8 min)

### The Remaining Problem

YYYY/MM/DD dates (`"2025/07/01"`) are silently misparsed as January 7. Slashes aren't valid ISO, so `fromisoformat` rejects it and dateutil with `dayfirst=True` swaps month and day.

Per-value parsing can't tell YYYY/MM/DD from DD/MM/YYYY. But looking at 5 sample values, the year position is obvious.

### The Design

New pure domain module `src/domain/model/date_format.py`:

```python
def detect_date_format(values: list[str]) -> str | None:
    """Detect format from sample column values.
    Returns: "iso", "yyyy_slash", "named_month", "dayfirst", or None
    """

def parse_date(value: str, format_hint: str | None) -> datetime.date:
    """Parse using the detected format hint."""
```

### Detection Heuristics

| Pattern | Regex | Example | Result |
|---------|-------|---------|--------|
| ISO 8601 | `^\d{4}-\d{2}-\d{2}$` | `"2025-01-15"` | `"iso"` |
| YYYY/MM/DD | `^\d{4}/\d{1,2}/\d{1,2}$` | `"2025/07/01"` | `"yyyy_slash"` |
| Named month | contains Jan/Feb/January... | `"01-Jan-2025"` | `"named_month"` |
| DD/MM/YYYY | `^\d{1,2}/\d{1,2}/\d{4}$` | `"15/01/2025"` | `"dayfirst"` |
| Mixed/unknown | none match | | `None` |

### Service Layer Wiring

In `MappingService._validate_rows()`, after renaming columns but before `model_validate()`:

```python
# 1. Identify DATE fields from schema
date_field_names = {
    name for name, defn in self._schema.fields.items()
    if defn.type == FieldType.DATE
}

# 2. Sample 5 values per date column, detect format
for field_name in date_field_names:
    sample = df[field_name].head(5).to_list()
    date_formats[field_name] = detect_date_format(str_samples)

# 3. Pre-convert date strings using detected format
for row in rows:
    for field_name, fmt in date_formats.items():
        row[field_name] = parse_date(str(val), fmt)
```

`model_validate()` then receives `datetime.date` objects, which `coerce_date()` passes through unchanged.

### Belt and Suspenders

For mixed-format columns (detection returns `None`), the fallback parsing order is:

```
ISO (fromisoformat) → YYYY/MM/DD (regex) → dateutil (dayfirst=True)
```

This is applied in both `parse_date(val, None)` and `coerce_date()`, so YYYY/MM/DD is handled correctly even when column detection can't determine a single format.

### 11 TDD Loops

| Loop | What | Tests |
|------|------|-------|
| 1 | ISO detection | 2 |
| 2 | YYYY/MM/DD detection | 2 |
| 3-5 | Named month, DD/MM/YYYY, edge cases | 10 |
| 6-8 | parse_date all formats + errors | 12 |
| 9 | Wire into MappingService | 1 |
| 10 | Integration test (Excel row 10 = July 1) | 1 |
| 11 | Full checks + review fixes | — |

---

## 8. By the Numbers (3 min)

| Metric | Start of session | End of session |
|--------|-----------------|----------------|
| PRs merged | 90 | 95 |
| Unit tests | 499 | 541 |
| Hooks | 6 | 8 (+ runtime deps, + post-rename) |
| Source files | 34 | 35 (+ date_format.py) |
| Test files | — | + test_date_format.py, test_runtime_deps.py, test_fixture_upload.py |
| Production bugs found | 0 | 3 (pydantic dep, ISO misparsing, YYYY/MM/DD misparsing) |

### PRs This Session

| PR | Title | Tests added |
|----|-------|-------------|
| #91 | Runtime dependency check hook | 16 |
| #92 | Post-rename stale reference detection | 0 (shell hook) |
| #93 | Fixture upload tests + ISO date fix | 12 |
| #94 | Column-level date format detection | 28 |
| #95 | Cleanup: CLAUDE.md architecture tree | 0 |

### Permission Improvements

Added to auto-allow: `git push`, `gh`, `docker compose`, `ls`, `find`, `cat`. Kept prompting: `python3 -c`, `mv`, `chmod`, `git rm`.

---

## 9. Lessons Learned (3 min)

### 1. Harness improvements pay for themselves immediately

The runtime dependency check found `pydantic` missing during its first run. The fixture tests found the ISO misparsing bug on first upload. The post-rename hook would have saved two days of manual grep-and-fix on the `default.yaml` rename. Every improvement justified its cost within the session.

### 2. Boundary tests need adversarial thinking

The original ISO test used `"2025-01-15"` (day=15 > 12). The boundary that matters — both components valid as months — was untested. The fix: systematically ask "what input would be valid for multiple interpretations?" not just "what input is invalid?"

### 3. Column context beats per-value guessing

`dateutil` is a general-purpose parser. It doesn't know that a column of dates should all use the same format. By sampling 5 values and detecting the pattern once, we eliminate an entire class of ambiguity bugs. The per-value fallback remains as a safety net for mixed-format columns.

### 4. Integration tests find bugs that unit tests can't

27 date coercion unit tests all passed. The bug only appeared when uploading a real CSV with ISO dates through the full pipeline (ingest → map → validate → cross-field check). The cross-field date ordering rule was the canary — without it, the misparsed dates would have been silently accepted.

### 5. The post-edit lint hook fights you when building incrementally

Adding an import in one edit, then using it in the next edit, causes the linter to strip the import between edits. Workaround: add imports in the same edit as their usage. This is a known friction point with the hook-per-edit architecture.

---

## Lessons Learned (retrospective)

| Problem | Impact | How it was caught |
|---------|--------|-------------------|
| Post-edit lint hook stripped imports added in one edit before they were used in the next | Forced workaround: add imports in the same edit as usage | Discovered during incremental development — known friction point |
| ISO date misparsing: `2025/07/15` parsed as July 15 in some locales, January 5 in others | Silent data corruption on ambiguous dates | Integration test with fixture data (PR #93) |
| YYYY/MM/DD format not detected by date_format module | Dates in this format fell through to generic parsing with wrong dayfirst assumption | Test failure on real bordereaux data |

**Key insight:** Date parsing is a minefield of silent failures. The fix wasn't just better parsing — it was column-level format detection that locks in the format from sample data before parsing the full column.
