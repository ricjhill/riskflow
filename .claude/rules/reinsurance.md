---
paths:
  - "src/domain/**/*.py"
  - "src/adapters/slm/**/*.py"
---

# Reinsurance Domain Rules

All mapping must produce these fields exactly: `Policy_ID`, `Inception_Date`, `Expiry_Date`, `Sum_Insured`, `Gross_Premium`, `Currency`.

## Validation
- Currencies: ISO 4217 only (USD, GBP, EUR, JPY)
- Dates: ISO 8601 (YYYY-MM-DD)
- Financials (Sum_Insured, Gross_Premium): non-negative floats

## SLM Prompt Context
- "GWP" usually means `Gross_Premium` — always include this in prompts
- Enumerate all 6 target fields explicitly in every prompt
- Include sample rows so the SLM can disambiguate by data shape
- Use `response_format={"type": "json_object"}` for structured output

## Domain Errors
- `MappingConfidenceLowError` — any mapping confidence < 0.6
- `InvalidCedentDataError` — unparseable source data
- `SchemaValidationError` — row fails RiskRecord validation
- `SLMUnavailableError` — Groq API errors (wrap, never leak)
