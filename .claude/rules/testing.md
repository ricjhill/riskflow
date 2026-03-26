---
paths:
  - "tests/**/*.py"
---

# Testing Standards

## Default coverage (applies unless layer rules below say otherwise)
- **Happy path** — valid input produces expected output
- **Boundary values** — zero, empty string, exactly at limits (0.0, 1.0), one past limits (-0.01, 1.01)
- **Invalid input** — wrong types, out-of-range, malformed strings
- **Edge cases** — duplicates, empty collections, same value for two fields that are usually different

## Use pytest.mark.parametrize
When testing multiple valid or invalid values for the same rule, use `@pytest.mark.parametrize` instead of loops. This gives one test result per value instead of hiding failures inside a loop.

## Match error messages
Use `pytest.raises(ValueError, match="field_name")` not just `pytest.raises(ValueError)`. This proves the right validator caught the error, not an unrelated one.

## Test domain invariants explicitly
If a model has a business rule (e.g., no duplicate target fields, expiry after inception), write a dedicated test for it. Don't rely on it being caught indirectly.

## Test depth by layer
- **Domain models** — full edge case coverage: boundaries, invalid input, invariants. These are the core validation rules.
- **Ports (Protocols)** — structural only: verify classes satisfy or fail to satisfy the interface. No behavior to test.
- **Adapters** — heavy edge case coverage: empty files, missing files, malformed input, API errors, timeouts, connection failures. This is where real-world messiness hits.
- **Domain services** — test orchestration logic with mocked ports: cache hit/miss, error propagation, threshold checks.
- **HTTP routes** — test status codes, error mapping, request/response shapes. Use TestClient with mocked services.
