"""pytest-benchmark suite for hot-path functions.

Unlike guardrail tests (which assert time budgets), these benchmarks
produce precise measurements and can track trends over time via
pytest-benchmark's JSON output:

    uv run pytest tests/benchmark/test_benchmarks.py --benchmark-only --benchmark-json=benchmarks/results.json

The --benchmark-json flag writes machine-readable results that can be
compared across commits:

    uv run pytest-benchmark compare benchmarks/baseline.json benchmarks/results.json

Integration with TDD:
    1. Before refactoring: run benchmarks and save baseline.
    2. Refactor.
    3. Re-run benchmarks. Compare against baseline.
    4. If any function regressed >10%, investigate before merging.
"""

from __future__ import annotations

import datetime
import hashlib
from typing import Any

import pytest

from src.domain.model.record_factory import build_record_model, _build_cached
from src.domain.model.schema import (
    ColumnMapping,
    ConfidenceReport,
    MappingResult,
)
from src.domain.model.target_schema import (
    DEFAULT_TARGET_SCHEMA,
    FieldDefinition,
    FieldType,
    TargetSchema,
)


# ---------------------------------------------------------------------------
# Benchmark 1: Cache key computation
# ---------------------------------------------------------------------------
@pytest.mark.benchmark(group="cache-key")
def test_cache_key_50_headers(
    benchmark: Any,
) -> None:
    """Benchmark cache key computation with 50 headers (typical spreadsheet)."""
    headers = [f"Column_{i}" for i in range(50)]
    schema = DEFAULT_TARGET_SCHEMA

    def compute() -> str:
        normalized = "|".join(sorted(h.lower().strip() for h in headers))
        key_input = f"{schema.fingerprint}:{normalized}"
        return hashlib.sha256(key_input.encode()).hexdigest()

    benchmark(compute)


@pytest.mark.benchmark(group="cache-key")
def test_cache_key_200_headers(
    benchmark: Any,
) -> None:
    """Benchmark cache key computation with 200 headers (large spreadsheet)."""
    headers = [f"Column_{i}" for i in range(200)]
    schema = DEFAULT_TARGET_SCHEMA

    def compute() -> str:
        normalized = "|".join(sorted(h.lower().strip() for h in headers))
        key_input = f"{schema.fingerprint}:{normalized}"
        return hashlib.sha256(key_input.encode()).hexdigest()

    benchmark(compute)


# ---------------------------------------------------------------------------
# Benchmark 2: Dynamic model generation (cold vs warm cache)
# ---------------------------------------------------------------------------
@pytest.mark.benchmark(group="model-build")
def test_model_build_cold(
    benchmark: Any,
) -> None:
    """Benchmark building a dynamic model from scratch (cache cleared)."""
    schema = TargetSchema(
        name="bench_cold",
        fields={
            "A": FieldDefinition(type=FieldType.STRING, not_empty=True),
            "B": FieldDefinition(type=FieldType.DATE),
            "C": FieldDefinition(type=FieldType.FLOAT, non_negative=True),
            "D": FieldDefinition(type=FieldType.CURRENCY, allowed_values=["USD"]),
        },
    )

    def build() -> None:
        _build_cached.cache_clear()
        build_record_model(schema)

    benchmark(build)


@pytest.mark.benchmark(group="model-build")
def test_model_build_warm(
    benchmark: Any,
) -> None:
    """Benchmark cached model lookup (LRU cache hit)."""
    schema = DEFAULT_TARGET_SCHEMA
    build_record_model(schema)  # warm cache

    benchmark(build_record_model, schema)


# ---------------------------------------------------------------------------
# Benchmark 3: Row validation
# ---------------------------------------------------------------------------
@pytest.mark.benchmark(group="row-validation")
def test_validate_single_row(
    benchmark: Any,
) -> None:
    """Benchmark validating a single row against the default schema model."""
    model = build_record_model(DEFAULT_TARGET_SCHEMA)
    row = {
        "Policy_ID": "POL-0001",
        "Inception_Date": datetime.date(2025, 1, 1),
        "Expiry_Date": datetime.date(2025, 12, 31),
        "Sum_Insured": 100000.0,
        "Gross_Premium": 5000.0,
        "Currency": "USD",
    }

    benchmark(model.model_validate, row)


@pytest.mark.benchmark(group="row-validation")
def test_validate_100_rows(
    benchmark: Any,
) -> None:
    """Benchmark validating a batch of 100 rows."""
    model = build_record_model(DEFAULT_TARGET_SCHEMA)
    rows = [
        {
            "Policy_ID": f"POL-{i:04d}",
            "Inception_Date": datetime.date(2025, 1, 1),
            "Expiry_Date": datetime.date(2025, 12, 31),
            "Sum_Insured": 100000.0 + i,
            "Gross_Premium": 5000.0 + i,
            "Currency": "USD",
        }
        for i in range(100)
    ]

    def validate_batch() -> None:
        for row in rows:
            model.model_validate(row)

    benchmark(validate_batch)


# ---------------------------------------------------------------------------
# Benchmark 4: MappingResult construction with duplicate check
# ---------------------------------------------------------------------------
@pytest.mark.benchmark(group="mapping-result")
def test_mapping_result_20_fields(
    benchmark: Any,
) -> None:
    """Benchmark building a MappingResult with 20 mappings."""
    mappings = [
        ColumnMapping(
            source_header=f"Source_{i}",
            target_field=f"Target_{i}",
            confidence=0.9,
        )
        for i in range(20)
    ]

    def build() -> MappingResult:
        return MappingResult(mappings=mappings, unmapped_headers=[])

    benchmark(build)


# ---------------------------------------------------------------------------
# Benchmark 5: ConfidenceReport aggregation
# ---------------------------------------------------------------------------
@pytest.mark.benchmark(group="confidence-report")
def test_confidence_report_50_mappings(
    benchmark: Any,
) -> None:
    """Benchmark ConfidenceReport.from_mapping_result with 50 mappings."""
    mappings = [
        ColumnMapping(
            source_header=f"Source_{i}",
            target_field=f"Target_{i}",
            confidence=0.7 + (i % 30) / 100,
        )
        for i in range(50)
    ]
    result = MappingResult(mappings=mappings, unmapped_headers=["orphan_a", "orphan_b"])
    valid_fields = {f"Target_{i}" for i in range(60)}

    benchmark(
        ConfidenceReport.from_mapping_result,
        result,
        threshold=0.6,
        valid_fields=valid_fields,
    )


# ---------------------------------------------------------------------------
# Benchmark 6: Schema fingerprint
# ---------------------------------------------------------------------------
@pytest.mark.benchmark(group="fingerprint")
def test_schema_fingerprint(
    benchmark: Any,
) -> None:
    """Benchmark computing the schema fingerprint (blake2b)."""
    schema = DEFAULT_TARGET_SCHEMA

    def compute() -> str:
        return schema.fingerprint

    benchmark(compute)
