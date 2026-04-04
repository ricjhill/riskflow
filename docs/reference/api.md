# API Reference

Base URL: `http://localhost:8000`

The API is semantically versioned. The current version is in [`openapi.json`](../../openapi.json). For the machine-readable spec, see [OpenAPI Specification](openapi.md). For the versioning strategy, see [Versioning](versioning.md).

## Endpoints

### GET /health

Health check.

**Response:** `200 OK`

```json
{"status": "ok"}
```

---

### GET /schemas

List all available target schemas.

**Response:** `200 OK`

```json
{"schemas": ["standard_reinsurance", "marine_cargo"]}
```

---

### POST /upload

Upload a spreadsheet and map its headers to the target schema synchronously.

**Content-Type:** `multipart/form-data`

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| file | body | File | Yes | CSV, XLSX, or XLS file (max 10MB) |
| sheet_name | query | string | No | Sheet to process (Excel only, default: first sheet) |
| cedent_id | query | string | No | Cedent ID for correction cache lookup |
| schema | query | string | No | Schema name (default: standard_reinsurance) |

**Response:** `200 OK`

```json
{
  "mapping": {
    "mappings": [
      {
        "source_header": "Policy No.",
        "target_field": "Policy_ID",
        "confidence": 0.95
      }
    ],
    "unmapped_headers": ["Broker Notes"]
  },
  "confidence_report": {
    "min_confidence": 0.95,
    "avg_confidence": 0.95,
    "low_confidence_fields": [],
    "missing_fields": []
  },
  "valid_records": [
    {
      "Policy_ID": "POL-2024-001",
      "Inception_Date": "2024-01-15",
      "Expiry_Date": "2025-01-15",
      "Sum_Insured": 5000000.0,
      "Gross_Premium": 125000.0,
      "Currency": "USD"
    }
  ],
  "invalid_records": [],
  "errors": []
}
```

**Errors:**

| Status | Error Code | Cause |
|--------|-----------|-------|
| 400 | INVALID_DATA | Unparseable file content |
| 400 | INVALID_SHEET | Named sheet doesn't exist |
| 404 | SCHEMA_NOT_FOUND | ?schema= value not in registry |
| 422 | LOW_CONFIDENCE | Any mapping below confidence threshold |
| 422 | SCHEMA_VALIDATION | Row fails schema validation |
| 422 | INVALID_CORRECTION | Correction references unknown field |
| 503 | SLM_UNAVAILABLE | Groq API unreachable or returned error |
| 500 | INTERNAL_ERROR | Unexpected server error |

---

### POST /upload/async

Upload a file for asynchronous processing. Returns immediately with a job ID.

**Content-Type:** `multipart/form-data`

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| file | body | File | Yes | CSV, XLSX, or XLS file (max 10MB) |
| sheet_name | query | string | No | Sheet to process (Excel only) |

**Response:** `202 Accepted`

```json
{"job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"}
```

---

### GET /jobs/{job_id}

Get the status and result of an async job.

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| job_id | path | string | Yes | Job ID from POST /upload/async |

**Response:** `200 OK`

```json
{
  "job_id": "a1b2c3d4-...",
  "status": "COMPLETE",
  "result": { ... },
  "error": null
}
```

**Status values:** PENDING, PROCESSING, COMPLETE, FAILED

**Errors:** `404 Not Found` if job_id doesn't exist.

---

### POST /sheets

Upload a file and return its sheet names. Useful for previewing Excel workbooks before upload.

**Content-Type:** `multipart/form-data`

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| file | body | File | Yes | Excel file (CSV returns empty list) |

**Response:** `200 OK`

```json
{"sheets": ["Policies", "Claims", "Summary"]}
```

---

### POST /corrections

Submit human-verified mapping corrections for a cedent.

**Content-Type:** `application/json`

**Request body:**

```json
{
  "cedent_id": "ACME-RE",
  "corrections": [
    {"source_header": "TSI", "target_field": "Sum_Insured"},
    {"source_header": "Amt", "target_field": "Gross_Premium"}
  ]
}
```

**Response:** `201 Created`

```json
{"stored": 2}
```

**Errors:**

| Status | Error Code | Cause |
|--------|-----------|-------|
| 400 | *(plain text)* | Empty cedent_id or empty corrections list |
| 422 | INVALID_CORRECTION | target_field not in the active schema |

---

### GET /schemas/{name}

Return the full definition of a target schema.

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| name | path | string | Yes | Schema name |

**Response:** `200 OK`

```json
{
  "name": "standard_reinsurance",
  "fields": {
    "Policy_ID": {"type": "string", "not_empty": true},
    "Inception_Date": {"type": "date"},
    "Sum_Insured": {"type": "float", "non_negative": true}
  },
  "cross_field_rules": [{"earlier": "Inception_Date", "later": "Expiry_Date"}],
  "slm_hints": [{"source_alias": "GWP", "target": "Gross_Premium"}]
}
```

**Errors:** `404 SCHEMA_NOT_FOUND`

---

### POST /schemas

Create a runtime schema from a JSON definition. Persists to Redis.

**Content-Type:** `application/json`

**Request body:** Same format as GET /schemas/{name} response.

**Response:** `201 Created`

```json
{"name": "custom_marine", "fingerprint": "a1b2c3..."}
```

**Errors:**

| Status | Error Code | Cause |
|--------|-----------|-------|
| 409 | SCHEMA_ALREADY_EXISTS | Schema name already in use |
| 422 | INVALID_SCHEMA | Invalid schema definition |

---

### DELETE /schemas/{name}

Delete a runtime schema. Built-in schemas (loaded from YAML) cannot be deleted.

**Response:** `204 No Content`

**Errors:**

| Status | Error Code | Cause |
|--------|-----------|-------|
| 403 | PROTECTED_SCHEMA | Cannot delete built-in schema |
| 404 | SCHEMA_NOT_FOUND | Schema doesn't exist |

---

### POST /sessions

Upload a file and create an interactive mapping session. Returns the session with SLM-suggested mappings and a preview of the data.

**Content-Type:** `multipart/form-data`

**Parameters:**

| Name | In | Type | Required | Description |
|------|----|------|----------|-------------|
| file | body | File | Yes | CSV, XLSX, or XLS file (max 10MB) |
| sheet_name | query | string | No | Sheet to process (Excel only) |
| schema | query | string | No | Schema name (default: standard_reinsurance) |

**Response:** `201 Created`

```json
{
  "id": "a1b2c3d4-...",
  "status": "created",
  "schema_name": "standard_reinsurance",
  "file_path": "/tmp/tmpXXXXXX.csv",
  "sheet_name": null,
  "source_headers": ["Policy No.", "Start Date", "GWP"],
  "target_fields": ["Currency", "Expiry_Date", "Gross_Premium", "Inception_Date", "Policy_ID", "Sum_Insured"],
  "mappings": [
    {"source_header": "Policy No.", "target_field": "Policy_ID", "confidence": 0.95}
  ],
  "unmapped_headers": ["Broker Notes"],
  "preview_rows": [{"Policy No.": "POL-001", "Start Date": "2024-01-15", "GWP": 125000}],
  "result": null
}
```

**Errors:**

| Status | Error Code | Cause |
|--------|-----------|-------|
| 400 | INVALID_DATA | Empty file, unparseable content |
| 404 | SCHEMA_NOT_FOUND | ?schema= value not in registry |
| 503 | SLM_UNAVAILABLE | Groq API unreachable |

---

### GET /sessions/{session_id}

Return the current state of a mapping session.

**Response:** `200 OK` — same shape as POST /sessions response.

**Errors:** `404` if session not found.

---

### PUT /sessions/{session_id}/mappings

Replace the session's mappings with user-edited values.

**Content-Type:** `application/json`

**Request body:**

```json
{
  "mappings": [
    {"source_header": "Policy No.", "target_field": "Policy_ID", "confidence": 1.0},
    {"source_header": "GWP", "target_field": "Gross_Premium", "confidence": 1.0}
  ],
  "unmapped_headers": ["Broker Notes"]
}
```

**Response:** `200 OK` — updated session dict.

**Errors:**

| Status | Error Code | Cause |
|--------|-----------|-------|
| 404 | | Session not found |
| 422 | INVALID_MAPPING | Invalid target field, duplicate targets |

---

### PATCH /sessions/{session_id}/target-fields

Add custom target fields to a session. Enables mapping source headers to fields not in the original schema.

**Content-Type:** `application/json`

**Request body:**

```json
{"fields": ["Renewal_Date", "Broker_Notes"]}
```

**Response:** `200 OK` — updated session dict with new fields in `target_fields`.

**Errors:**

| Status | Error Code | Cause |
|--------|-----------|-------|
| 404 | | Session not found |
| 422 | INVALID_FIELDS | Empty list, empty names, non-string values, finalised session |

---

### POST /sessions/{session_id}/finalise

Validate all rows using the session's current mapping. Transitions session to FINALISED.

**Response:** `200 OK` — session dict with `status: "finalised"` and `result` containing the ProcessingResult (same shape as POST /upload response).

**Errors:**

| Status | Error Code | Cause |
|--------|-----------|-------|
| 404 | | Session not found |
| 409 | | Session already finalised |
| 500 | INTERNAL_ERROR | Validation failed (e.g., temp file deleted) |

---

### DELETE /sessions/{session_id}

Delete a session, clean up the temp file and Redis entry.

**Response:** `204 No Content`

**Errors:** `404` if session not found.

---

## Error response format

All errors (except 404) return a structured body:

```json
{
  "detail": {
    "error_code": "LOW_CONFIDENCE",
    "message": "Mapping 'Amount' -> 'Sum_Insured' has confidence 0.45, below threshold 0.6",
    "suggestion": "Review the unmapped headers and consider providing more representative sample data."
  }
}
```

## File constraints

| Constraint | Value |
|-----------|-------|
| Max file size | 10 MB |
| Allowed extensions | .csv, .xlsx, .xls |
| Schema name format | Alphanumeric, hyphens, underscores only |
