# How to: Use a Custom Schema

## Goal

Define a custom target schema for bordereaux that don't fit the default 6-field reinsurance schema.

## When to use this

The default schema maps to: Policy_ID, Inception_Date, Expiry_Date, Sum_Insured, Gross_Premium, Currency. If your bordereaux needs different fields (e.g., marine cargo with Vessel_Name, Voyage_Date, Cargo_Value, Port_Of_Loading, etc.), create a custom schema. RiskFlow ships with a `marine_cargo.yaml` example alongside the default.

## Steps

### 1. Create a YAML schema file

Create a new file in the `schemas/` directory. Here's the `marine_cargo.yaml` schema that ships with RiskFlow as an example:

```yaml
# schemas/marine_cargo.yaml
name: marine_cargo
fields:
  Vessel_Name:
    type: string
    required: true
    not_empty: true
  Voyage_Date:
    type: date
    required: true
  Arrival_Date:
    type: date
    required: true
  Cargo_Value:
    type: float
    required: true
    non_negative: true
  Premium:
    type: float
    required: true
    non_negative: true
  Currency:
    type: currency
    required: true
    allowed_values: [USD, GBP, EUR, JPY, SGD, HKD]
  Port_Of_Loading:
    type: string
    required: true
    not_empty: true
  Port_Of_Discharge:
    type: string
    required: false
cross_field_rules:
  - earlier: Voyage_Date
    later: Arrival_Date
slm_hints:
  - source_alias: Ship
    target: Vessel_Name
  - source_alias: Vessel
    target: Vessel_Name
  - source_alias: Departure
    target: Voyage_Date
  - source_alias: Sailing Date
    target: Voyage_Date
  - source_alias: ETA
    target: Arrival_Date
  - source_alias: Cargo Value
    target: Cargo_Value
  - source_alias: Sum Insured
    target: Cargo_Value
  - source_alias: GWP
    target: Premium
  - source_alias: Ccy
    target: Currency
  - source_alias: Loading Port
    target: Port_Of_Loading
  - source_alias: Origin
    target: Port_Of_Loading
  - source_alias: Destination
    target: Port_Of_Discharge
  - source_alias: Discharge Port
    target: Port_Of_Discharge
```

This schema has 8 fields (including one optional: Port_Of_Discharge), a cross-field date ordering rule, extended currencies (SGD, HKD for Asia-Pacific marine), and 13 SLM hints covering shipping terminology.

### 2. Restart the application

The application loads all schemas from `schemas/` at startup. After adding a new file, restart:

```bash
docker compose restart api
```

### 3. Check it's available

```bash
curl http://localhost:8000/schemas
```

```json
{"schemas": ["marine_cargo", "standard_reinsurance"]}
```

### 4. Upload with the custom schema

```bash
curl -F "file=@cargo_data.csv" "http://localhost:8000/upload?schema=marine_cargo"
```

The AI will map headers to Vessel_Name, Voyage_Date, Cargo_Value, and Currency instead of the default fields.

## Schema reference

### Field types

| Type | Python type | Example |
|------|------------|---------|
| `string` | str | "POL-2024-001" |
| `date` | datetime.date | "2024-01-15" |
| `float` | float | 5000000.0 |
| `currency` | str (constrained) | "USD" |

### Field constraints

| Constraint | Applies to | What it does |
|-----------|-----------|-------------|
| `required: true` | All types | Field must be present |
| `not_empty: true` | string | Rejects empty or whitespace-only strings |
| `non_negative: true` | float | Rejects values below 0 |
| `allowed_values: [...]` | currency | Only listed values accepted |

### Cross-field rules

```yaml
cross_field_rules:
  - earlier: Voyage_Date
    later: Return_Date
```

Both fields must be `date` type. The rule ensures the "later" date is not before the "earlier" date.

### SLM hints

```yaml
slm_hints:
  - source_alias: Ship
    target: Vessel_Name
```

Tells the AI that "Ship" in the source data probably means "Vessel_Name". Improves mapping accuracy for domain-specific abbreviations.

## Alternative: Create schemas via the API

Instead of YAML files, you can create schemas at runtime via `POST /schemas`. No restart required.

```bash
curl -X POST http://localhost:8000/schemas \
  -H "Content-Type: application/json" \
  -d '{
    "name": "custom_marine",
    "fields": {
      "Vessel_Name": {"type": "string", "not_empty": true},
      "Voyage_Date": {"type": "date"},
      "Cargo_Value": {"type": "float", "non_negative": true}
    }
  }'
```

```json
{"name": "custom_marine", "fingerprint": "a1b2c3..."}
```

Runtime schemas persist in Redis and appear in `GET /schemas` immediately. They can be deleted with `DELETE /schemas/{name}`. Built-in schemas (from YAML) are protected.

## Alternative: Create schemas via the Flow Mapper GUI

In the Flow Mapper tab (Tab 4), you can add custom fields during mapping and save the result as a new schema:

1. Upload a file and review the SLM suggestions
2. Expand "Add Custom Target Field" and add fields with a name and type
3. Map source headers to the new fields
4. Finalise the session
5. Click "Save as New Schema" and enter a name

The saved schema includes both the original schema's fields and your custom additions.

## What if the schema YAML is invalid?

The application refuses to start. You'll see an error like:

```
InvalidSchemaError: non_negative constraint only applies to FLOAT fields, got string
```

Fix the YAML and restart. Invalid schemas are caught at startup, not at upload time.
