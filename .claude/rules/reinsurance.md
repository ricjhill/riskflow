---
paths:
  - "src/domain/**/*.py"
  - "src/adapters/slm/**/*.py"
---

# Reinsurance Domain Rules

## Target Schema
The default schema maps to 6 fields: `Policy_ID`, `Inception_Date`, `Expiry_Date`, `Sum_Insured`, `Gross_Premium`, `Currency`. Custom schemas can define different fields via YAML in `schemas/`. The active schema is loaded from `schemas/default.yaml` (or `SCHEMA_PATH` env var) at startup.

## Validation
- Field constraints (non_negative, not_empty, allowed_values) are defined per field in the schema YAML
- Dates: flexible parsing via `coerce_date()` — accepts ISO 8601, DD-Mon-YYYY, DD/MM/YYYY, YYYY/MM/DD, verbose formats. Uses `dayfirst=True` (London market convention)
- Cross-field rules (e.g., Expiry_Date must not precede Inception_Date) are defined in the schema
- Validation uses the dynamic model from `build_record_model(schema)`, not hardcoded classes

## SLM Prompt Context
- SLM hints (e.g., "GWP" → Gross_Premium) are defined in the schema's `slm_hints` section
- The prompt is built dynamically from the schema's field names and hints
- Include sample rows so the SLM can disambiguate by data shape
- Use `response_format={"type": "json_object"}` for structured output

## Domain Errors
- `MappingConfidenceLowError` — any mapping confidence < threshold (default 0.6)
- `InvalidCedentDataError` — unparseable source data
- `SchemaValidationError` — row fails dynamic model validation
- `SLMUnavailableError` — Groq API errors (wrap, never leak)
- `InvalidSchemaError` — target schema YAML is missing, malformed, or invalid (fatal at startup)
- `InvalidCorrectionError` — correction references a target field not in the active schema
