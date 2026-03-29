# How Mapping Works

This page explains the full pipeline from file upload to validated output.

## The Pipeline

```
1. Upload        → receive file, validate type and size
2. Parse         → extract headers and sample rows using Polars
3. Cache check   → hash headers + schema fingerprint, check Redis
4. Corrections   → if cedent_id provided, apply known-good mappings
5. AI mapping    → send remaining headers to Groq/Llama 3.3
6. Merge         → combine corrections + AI results
7. Validate      → read full file, rename columns, validate each row
8. Return        → valid records, invalid records, errors, confidence
```

## Step by step

### 1. File upload

The user uploads a CSV or Excel file via `POST /upload`. The file is saved to a temporary location. File type and size are validated (max 10MB, only .csv/.xlsx/.xls).

### 2. Header extraction

Polars reads the first few rows to extract column headers and sample data. The sample rows are important — they help the AI disambiguate ambiguous headers. For example, a column called "Amount" could be Sum_Insured or Gross_Premium, but if the sample values are 5,000,000 vs 125,000, the AI can use the magnitude to decide.

### 3. Cache check

The headers are sorted, lowercased, and hashed with SHA-256, combined with the schema's fingerprint (a blake2b hash of the schema definition). If this exact combination of headers + schema has been seen before, the cached mapping is returned immediately (~1ms instead of ~1-2 seconds).

### 4. Correction lookup

If the user provided a `cedent_id`, RiskFlow checks the Redis correction cache for known-good mappings from this cedent. Corrections are stored as `(cedent_id, source_header) → target_field` pairs. Corrected headers are mapped with confidence 1.0 and removed from the list sent to the AI.

### 5. AI mapping

The remaining unmapped headers (those not in cache and not corrected) are sent to Groq's Llama 3.3 model. The prompt includes:
- The target schema's field names
- SLM hints (common aliases like "GWP" → Gross_Premium)
- The sample data rows
- Instructions to return JSON with mappings and confidence scores

The AI returns a JSON response with one mapping per header it could identify, plus a list of unmapped headers.

### 6. Merge

Correction mappings (confidence 1.0) and AI mappings are combined into a single MappingResult. If the AI maps a header to a target that's already covered by a correction, the AI mapping is discarded (corrections take priority).

### 7. Row validation

The full file is read by Polars. Columns are renamed according to the mapping (e.g., "GWP" → "Gross_Premium"). Each row is validated against the target schema's dynamic pydantic model:
- Type checking (string, date, float)
- Constraint checking (non-negative, not-empty, allowed values)
- Cross-field rules (date ordering)

Rows that pass go to `valid_records`. Rows that fail go to `invalid_records` with an error message in `errors`.

### 8. Response

The response includes everything: the mapping with confidence scores, a confidence report, valid records, invalid records, and row-level errors.

## Why this order matters

- **Cache before AI:** Avoids redundant API calls for repeated uploads
- **Corrections before AI:** Human-verified mappings override AI guesses
- **Validation after mapping:** Can only validate data once we know which column is which
- **Schema fingerprint in cache key:** Prevents stale mappings when switching schemas
