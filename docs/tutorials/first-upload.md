# Tutorial: Your First Upload

This tutorial walks you through uploading a bordereaux spreadsheet to RiskFlow and reading the results. By the end, you'll understand what RiskFlow does and how to interpret its output.

**Time:** 5 minutes
**Prerequisites:** RiskFlow running locally (see README.md "Getting Started")

## Step 1: Check the service is running

```bash
curl http://localhost:8000/health
```

You should see:

```json
{"status": "ok"}
```

If you get "connection refused", the service isn't running. See README.md for setup instructions.

## Step 2: Look at the sample data

RiskFlow ships with a sample bordereaux file. Here's what it looks like:

| Policy No. | Start Date | End Date | Total Sum Insured | GWP | Ccy | Broker Notes |
|------------|-----------|----------|------------------|-----|-----|--------------|
| POL-2024-001 | 2024-01-15 | 2025-01-15 | 5000000 | 125000 | USD | Annual renewal |
| POL-2024-002 | 2024-03-01 | 2025-03-01 | 2500000 | 75000 | GBP | New business |

Notice the column names are informal — "Policy No." instead of "Policy_ID", "GWP" instead of "Gross_Premium", "Ccy" instead of "Currency". This is typical of real bordereaux data. RiskFlow's job is to figure out which column maps to which standard field.

## Step 3: Upload the file

```bash
curl -F "file=@tests/fixtures/sample_bordereaux.csv" http://localhost:8000/upload | python3 -m json.tool
```

## Step 4: Read the response

The response has four sections:

### Mapping — which columns mapped to which fields

```json
{
  "mapping": {
    "mappings": [
      {"source_header": "Policy No.", "target_field": "Policy_ID", "confidence": 0.95},
      {"source_header": "Start Date", "target_field": "Inception_Date", "confidence": 0.95},
      {"source_header": "End Date", "target_field": "Expiry_Date", "confidence": 0.95},
      {"source_header": "Total Sum Insured", "target_field": "Sum_Insured", "confidence": 0.95},
      {"source_header": "GWP", "target_field": "Gross_Premium", "confidence": 0.95},
      {"source_header": "Ccy", "target_field": "Currency", "confidence": 0.95}
    ],
    "unmapped_headers": ["Broker Notes"]
  }
}
```

**What this means:**
- "Policy No." was mapped to "Policy_ID" with 95% confidence
- "GWP" was correctly identified as "Gross_Premium"
- "Broker Notes" wasn't mapped to any target field (it's not part of the schema)

### Confidence Report — how certain is the AI?

```json
{
  "confidence_report": {
    "min_confidence": 0.95,
    "avg_confidence": 0.95,
    "low_confidence_fields": [],
    "missing_fields": []
  }
}
```

All fields mapped with high confidence. No fields are missing from the mapping.

### Valid Records — rows that passed validation

```json
{
  "valid_records": [
    {
      "Policy_ID": "POL-2024-001",
      "Inception_Date": "2024-01-15",
      "Expiry_Date": "2025-01-15",
      "Sum_Insured": 5000000.0,
      "Gross_Premium": 125000.0,
      "Currency": "USD"
    }
  ]
}
```

Each row has been renamed from the source headers to the standard field names, and validated:
- Currency is a valid ISO 4217 code (USD, GBP, EUR, JPY)
- Sum_Insured and Gross_Premium are non-negative numbers
- Expiry_Date is not before Inception_Date
- Policy_ID is not empty

### Errors — rows that failed validation

```json
{
  "invalid_records": [],
  "errors": []
}
```

No errors in this sample file. If a row had an invalid currency like "DOLLARS" or a negative premium, it would appear here with the row number and error message.

## Step 5: Try it with your own file

Replace the sample file with your own bordereaux CSV or Excel file:

```bash
curl -F "file=@your_file.csv" http://localhost:8000/upload | python3 -m json.tool
```

## What you learned

- RiskFlow takes messy spreadsheet headers and maps them to standard field names
- Each mapping has a confidence score (0 to 1)
- Rows are validated against the schema (types, ranges, cross-field rules)
- Invalid rows are separated from valid ones with clear error messages
- Headers that don't match any target field are listed as "unmapped"

## Next steps

- [Handle Multi-Sheet Excel Files](../how-to/multi-sheet-excel.md) — if your bordereaux has multiple sheets
- [Correct a Wrong Mapping](../how-to/correct-mappings.md) — if the AI maps a header incorrectly
- [Features Overview](../explanation/features.md) — understand all of RiskFlow's capabilities
