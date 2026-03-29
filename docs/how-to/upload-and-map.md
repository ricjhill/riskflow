# How to: Upload and Map a Spreadsheet

## Goal

Map a bordereaux spreadsheet's headers to the standard reinsurance schema and get validated records back.

## Steps

### 1. Upload the file

```bash
curl -F "file=@your_bordereaux.csv" http://localhost:8000/upload
```

For Excel files:

```bash
curl -F "file=@your_bordereaux.xlsx" http://localhost:8000/upload
```

### 2. Read the response

The response contains:

- `mapping.mappings` — each source header mapped to a target field with confidence
- `mapping.unmapped_headers` — headers that didn't match any target field
- `confidence_report` — summary of mapping confidence
- `valid_records` — rows that passed all validation checks
- `invalid_records` — rows that failed validation
- `errors` — specific error messages with row numbers

### 3. Check for issues

**Low confidence mappings:** If `confidence_report.low_confidence_fields` is not empty, review those mappings manually. The AI wasn't sure about them.

**Missing fields:** If `confidence_report.missing_fields` is not empty, some target fields weren't found in the source data.

**Invalid records:** Check `errors` for row-level validation failures. Each error includes the row number and a description of what went wrong.

## Options

| Parameter | Example | Purpose |
|-----------|---------|---------|
| `sheet_name` | `?sheet_name=Claims` | Process a specific Excel sheet |
| `cedent_id` | `?cedent_id=ACME-RE` | Apply corrections from this cedent |
| `schema` | `?schema=marine_cargo` | Use a custom target schema |

## Supported file types

- `.csv` — comma-separated values
- `.xlsx` — Excel (modern)
- `.xls` — Excel (legacy)

Maximum file size: 10 MB.
