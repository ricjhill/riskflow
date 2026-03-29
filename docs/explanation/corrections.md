# The Correction Feedback Loop

## Why corrections matter

The AI is good at mapping common headers ("Policy No." → Policy_ID) but can struggle with cedent-specific abbreviations. A cedent might call their column "PRMA" meaning "Gross_Premium" — the AI has no way to know this without examples.

Corrections let humans teach the system. Once corrected, the mapping is instant and guaranteed correct for that cedent.

## How the feedback loop works

```
Upload → AI maps headers → some are wrong
    ↓
Human reviews, submits correction
    ↓
Correction stored in Redis: (cedent_id, "PRMA") → "Gross_Premium"
    ↓
Next upload with same cedent_id → "PRMA" maps to "Gross_Premium" (confidence 1.0)
    ↓
AI only called for uncorrected headers → faster, more accurate
```

## What gets stored

Each correction is a triple: `(cedent_id, source_header, target_field)`.

- **cedent_id** identifies who sent the bordereaux (e.g., "ACME-RE", "SWISS-RE-001")
- **source_header** is the exact column name in their spreadsheet
- **target_field** is the correct standard field name

Corrections are stored in Redis as a hash per cedent: `corrections:ACME-RE` → `{"PRMA": "Gross_Premium", "TSI": "Sum_Insured"}`.

## What happens without corrections

Without `?cedent_id=` on the upload, no corrections are checked. The AI maps every header from scratch. This is the default behavior and works fine for one-off uploads.

## When corrections don't help

- **New cedents** — no corrections exist yet. The AI handles all headers.
- **Changed headers** — if a cedent renames a column (e.g., "PRMA" to "GrossPrem"), the old correction won't match. A new correction is needed.
- **Redis unavailable** — corrections require Redis. Without it, the system falls back to AI-only mapping (graceful degradation, no errors).

## Building institutional knowledge

Over time, corrections accumulate across cedents. Each cedent's correction cache becomes a dictionary of their specific terminology. This means:

1. **First upload from a new cedent:** All AI, moderate confidence
2. **After a few corrections:** Mixed AI + corrections, higher overall confidence
3. **After many corrections:** Mostly corrections, near-perfect accuracy, minimal AI calls

The system gets more accurate and faster the more it's used — without any model retraining.
