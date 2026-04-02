# Error Codes Reference

All API errors return a structured JSON body with `error_code`, `message`, and `suggestion`.

## Error response format

```json
{
  "detail": {
    "error_code": "ERROR_CODE",
    "message": "What went wrong",
    "suggestion": "What to do about it"
  }
}
```

## HTTP error codes

### 400 Bad Request

| Error Code | Trigger | Example |
|-----------|---------|---------|
| INVALID_DATA | Source file content is unparseable | Corrupted CSV, binary file with .csv extension |
| INVALID_SHEET | Named sheet doesn't exist in the workbook | `?sheet_name=NoSuchSheet` on an Excel file |
| INVALID_SCHEMA_NAME | Schema name contains invalid characters | `?schema=../../etc/passwd` — path traversal attempt |
| *(plain text)* | Unsupported file type | Uploading a .pdf file |
| *(plain text)* | File too large | File exceeds 10MB limit |
| *(plain text)* | Empty cedent_id or corrections list | POST /corrections with blank cedent_id |

### 403 Forbidden

| Error Code | Trigger | Example |
|-----------|---------|---------|
| PROTECTED_SCHEMA | Cannot delete a built-in schema | DELETE /schemas/standard_reinsurance |

### 404 Not Found

| Error Code | Trigger | Example |
|-----------|---------|---------|
| SCHEMA_NOT_FOUND | Schema name not in registry | `?schema=nonexistent` |
| *(plain text)* | Job ID doesn't exist | GET /jobs/unknown-id |
| *(plain text)* | Session ID doesn't exist | GET /sessions/unknown-id |

### 409 Conflict

| Error Code | Trigger | Example |
|-----------|---------|---------|
| SCHEMA_ALREADY_EXISTS | Schema name already in use | POST /schemas with existing name |
| *(plain text)* | Session already finalised | POST /sessions/{id}/finalise twice |

### 422 Unprocessable Entity

| Error Code | Trigger | Example |
|-----------|---------|---------|
| LOW_CONFIDENCE | Any mapping below confidence threshold (0.6) | AI mapped "Amount" to "Sum_Insured" with 0.45 confidence |
| SCHEMA_VALIDATION | A row fails schema validation | Row has Currency="DOLLARS" (not in allowed values) |
| INVALID_CORRECTION | Correction references a field not in the schema | Correction with target_field="NonexistentField" |
| INVALID_SCHEMA | Schema definition is malformed | POST /schemas with missing fields |
| INVALID_MAPPING | Target field not in schema or duplicate targets | PUT /sessions/{id}/mappings with bad target |
| INVALID_FIELDS | Empty/non-string field names or finalised session | PATCH /sessions/{id}/target-fields with empty list |

### 503 Service Unavailable

| Error Code | Trigger | Example |
|-----------|---------|---------|
| SLM_UNAVAILABLE | Groq API is unreachable, timed out, or returned an error | Network error, API key invalid, model deprecated |

### 500 Internal Server Error

| Error Code | Trigger | Example |
|-----------|---------|---------|
| INTERNAL_ERROR | Unexpected error in the application | Unhandled exception (details not leaked to client) |

## Domain errors (internal)

These are the Python exceptions that map to the HTTP error codes above:

| Exception | HTTP | Error Code |
|-----------|------|-----------|
| `InvalidCedentDataError` | 400 | INVALID_DATA |
| `ValueError` (sheet not found) | 400 | INVALID_SHEET |
| `MappingConfidenceLowError` | 422 | LOW_CONFIDENCE |
| `SchemaValidationError` | 422 | SCHEMA_VALIDATION |
| `InvalidCorrectionError` | 422 | INVALID_CORRECTION |
| `SLMUnavailableError` | 503 | SLM_UNAVAILABLE |
| `InvalidSchemaError` | N/A | Fatal at startup (app won't boot) |
| `RiskFlowError` (base) | 500 | INTERNAL_ERROR |

## Startup errors

These errors prevent the application from starting:

| Error | Cause | Fix |
|-------|-------|-----|
| `InvalidSchemaError: Schema file not found` | SCHEMA_PATH points to a missing file | Check the path in .env |
| `InvalidSchemaError: Failed to parse YAML` | Schema YAML is malformed | Fix the YAML syntax |
| `InvalidSchemaError: non_negative constraint only applies to FLOAT` | Constraint applied to wrong field type | Check field types in schema YAML |
| `InvalidSchemaError: Cross-field rule references non-DATE field` | Date ordering rule on a non-date field | Both fields must be type: date |
| `InvalidSchemaError: duplicate source aliases` | Two SLM hints have the same source_alias | Make aliases unique |
