# Features Overview

This page explains what RiskFlow does, who it's for, and how each feature delivers value. It's written for product owners, testers, and anyone evaluating the tool.

## The Problem

Reinsurance companies receive bordereaux spreadsheets from cedents (insurance companies that cede risk). Every cedent formats their spreadsheets differently:

- One calls it "GWP", another calls it "Gross Written Premium"
- Date formats vary: "15/01/2024", "Jan-15-2024", "2024-01-15"
- Column names are abbreviated, misspelled, or use internal jargon
- Some spreadsheets have multiple sheets with different data

Today, underwriters manually map these columns to a standard format. This is slow (hours per file), error-prone, and doesn't scale.

## What RiskFlow Does

RiskFlow automates the mapping step. Upload a bordereaux spreadsheet, and RiskFlow:

1. **Identifies** what each column represents using an AI model (Groq/Llama 3.3)
2. **Maps** messy column names to standard field names (e.g., "GWP" → "Gross_Premium")
3. **Validates** every row against the schema (correct currencies, non-negative amounts, valid dates)
4. **Returns** clean, validated data with confidence scores

## Feature List

### 1. Automatic Header Mapping

**What it does:** Upload a spreadsheet → get column mappings with confidence scores.

**Business value:** Eliminates manual column mapping. A file that took an underwriter 30 minutes to interpret is processed in under 2 seconds.

**How it works:** The AI reads the column headers and sample data rows, then determines which target field each column most likely represents. Each mapping includes a confidence score (0 to 1) so users know which mappings to trust and which to review.

**Example:**
| Source Header | Target Field | Confidence |
|---------------|-------------|------------|
| Policy No. | Policy_ID | 0.95 |
| GWP | Gross_Premium | 0.95 |
| Ccy | Currency | 0.95 |
| Broker Notes | *(unmapped)* | — |

### 2. Row-Level Validation

**What it does:** After mapping, every row is validated against the target schema.

**Business value:** Catches data quality issues immediately — before they enter downstream systems. Invalid rows are flagged with specific error messages, not silently accepted.

**What it checks:**
- Required fields are present and non-empty
- Currencies are valid ISO 4217 codes (USD, GBP, EUR, JPY in the default schema)
- Financial amounts (Sum_Insured, Gross_Premium) are non-negative
- Dates are valid and Expiry_Date is not before Inception_Date
- Policy_ID is not blank

**Example output:**
- 5 rows uploaded → 4 valid records + 1 error: "Row 3: Currency must be one of [USD, GBP, EUR, JPY], got 'DOLLARS'"

### 3. Confidence Scores

**What it does:** Every mapping includes a confidence score. A summary report shows the minimum, average, and any fields below the review threshold.

**Business value:** Users don't need to check every mapping — only the low-confidence ones. High confidence (>0.9) means the AI is very certain. Low confidence (<0.6) means a human should verify.

**What triggers low confidence:**
- Ambiguous headers (e.g., "Amount" could be Sum_Insured or Gross_Premium)
- Headers the AI hasn't seen before
- Multiple columns that could map to the same field

### 4. Multi-Sheet Excel Support

**What it does:** For Excel files with multiple sheets, users can specify which sheet to process.

**Business value:** Many bordereaux arrive as multi-sheet workbooks (e.g., "Policies", "Claims", "Summary"). Users can target the right sheet without splitting the file.

**How to use it:**
1. Upload the file to `POST /sheets` to see available sheet names
2. Upload again to `POST /upload?sheet_name=Policies` to process a specific sheet

### 5. Correction Feedback Loop

**What it does:** When the AI maps a header incorrectly, users can submit a correction. Future uploads from the same cedent automatically apply the correction with 100% confidence.

**Business value:** The system learns from mistakes. After correcting "TSI" → "Sum_Insured" for cedent ABC once, every future file from cedent ABC maps "TSI" correctly without calling the AI.

**How it works:**
1. Upload file from cedent ABC → AI maps "TSI" to "Gross_Premium" (wrong)
2. Submit correction: `POST /corrections` with cedent_id="ABC", source_header="TSI", target_field="Sum_Insured"
3. Next upload with `?cedent_id=ABC` → "TSI" maps to "Sum_Insured" with confidence 1.0, AI skipped for that header

**What this means for accuracy:** Over time, frequently-used cedents build up a correction cache. The more corrections, the fewer AI calls, the more accurate the results.

### 6. Async Processing

**What it does:** For large files, upload without waiting. Get a job ID, poll for status, retrieve results when ready.

**Business value:** Large bordereaux files (thousands of rows) don't time out the HTTP connection. Users can submit and come back later.

**How to use it:**
1. `POST /upload/async` → returns `{"job_id": "abc-123"}`
2. `GET /jobs/abc-123` → returns status (PENDING, PROCESSING, COMPLETE, FAILED)
3. When COMPLETE, the response includes the full mapping and validation results

### 7. Configurable Target Schema

**What it does:** The 6-field reinsurance schema (Policy_ID, Inception_Date, etc.) is the default, but users can define custom schemas for different bordereaux types.

**Business value:** Different lines of business have different data requirements. A marine cargo bordereaux needs Vessel_Name and Voyage_Date, not the standard reinsurance fields. Custom schemas let RiskFlow handle any bordereaux format.

**How it works:**
- Schemas are defined as YAML files in the `schemas/` directory
- Each schema specifies field names, types, constraints, and AI hints
- Users select a schema per upload: `POST /upload?schema=marine_cargo`
- `GET /schemas` lists all available schemas

### 8. Caching

**What it does:** When the same set of headers is uploaded again, the mapping result is returned from cache instead of calling the AI.

**Business value:** Repeated uploads of similar files (monthly bordereaux from the same cedent) are near-instant. First upload: ~1-2 seconds (AI call). Second upload: ~1 millisecond (cache hit).

**How it works:** The cache key is based on the sorted headers + the schema fingerprint. Different schemas produce different cache keys, so switching schemas doesn't return stale results.

### 9. Interactive Session-Based Mapping

**What it does:** The Flow Mapper (GUI Tab 4) provides a multi-step interactive workflow: upload a file, review AI-suggested mappings, edit them via dropdowns, add custom target fields, and finalise. The result can be saved as a new reusable schema.

**Business value:** Users can correct AI mistakes before validation, add fields not in the original schema (e.g., "Broker_Notes"), and build custom schemas visually — no YAML editing or API knowledge required.

**How it works:** Sessions are persisted in Redis with a 1-hour TTL. The temp file from upload is kept alive so finalise can re-read it. Custom fields are added via PATCH /sessions/{id}/target-fields. New schemas are saved via POST /schemas and appear in the dropdown for future sessions.

### 10. Runtime Schema Management

**What it does:** Schemas can be created, viewed, and deleted at runtime via the API (POST/GET/DELETE /schemas). They persist in Redis alongside the YAML-loaded schemas.

**Business value:** New cedent schemas can be created by data teams without restarting the service or editing YAML files. Built-in schemas (from YAML) are protected from deletion.

## Acceptance Testing Checklist

For testers validating RiskFlow, here are the key scenarios to verify:

| # | Scenario | Expected Result |
|---|----------|----------------|
| 1 | Upload sample_bordereaux.csv | All 6 headers mapped, 5 rows valid, 0 errors |
| 2 | Upload CSV with invalid currency ("DOLLARS") | Row with bad currency in `invalid_records`, clear error message |
| 3 | Upload CSV with negative Sum_Insured | Row rejected with "must be non-negative" error |
| 4 | Upload CSV with Expiry_Date before Inception_Date | Row rejected with "must not be before" error |
| 5 | Upload CSV with empty Policy_ID | Row rejected with "must not be empty" error |
| 6 | Upload same file twice | Second upload returns faster (cache hit logged) |
| 7 | Submit correction, then re-upload with cedent_id | Corrected header maps with confidence 1.0 |
| 8 | Upload multi-sheet Excel with ?sheet_name | Only the named sheet is processed |
| 9 | Upload non-spreadsheet file (e.g., .pdf) | 400 error: "Unsupported file type" |
| 10 | Upload file larger than 10MB | 400 error: "File size exceeds limit" |
| 11 | Use ?schema=nonexistent | 404 error: "Schema not found" |
| 12 | GET /schemas | Returns list of available schema names |
| 13 | POST /upload/async then GET /jobs/{id} | Job progresses from PENDING → PROCESSING → COMPLETE |
| 14 | POST /sessions → GET → PUT mappings → POST finalise | Interactive session workflow completes |
| 15 | PATCH /sessions/{id}/target-fields with custom field | Custom field appears in target_fields |
| 16 | POST /schemas with new schema body | Schema created, appears in GET /schemas |
| 17 | DELETE /schemas/{builtin_name} | 403: built-in schemas are protected |
| 18 | Flow Mapper: add field → map → finalise → save schema | Full interactive schema creation |

## Architecture (Non-Technical Summary)

RiskFlow is built as a REST API. You send it files, it sends back JSON.

```
Your spreadsheet
    ↓
RiskFlow API (upload)
    ↓
Parse headers from the file
    ↓
Check cache → if seen before, return cached result
    ↓
Check corrections → if cedent has corrections, apply them
    ↓
AI maps remaining headers → returns field names + confidence
    ↓
Validate every row against the schema
    ↓
Return: mapped fields, valid records, invalid records, errors
```

The AI (Groq/Llama 3.3) is only called when the headers haven't been seen before and there are no corrections. For repeat uploads, the response is near-instant from cache.
