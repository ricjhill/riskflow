# How to: Correct a Wrong Mapping

## Goal

When the AI maps a header incorrectly, submit a correction so future uploads from the same cedent get it right automatically.

## When to use this

You uploaded a file from cedent "ACME-RE" and the AI mapped "TSI" to "Gross_Premium" instead of "Sum_Insured". You want to fix this — not just for this upload, but for all future uploads from ACME-RE.

## Steps

### 1. Submit the correction

```bash
curl -X POST http://localhost:8000/corrections \
  -H "Content-Type: application/json" \
  -d '{
    "cedent_id": "ACME-RE",
    "corrections": [
      {"source_header": "TSI", "target_field": "Sum_Insured"}
    ]
  }'
```

Response:

```json
{"stored": 1}
```

You can submit multiple corrections at once:

```json
{
  "cedent_id": "ACME-RE",
  "corrections": [
    {"source_header": "TSI", "target_field": "Sum_Insured"},
    {"source_header": "Amt", "target_field": "Gross_Premium"}
  ]
}
```

### 2. Re-upload with the cedent ID

```bash
curl -F "file=@acme_bordereaux.csv" "http://localhost:8000/upload?cedent_id=ACME-RE"
```

Now "TSI" maps to "Sum_Insured" with confidence 1.0 — the AI is not called for that header. Only uncorrected headers go through the AI.

## How it works

- Corrections are stored in Redis, keyed by `(cedent_id, source_header)`
- On upload with `?cedent_id=`, corrected headers are applied first with confidence 1.0
- Only uncorrected headers are sent to the AI
- If all headers have corrections, the AI is never called (instant response)

## What if the target field doesn't exist?

You get a 422 error:

```json
{
  "detail": {
    "error_code": "INVALID_CORRECTION",
    "message": "Correction target 'Wrong_Field' not in schema fields: ['Currency', 'Expiry_Date', ...]",
    "suggestion": "The correction references a target field not in the active schema."
  }
}
```

## What if Redis is not configured?

Corrections require Redis. If Redis is not available, the correction is accepted but not stored (NullCorrectionCache). The upload still works — it just won't use corrections.
