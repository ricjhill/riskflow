# Target Schema Reference

## Default schema

The default schema (`schemas/standard_reinsurance.yaml`) defines 6 fields for standard reinsurance bordereaux:

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| Policy_ID | string | Yes | Must not be empty |
| Inception_Date | date | Yes | ISO 8601 format |
| Expiry_Date | date | Yes | Must not be before Inception_Date |
| Sum_Insured | float | Yes | Must be non-negative |
| Gross_Premium | float | Yes | Must be non-negative |
| Currency | currency | Yes | Must be one of: USD, GBP, EUR, JPY |

## Schema YAML format

```yaml
name: schema_name          # Unique name, used in ?schema= param
fields:
  Field_Name:
    type: string|date|float|currency
    required: true|false     # Default: true
    not_empty: true|false    # String only. Default: false
    non_negative: true|false # Float only. Default: false
    allowed_values: [...]    # Currency only. List of valid codes.
cross_field_rules:
  - earlier: Field_A         # Both must be date type
    later: Field_B
slm_hints:
  - source_alias: "GWP"     # Common column name in source data
    target: Gross_Premium    # Which field it maps to
```

## Field types

| Type | Python type | Accepts | Example |
|------|------------|---------|---------|
| string | str | Any text | "POL-2024-001" |
| date | datetime.date | ISO 8601 dates, various date strings | "2024-01-15" |
| float | float | Numbers, numeric strings | 5000000.0, "5000000" |
| currency | str | Only values in allowed_values | "USD" |

## Constraint rules

| Constraint | Valid on | Meaning | Invalid example |
|-----------|---------|---------|-----------------|
| `not_empty: true` | string | Rejects "" and whitespace-only | `Policy_ID: "   "` → rejected |
| `non_negative: true` | float | Rejects values < 0 | `Sum_Insured: -100` → rejected |
| `allowed_values: [X, Y]` | currency | Rejects values not in list | `Currency: "AUD"` → rejected |
| `required: true` | all | Field must be present in data | Missing Currency → rejected |

Constraint-type mismatches are caught at startup:
- `non_negative` on a string field → `InvalidSchemaError`
- `not_empty` on a float field → `InvalidSchemaError`
- `allowed_values` on a non-currency field → `InvalidSchemaError`

## Cross-field rules

Only `DateOrderingRule` is supported:

```yaml
cross_field_rules:
  - earlier: Inception_Date
    later: Expiry_Date
```

Both fields must be type `date`. The rule ensures Expiry_Date is not before Inception_Date. Same-day values are allowed.

Validation at startup:
- Both fields must exist in the schema
- Both fields must be type `date`
- `earlier` and `later` must be different fields

## SLM hints

Hints improve the AI's mapping accuracy by providing known aliases:

```yaml
slm_hints:
  - source_alias: GWP
    target: Gross_Premium
  - source_alias: TSI
    target: Sum_Insured
```

The AI includes these in its prompt: "GWP typically means Gross_Premium".

Validation at startup:
- `target` must be a field in the schema
- `source_alias` values must be unique (no two hints with the same alias)

## Schema fingerprint

Each schema has a blake2b fingerprint derived from its field definitions (excluding the name). This fingerprint is:
- Used in cache keys to prevent stale mappings across schema changes
- Logged at startup for audit trails
- Deterministic: same field definitions always produce the same fingerprint

## Creating a custom schema

See [How to: Use a Custom Schema](../how-to/custom-schema.md).
