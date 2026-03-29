# How to: Use the GUI Dashboard

## Goal

Use the Streamlit dashboard to upload files, inspect schemas, and submit corrections — without writing curl commands.

## Starting the GUI

### With Docker (recommended)

```bash
docker compose up -d
```

Open http://localhost:8501. The GUI connects to the API automatically.

### Without Docker

Start the API first, then the GUI in a separate terminal:

```bash
# Terminal 1: API
uv run uvicorn src.entrypoint.main:app --reload --port 8000

# Terminal 2: GUI
uv run streamlit run gui/app.py
```

Open http://localhost:8501. The sidebar shows "API connected" when the API is reachable.

## Tab 1: Mapping & Ingestion

This is the main tab for uploading and mapping bordereaux files.

### Steps

1. **Select a schema** — choose from the dropdown (e.g., "standard_reinsurance" or "marine_cargo")
2. **Set confidence threshold** — use the slider (default 0.6). Mappings below this are flagged as "Low"
3. **Upload a file** — drag and drop a CSV or Excel file
4. **Enter Cedent ID** (optional) — if this cedent has corrections, they'll be applied automatically
5. **Select a sheet** (Excel only) — if the file has multiple sheets, pick one
6. **Click "Map & Validate"** — the file is sent to the API for processing

### Reading the results

- **Column Mappings table** — green rows are high confidence, red are low confidence or unmapped
- **Metrics** — min confidence, average confidence, processing time
- **Warnings** — missing fields or low confidence fields are highlighted
- **Valid Records** — the cleaned, mapped data. Click "Download Clean CSV" to export
- **Validation Errors** — any rows that failed schema validation, with row numbers and error messages

### Error handling

If something goes wrong, the GUI shows the structured error from the API:
- **Error code** (e.g., LOW_CONFIDENCE, SLM_UNAVAILABLE)
- **Message** explaining what went wrong
- **Suggestion** for how to fix it

## Tab 2: Harness Debugger

For developers and DevOps — inspect the internals.

1. **Select a schema** to inspect
2. **Schema Definition** — the full YAML displayed as code
3. **Schema Properties** — field count, required/optional, rules, hints
4. **SLM Prompt** — the exact prompt the AI sees when mapping headers for this schema. This is reconstructed client-side from the YAML (same logic as the API)
5. **Field Definitions table** — every field with its type, required status, and constraints

Use this to verify the AI is getting the right instructions, or to debug why a mapping went wrong.

## Tab 3: Feedback & Corrections

Submit corrections when the AI maps a header incorrectly.

1. **Enter Cedent ID** — identifies who sent the bordereaux (e.g., "ACME-RE")
2. **Select schema** — the dropdown shows valid target fields for that schema
3. **Add corrections** — for each wrong mapping, enter the source header and select the correct target field
4. **Click "+ Add Row"** to add more corrections
5. **Click "Save Corrections to Redis"** — corrections are stored and applied on future uploads from this cedent

After saving, upload a file with `?cedent_id=ACME-RE` (Tab 1) and the corrected headers will map with 100% confidence.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "API not reachable" | Start the API: `docker compose up -d` |
| No schemas in dropdown | API is running but schemas/ directory is empty or not mounted |
| File upload fails | Check file is CSV/XLSX/XLS and under 10MB |
| GUI shows but API sidebar says error | Check the API URL in the sidebar matches where the API is running |
