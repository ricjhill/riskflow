# OpenAPI Specification

RiskFlow publishes a machine-readable OpenAPI 3.1 spec that describes every endpoint, request body, response shape, and error format. The spec is generated from the FastAPI route definitions and Pydantic models — it is the single source of truth for the API contract.

## Accessing the spec

### Live (running server)

When the API is running, the spec is available at:

- **JSON:** `GET /openapi.json`
- **Swagger UI:** `GET /docs`
- **ReDoc:** `GET /redoc`

### Committed file

The spec is committed to the repository at [`openapi.json`](../../openapi.json) in the project root. This file is regenerated from the app and checked for staleness in CI — if a developer changes a route or Pydantic model but forgets to re-export, the build fails.

### Regenerating

```bash
uv run python -m tools.export_openapi
```

This runs the app with null adapters (no Redis or Groq needed) and writes `openapi.json` to the project root.

## What the spec contains

The spec includes **30 component schemas** covering every request body, response model, and domain type:

| Category | Schemas |
|----------|---------|
| **Domain models** | ProcessingResult, MappingResult, ColumnMapping, ConfidenceReport, RowError, MappingSession, TargetSchema, FieldDefinition, DateOrderingRule, SLMHint, SessionStatus, FieldType |
| **Response models** | SchemaListResponse, SchemaCreatedResponse, SheetListResponse, CorrectionStoredResponse, AsyncJobResponse, JobStatusResponse, HealthResponse, ErrorDetail |
| **Request models** | CorrectionRequest, CorrectionItem, UpdateMappingsRequest, ExtendTargetFieldsRequest |
| **Auto-generated** | Body_upload_file_*, HTTPValidationError, ValidationError |

## Version

The spec's `info.version` field is read from `pyproject.toml` at export time. This version is bumped automatically by the release workflow when API changes are detected (see [Versioning](versioning.md)).

## Using the spec for code generation

The spec is designed for client code generation. Example with `openapi-typescript`:

```bash
npx openapi-typescript openapi.json -o src/types/api.generated.ts
```

This produces typed interfaces for every request and response, eliminating hand-written type definitions that can drift from the backend.

## CI enforcement

Two mechanisms prevent the committed spec from drifting:

1. **Unit test** (`test_committed_spec_matches_live_app`): Regenerates the spec in-process and asserts it matches the committed file. Runs in the pre-commit hook.
2. **CI step** (OpenAPI spec staleness check): Regenerates to a temp file and diffs against the committed spec. Fails the build on mismatch.
