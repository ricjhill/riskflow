# Flexible Date Parsing & Production Hardening

**RiskFlow Engineering Session — 31 March 2026**
**Duration: 45 minutes**

---

## Agenda

| # | Section | Time |
|---|---------|------|
| 1 | Context: What is RiskFlow? | 3 min |
| 2 | The Problem: Manual Testing Reveals Date Failures | 5 min |
| 3 | Creating Test Data | 4 min |
| 4 | TDD Cycle: Failing Tests First | 6 min |
| 5 | Implementation: coerce_date and FlexibleDate | 7 min |
| 6 | Agent-to-Agent Code Review | 5 min |
| 7 | CI Debugging: The Boot-Test Mystery | 7 min |
| 8 | GUI Debugging: The Schema File Mismatch | 4 min |
| 9 | Summary & Lessons Learned | 4 min |

---

## 1. Context: What is RiskFlow?

### The Problem RiskFlow Solves

Reinsurance companies receive **bordereaux** — messy spreadsheets from brokers containing policy data. Each broker uses different column names, date formats, currencies, and layouts.

RiskFlow automates the mapping of these spreadsheets to a standardized schema using Small Language Models (SLMs via Groq/Llama 3.3).

### Architecture

```
Broker uploads CSV/Excel
        |
        v
  FastAPI /upload endpoint
        |
        v
  SLM maps column headers --> "GWP" -> Gross_Premium (0.95 confidence)
        |
        v
  Row-by-row Pydantic validation
        |
        v
  Clean, validated records + error report
```

### Stack

- **Python 3.12**, FastAPI, Polars, Redis, Groq API
- **Hexagonal architecture** — domain logic has zero infrastructure dependencies
- **Dynamic schema validation** — schemas defined in YAML, Pydantic models built at runtime

---

## 2. The Problem: Manual Testing Reveals Date Failures

### What Happened

We created Excel test data to manually test the Streamlit GUI. The reinsurance spreadsheet used dates like brokers actually write them:

```
01-Jan-2025    (DD-Mon-YYYY — London market standard)
15-Feb-2025
01-Mar-2025
```

### What We Expected

The mapper would identify the date columns, and the validator would accept the rows.

### What Actually Happened

**Every single row failed validation.**

```
Row 1: 2 validation errors for DynamicRecord_standard_reinsurance
  Inception_Date: Input should be a valid date or datetime,
    invalid character in year
    [input_value='01-Jan-2025', input_type=str]
  Expiry_Date: Input should be a valid date or datetime,
    invalid character in year
    [input_value='31-Dec-2025', input_type=str]
```

**10 rows, 20 errors — the same error repeated for every date field.**

### Root Cause

Pydantic's default date parser only accepts **ISO 8601** format (`YYYY-MM-DD`). Real-world bordereaux use dozens of date formats.

### Why This Matters

- Brokers will not reformat their spreadsheets
- The London market predominantly uses DD-Mon-YYYY and DD/MM/YYYY
- A tool that rejects real broker data on upload is unusable

---

## 3. Creating Test Data

### Three Test Spreadsheets

We built a Python script (`tests/fixtures/create_test_spreadsheets.py`) that generates three Excel files with realistic broker data:

| File | Schema | Purpose |
|------|--------|---------|
| `reinsurance_bordereaux_messy.xlsx` | standard_reinsurance | Messy headers + mixed date formats |
| `marine_cargo_bordereaux.xlsx` | marine_cargo | Broker-style aliases |
| `multi_sheet_bordereaux.xlsx` | Either | Two sheets for sheet selector testing |

### Realistic Messiness

The reinsurance file uses:
- Non-standard column names: `Certificate No`, `TSI (000s)`, `GWP`, `Ccy`
- Extra columns the mapper should ignore: `Insured Name`, `Broker`, `Line %`
- **Mixed date formats across rows:**

```python
"01-Jan-2025"       # DD-Mon-YYYY (rows 1-4)
"10/01/2025"        # DD/MM/YYYY  (row 5)
"2025-05-01"        # ISO 8601    (row 6)
"20 March 2025"     # DD Month YYYY (row 7)
"01-Jun-2025"       # DD-Mon-YYYY (row 8)
"April 15, 2025"    # Month DD, YYYY (row 9)
"2025/07/01"        # YYYY/MM/DD  (row 10)
```

This exercises six different date formats in a single file — exactly what happens in real broker data.

---

## 4. TDD Cycle: Failing Tests First

### Test Design

Following strict TDD, we wrote **all tests before any implementation**.

The test file (`tests/unit/test_date_coercion.py`) covers six test classes:

#### Class 1: TestDateCoercionFormats (13 tests)

```python
@pytest.mark.parametrize(
    "date_str, expected",
    [
        ("2025-01-15", datetime.date(2025, 1, 15)),       # ISO 8601
        ("01-Jan-2025", datetime.date(2025, 1, 1)),       # DD-Mon-YYYY
        ("15/01/2025", datetime.date(2025, 1, 15)),       # DD/MM/YYYY
        ("2025/01/15", datetime.date(2025, 1, 15)),       # YYYY/MM/DD
        ("15 January 2025", datetime.date(2025, 1, 15)),  # DD Month YYYY
        ("January 15, 2025", datetime.date(2025, 1, 15)), # Month DD, YYYY
        # ... 11 parametrized cases total
    ],
)
def test_accepts_common_date_format(self, date_str, expected):
    Model = build_record_model(_date_schema())
    record = Model.model_validate({"Start": date_str})
    assert record.Start == expected
```

Plus: `datetime.date` passthrough, `datetime.datetime` coercion.

#### Class 2: TestDateCoercionInvalidInput (5 tests)

```python
@pytest.mark.parametrize("bad_value", [
    "not-a-date", "2025-02-30", "", "yesterday"
])
def test_rejects_invalid_date_string(self, bad_value):
    with pytest.raises((ValidationError, ValueError), match="(?i)date|empty"):
        Model.model_validate({"Start": bad_value})
```

Plus: non-string fall-through test (integer `20250115`).

#### Class 3: TestDateCoercionLenientBehavior (2 tests)

Documents dateutil's known lenient behavior:

```python
def test_partial_month_year_produces_a_date(self):
    """'Jan 2025' is accepted — documents lenient behavior."""
    record = Model.model_validate({"Start": "Jan 2025"})
    assert record.Start.year == 2025
    assert record.Start.month == 1
```

#### Classes 4-6: Cross-field rules, optional fields, equivalence

- Cross-field date ordering works with coerced dates
- Optional date fields still accept `None`
- Dynamic model and hardcoded `RiskRecord` agree on flexible inputs

### Running the Red Phase

```
FAILED test_accepts_common_date_format[dd-mon-yyyy-jan]
  pydantic_core.ValidationError:
    Input should be a valid date or datetime,
    invalid character in year
    [input_value='01-Jan-2025']

1 failed, 1 passed
```

Confirmed: the tests fail exactly as expected.

---

## 5. Implementation: coerce_date and FlexibleDate

### The coerce_date Function

Added to `src/domain/model/record_factory.py`:

```python
from dateutil import parser as dateutil_parser

def coerce_date(value: Any) -> Any:
    """Coerce common date formats to datetime.date.

    Uses dayfirst=True since reinsurance is heavily
    London-market oriented (DD/MM/YYYY convention).
    """
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("Date string must not be empty")
        try:
            return dateutil_parser.parse(stripped, dayfirst=True).date()
        except (ValueError, OverflowError) as e:
            msg = f"Could not parse date: '{value}'"
            raise ValueError(msg) from e
    return value
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| `dayfirst=True` | London market convention: 01/02/2025 = Feb 1, not Jan 2 |
| `BeforeValidator` | Runs before Pydantic's strict parser, not after |
| Fall-through for unknown types | Let Pydantic handle type errors with its own messages |
| Empty string check | Explicit error rather than dateutil's confusing default |

### The FlexibleDate Type

```python
FlexibleDate = Annotated[datetime.date, BeforeValidator(coerce_date)]
```

Single definition in `record_factory.py`, imported by `schema.py` — no duplication.

### Wiring into the Dynamic Model Factory

```python
def _build_model(schema):
    field_definitions = {}
    for name, defn in schema.fields.items():
        if defn.type == FieldType.DATE:
            if defn.required:
                field_definitions[name] = (FlexibleDate, ...)
            else:
                field_definitions[name] = (FlexibleDate | None, None)
        else:
            # ... existing logic for other types
```

### TDD Cycle Results

| Cycle | Action | Result |
|-------|--------|--------|
| RED | 24 tests written | 23 fail (1 ISO test already passes) |
| GREEN (dynamic) | `coerce_date` + `FlexibleDate` in record factory | 21/24 pass |
| GREEN (static) | Import `FlexibleDate` in `RiskRecord` | 24/24 pass |
| GREEN (review) | Add 3 more tests from review feedback | 27/27 pass |

---

## 6. Agent-to-Agent Code Review

### How It Works

Before creating a PR, a **code-reviewer agent** inspects the diff and draft PR description. It checks:

- Architecture violations (hexagonal boundary crossings)
- Security issues
- Test coverage gaps
- PR description accuracy (every claim verified against actual code)

### First Review: BLOCK

The reviewer found **two blocking issues and three test gaps**:

#### Blocking Issue 1: Missing Runtime Dependency

```
python-dateutil is not declared as a runtime dependency.
pyproject.toml adds only types-python-dateutil to the dev group.
The runtime package is currently installed only because streamlit
pulls in pandas, which requires dateutil.

In a production Docker image built without streamlit, this will
raise ModuleNotFoundError at startup.
```

**Fix:** `uv add "python-dateutil>=2.8.2"` to runtime deps.

#### Blocking Issue 2: Duplicate Type Definition

```
FlexibleDate is defined twice — in record_factory.py and schema.py.
If the two definitions ever diverge, RiskRecord and the dynamic model
will silently disagree.
```

**Fix:** `schema.py` imports `FlexibleDate` from `record_factory.py`.

#### Test Gaps

1. No `match=` on `pytest.raises` for invalid inputs
2. No test for non-string fall-through (integer passed as date)
3. No documentation of dateutil's lenient behavior with partial dates

### Second Review: APPROVE

All issues fixed, re-submitted, reviewer approved.

### Why This Matters

Both blocking issues would have caused **production failures**:
- Issue 1: API container crash on startup (actually happened in CI)
- Issue 2: Silent data inconsistency between validation paths

The agent caught what a human reviewer might miss — especially the transitive dependency chain.

---

## 7. CI Debugging: The Boot-Test Mystery

### The Symptom

After pushing to GitHub, the boot-test CI job failed:

```
curl: (7) Failed to connect to localhost port 8000
  after 0 ms: Couldn't connect to server
Warning: Problem (retrying all errors). Will retry in 2 seconds.
  5 retries left.
...
##[error]Process completed with exit code 7.
```

The API container started (Docker confirmed "Started") but never served requests.

### The Investigation

```
gh run view 23817456423 --log-failed
```

Docker logs showed containers created and started successfully. But the API process inside never bound to port 8000 within the 15-second timeout (5s sleep + 5 retries x 2s).

### Root Cause 1: Dev Dependency Download at Startup

The Dockerfile:

```dockerfile
RUN uv sync --frozen --no-dev          # Build: production deps only
CMD ["uv", "run", "uvicorn", ...]      # Run: syncs ALL deps (including dev!)
```

`uv run` without `--no-dev` triggered a re-sync of the full environment at container startup, downloading ~120MB of dev dependencies (streamlit, mypy, ruff, locust, etc.).

**Fix:** `CMD ["uv", "run", "--no-dev", "uvicorn", ...]`

### Root Cause 2: Missing pyyaml Runtime Dependency

Once `--no-dev` was added, the API crashed with a different error:

```
File "/app/src/adapters/parsers/schema_loader.py", line 11, in <module>
    import yaml
ModuleNotFoundError: No module named 'yaml'
```

`pyyaml` was only installed as a transitive dependency of `streamlit` (a dev dep). The schema loader needed it at runtime.

**Fix:** `uv add pyyaml`

### Verification

```
$ docker compose build api && docker compose up -d
$ curl -sf http://localhost:8000/health
{"status":"ok"}
```

API starts in ~3 seconds, well within the CI timeout.

### Timeline

```
20:18:43  Container riskflow-api-1 Started (Docker level)
20:18:48  First health check attempt — connection refused
20:18:50  Retry 1 — connection refused
20:18:52  Retry 2 — connection refused
20:18:54  Retry 3 — connection refused
20:18:56  Retry 4 — connection refused
20:18:58  Retry 5 — connection refused, exit code 7
```

The API was downloading 120MB of dev packages during those 15 seconds.

---

## 8. GUI Debugging: The Schema File Mismatch

### The Symptom

The Harness Debugger tab in the Streamlit GUI showed:

```
Schema file not found at schemas/standard_reinsurance.yaml.
The GUI reads YAML files directly from the schemas/ directory.
```

### The Investigation

The API returns schema names from the `name` field inside each YAML file:

```yaml
# schemas/default.yaml
name: standard_reinsurance    # <-- API uses this name
fields:
  Policy_ID: ...
```

The GUI constructs file paths from these names:

```python
schema_path = f"schemas/{debug_schema}.yaml"
# Resolves to: schemas/standard_reinsurance.yaml
# But the file is actually: schemas/default.yaml
```

### The Fix

Renamed `schemas/default.yaml` to `schemas/standard_reinsurance.yaml` — matching the convention already used by `marine_cargo.yaml`.

Updated all references in:
- `src/entrypoint/main.py` (DEFAULT_SCHEMA_FILE constant)
- `tests/unit/test_schema_wiring.py` (4 references)
- `tests/unit/test_schema_loader.py` (4 references)

---

## 9. Summary & Lessons Learned

### What We Shipped

| Change | Files | Tests |
|--------|-------|-------|
| Flexible date parsing | 2 production files | 27 new tests |
| Dockerfile --no-dev fix | 1 file | Boot-test passes |
| pyyaml runtime dep | pyproject.toml + uv.lock | Prevents startup crash |
| Schema file rename | 4 files | 29 existing tests updated |
| Test spreadsheets | 4 fixture files | Manual testing assets |

### PR #90 Final Stats

```
15 files changed, 763 insertions(+), 41 deletions(-)
483 unit tests passing
mypy, ruff check, ruff format all clean
Boot-test: PASS
```

### Lessons Learned

#### 1. Manual Testing Finds What Unit Tests Miss

The date format issue was invisible in unit tests (which all used ISO dates) but immediately obvious when uploading a real broker spreadsheet.

#### 2. Transitive Dependencies Are Hidden Bombs

Both `python-dateutil` and `pyyaml` were installed only because `streamlit` pulled them in. The dev-only install in Docker masked runtime dependency gaps. The code-reviewer agent caught `python-dateutil`; the boot-test caught `pyyaml`.

#### 3. `uv run` Without `--no-dev` Is a Trap

`uv run` syncs the full environment by default, including dev dependencies. In a production container built with `--no-dev`, this triggers a download at startup — turning a fast boot into a 60+ second wait.

#### 4. Agent Code Review Catches Real Bugs

The code-reviewer agent found two issues that would have caused production failures. Automated review before PR creation is a force multiplier.

#### 5. Filename Conventions Matter

When filenames and internal names disagree (`default.yaml` vs `name: standard_reinsurance`), one part of the system will eventually try to use the wrong one.

---

## Appendix: Files Changed

```
schemas/default.yaml -> schemas/standard_reinsurance.yaml  (rename)
src/domain/model/record_factory.py                         (coerce_date, FlexibleDate)
src/domain/model/schema.py                                 (import FlexibleDate)
src/entrypoint/main.py                                     (DEFAULT_SCHEMA_FILE path)
Dockerfile                                                 (--no-dev in CMD)
pyproject.toml                                             (python-dateutil, pyyaml)
uv.lock                                                    (lock file update)
tests/unit/test_date_coercion.py                           (27 new tests)
tests/unit/test_schema_loader.py                           (path updates)
tests/unit/test_schema_wiring.py                           (path updates)
tests/fixtures/create_test_spreadsheets.py                 (generator script)
tests/fixtures/reinsurance_bordereaux_messy.xlsx            (test data)
tests/fixtures/marine_cargo_bordereaux.xlsx                 (test data)
tests/fixtures/multi_sheet_bordereaux.xlsx                  (test data)
.claude/rules/reinsurance.md                               (updated date rule)
```

---

## Lessons Learned (retrospective)

| Problem | Impact | How it was caught |
|---------|--------|-------------------|
| Ruff SIM105 suggested replacing deliberate `try/except/pass` with `contextlib.suppress` | Changed working, tested code to satisfy a linter rule | PR #87 reverted — led to "don't rewrite deliberate code for linters" feedback memory |
| Post-rename hook didn't exist — 8+ stale references to `schemas/default.yaml` after rename | Stale file paths in docs, rules, and comments | Built the post-rename hook (PR #92) as a direct result |
| `pyyaml` was only in dev deps but imported at runtime | Boot test worked in dev mode but would fail in production Docker image | Runtime dependency check hook (PR #91) |

**Key insight:** Linter suggestions are not always improvements. Deliberate patterns (try/except/pass for graceful degradation) should be preserved — ignore the rule, don't change the code.
