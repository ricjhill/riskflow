# OpenAPI Spec Export, Typed Models & API Versioning

**RiskFlow Engineering Session — 4 April 2026**

---

## Agenda

| # | Section | Time |
|---|---------|------|
| 1 | What We Built | 3 min |
| 2 | The Problem: Three Sources of Truth | 5 min |
| 3 | Typed Response Models | 5 min |
| 4 | OpenAPI Spec Export & CI Enforcement | 5 min |
| 5 | Breaking Change Detection | 5 min |
| 6 | Automated GitHub Releases | 5 min |
| 7 | Documentation & Harness Updates | 3 min |
| 8 | Design Review: Is It Over-Engineered? | 3 min |
| 9 | By the Numbers | 3 min |
| 10 | What's Next | 2 min |

---

## 1. What We Built (3 min)

Five PRs, one theme: **make the API contract a first-class artifact**.

| PR | Title | Theme |
|----|-------|-------|
| #109 | OpenAPI export + typed response models | Contract |
| #110 | Committed openapi.json with CI staleness check | Enforcement |
| #111 | API versioning with breaking change detection | Versioning |
| #112 | Diataxis docs: OpenAPI spec + versioning reference | Docs |
| #113 | Advisory docs-reminder hook for API changes | Harness |

Starting point: every route returned `dict[str, object]`, the OpenAPI spec was full of generic `additionalProperties: true` objects, there were no releases, no version numbers, and the API contract existed in three places that drifted independently.

Ending point: 30 typed component schemas, a committed spec with CI enforcement, automated semantic versioning, and GitHub releases triggered by API surface changes.

---

## 2. The Problem: Three Sources of Truth (5 min)

Before this session, the API contract lived in three places:

| Source | What it was | Problem |
|--------|------------|---------|
| FastAPI route code | The actual implementation | Returned `dict[str, object]` — OpenAPI spec was useless |
| `docs/reference/api.md` | Hand-written Markdown | Could drift from code silently |
| `riskflow-ui/src/types/api.ts` | Hand-written TypeScript | Could drift from both code and docs |

**Key finding from the audit:** POST /corrections had three different error formats across the three sources. Code returned plain strings, docs said "plain text", TypeScript expected structured `ErrorDetail`.

**Decision:** Make the code the single source of truth. If the code expresses the contract fully (typed return types), the OpenAPI spec becomes accurate automatically, and hand-written types become unnecessary.

---

## 3. Typed Response Models (5 min)

### The change

Every route returned `dict[str, object]`. FastAPI generated `additionalProperties: true` for everything.

**Before:**
```python
@router.post("/upload")
async def upload_file(...) -> dict[str, object]:
    return result.model_dump()
```

**After:**
```python
@router.post("/upload")
async def upload_file(...) -> ProcessingResult:
    return result
```

### What was added

11 new Pydantic models in `routes.py`:

| Category | Models |
|----------|--------|
| Response | SchemaListResponse, SchemaCreatedResponse, SheetListResponse, CorrectionStoredResponse, AsyncJobResponse, JobStatusResponse, HealthResponse, ErrorDetail |
| Request | UpdateMappingsRequest, ExtendTargetFieldsRequest |

Domain models used directly as return types: `ProcessingResult`, `MappingSession`, `TargetSchema`.

### Why not just add type hints?

FastAPI only generates component schemas from Pydantic models in return type annotations. Returning `result.model_dump()` as `dict` loses all type information. Returning `result` directly as `ProcessingResult` keeps the same JSON but tells FastAPI to generate the schema.

### Side benefit

The `UpdateMappingsRequest` and `ExtendTargetFieldsRequest` models replaced 20+ lines of manual `isinstance` validation in the route handlers. Pydantic validates at the framework boundary now.

---

## 4. OpenAPI Spec Export & CI Enforcement (5 min)

### The export script

`tools/export_openapi.py` — 34 lines. Runs the app with null adapters (clears `REDIS_URL`), calls `app.openapi()`, writes JSON.

```bash
uv run python -m tools.export_openapi
# Exported 13 paths (16 operations) to openapi.json
```

**Design decision:** We initially gitignored the spec, but committing it is better because:
- You can `git diff openapi.json` between releases to see what changed
- riskflow-ui CI can fetch it without running the backend
- Tools like `oasdiff` can detect breaking changes in PRs

### Two enforcement mechanisms

1. **Unit test** (`test_committed_spec_matches_live_app`): Regenerates in-process, asserts equality against committed file. Catches drift in pre-commit hooks.

2. **CI step** (in `quality` job): Regenerates to temp file, runs `diff`. Fails the build if stale.

Both are needed — the unit test catches it fast locally, CI catches it if someone skips hooks.

---

## 5. Breaking Change Detection (5 min)

### The tool

`tools/check_api_changes.py` — pure Python, no external deps. Compares two OpenAPI specs structurally.

### Classification rules

| Breaking (major bump) | Non-breaking (minor bump) |
|----------------------|--------------------------|
| Removed path | Added path |
| Removed HTTP method | Added HTTP method |
| Removed required parameter | Added optional parameter |
| Required ↔ optional change | Removed optional parameter |
| Removed response status code | Added response status code |

### What it doesn't detect (acknowledged limitation)

- Request/response body schema changes (added/removed properties)
- Parameter type changes (string → integer)

These would require deep JSON Schema diffing — more complexity than the current need warrants.

### Test coverage

18 tests covering every detection path, including mixed scenarios (breaking + non-breaking = breaking wins).

---

## 6. Automated GitHub Releases (5 min)

### The workflow

`.github/workflows/release.yml` — triggers after CI passes on main.

```
CI passes on main
    ↓
Fetch openapi.json from last release tag
    ↓
Compare against current committed spec
    ↓
BREAKING → bump major, commit, release
NON_BREAKING → bump minor, commit, release  
NONE → do nothing
```

### Version flow

`pyproject.toml` is the canonical source. FastAPI reads it via `_get_version()`. The export script picks it up. The release workflow bumps it and re-exports.

### First run

No tags exist yet → creates initial `v0.1.0` release with `openapi.json` as a downloadable asset.

---

## 7. Documentation & Harness Updates (3 min)

### New reference docs

- `docs/reference/openapi.md` — how to access the spec, 30 schema inventory, codegen example, CI enforcement
- `docs/reference/versioning.md` — semver scheme, release workflow, breaking change rules, manual bump instructions

### Advisory hook

`.claude/hooks/docs-reminder.sh` — when committing API-facing files without docs/, prints a non-blocking reminder. Fills the gap doc-gardener misses: new features with zero documentation.

### Cleanup scan

Full cleanup scan found 0 issues across all 6 categories (dead code, architecture, tests, deps, docs, patterns).

---

## 8. Design Review: Is It Over-Engineered? (3 min)

We asked this explicitly at the end of the session.

**Current:** 4 files, ~480 lines, 37 tests for the versioning pipeline.

**Could be simpler:** Merge `bump_version.py` into the release workflow as a single script. Drop from 4 files to 3, workflow from 152 lines to ~30.

**Decision: Leave it.** The disadvantages of simplifying (harder to debug in CI, lose standalone CLI, less self-documenting YAML) outweigh the benefit (fewer files) for now. The 37 tests protect it either way. Revisit if it becomes a maintenance burden.

---

## 9. By the Numbers (3 min)

| Metric | Before | After |
|--------|--------|-------|
| OpenAPI component schemas | ~6 (generic Body_*) | 30 (fully typed) |
| Routes with typed returns | 0 | 16 |
| API version | none | 0.1.0 (semver) |
| Breaking change detection | none | automated |
| GitHub releases | 0 | automated pipeline |
| Unit tests | 706 | 743 (+37) |
| Total tests collected | 801 | 838 |
| New tools | 0 | 3 (export, check, bump) |
| New docs | 0 | 2 reference pages |
| PRs merged | 0 | 5 |

---

## 10. What's Next (2 min)

### Immediate (riskflow-ui session)

Step 2 of the OpenAPI sync plan:
1. Install `openapi-typescript` in riskflow-ui
2. Generate TypeScript types from `../riskflow/openapi.json`
3. Replace hand-written `src/types/api.ts`
4. Add CI staleness check

### Future

- Auto-generate `docs/reference/api.md` from the spec (eliminate the second source of truth)
- Add body schema diffing to `check_api_changes.py` (detect added/removed response properties)
- Consider `oasdiff` for PR comments showing exactly what changed
- Create initial `v0.1.0` release tag (happens automatically on first CI pass after merge)
