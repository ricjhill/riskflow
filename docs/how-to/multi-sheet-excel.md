# How to: Handle Multi-Sheet Excel Files

## Goal

Process a specific sheet from an Excel workbook that contains multiple sheets.

## Steps

### 1. See what sheets are available

```bash
curl -F "file=@workbook.xlsx" http://localhost:8000/sheets
```

Response:

```json
{"sheets": ["Policies", "Claims", "Summary"]}
```

### 2. Upload with the sheet name

```bash
curl -F "file=@workbook.xlsx" "http://localhost:8000/upload?sheet_name=Claims"
```

Only the "Claims" sheet is processed. The other sheets are ignored.

## What happens if you don't specify a sheet?

For Excel files with multiple sheets, the first sheet is used by default. For CSV files, the `sheet_name` parameter is ignored (CSVs don't have sheets).

## What if the sheet doesn't exist?

You get a 400 error:

```json
{
  "detail": {
    "error_code": "INVALID_SHEET",
    "message": "Sheet 'NoSuchSheet' not found",
    "suggestion": "Check the sheet name and try again. Omit sheet_name to use the first sheet."
  }
}
```
