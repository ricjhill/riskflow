# Confidence Scores

## What is a confidence score?

Every header mapping includes a confidence score between 0.0 and 1.0. This is the AI's estimate of how certain it is that the mapping is correct.

| Score | Meaning | Action needed |
|-------|---------|---------------|
| 0.9 - 1.0 | Very confident | Accept the mapping |
| 0.7 - 0.9 | Confident | Likely correct, review if critical |
| 0.5 - 0.7 | Uncertain | Review manually |
| Below 0.5 | Low confidence | Likely wrong — correct it |

## The confidence report

Every response includes a `confidence_report` with:

- **min_confidence** — the lowest confidence score across all mappings
- **avg_confidence** — the average confidence across all mappings
- **low_confidence_fields** — list of mappings below the threshold (default 0.6)
- **missing_fields** — target fields that no source header mapped to

## What affects confidence?

**High confidence** (good): unambiguous headers, common industry terms, headers matching SLM hints
- "Policy No." → Policy_ID (0.95)
- "GWP" → Gross_Premium (0.95) — a known alias

**Low confidence** (review needed): ambiguous headers, unfamiliar terms, multiple possible targets
- "Amount" → Sum_Insured or Gross_Premium? (0.55)
- "Date" → Inception_Date or Expiry_Date? (0.50)

## Corrections override confidence

When you submit a correction via `POST /corrections`, that mapping gets confidence 1.0 on all future uploads from the same cedent. Corrections represent human-verified ground truth — they're always more reliable than AI estimates.

## The confidence threshold

Mappings below 0.6 confidence trigger a `MappingConfidenceLowError` (HTTP 422). This prevents obviously wrong mappings from being silently accepted. The threshold is configurable per MappingService instance.
