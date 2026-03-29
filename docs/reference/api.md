# API Reference

Base URL: `http://localhost:8000`

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
