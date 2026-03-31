"""Performance guardrail tests — TDD-friendly regression detection.

These tests enforce time budgets on critical hot-path functions.
They run as normal pytest tests (not pytest-benchmark) so they
integrate naturally into the TDD red-green-refactor cycle:

    1. Write a guardrail test with a time budget BEFORE refactoring.
    2. Run it — green means the current implementation meets the budget.
    3. Refactor for speed. If the guardrail stays green, ship it.
    4. If the guardrail goes red after a change, you introduced a regression.

Guardrails are NOT microbenchmarks. They assert "this must finish
within X ms" — a coarse-grained safety net, not a precise measurement.
Use pytest-benchmark (tests/benchmark/test_benchmarks.py) for precise
measurements and trend tracking.

Time budgets are intentionally generous (10-50x typical) to avoid
flaky failures on slow CI runners while still catching O(n^2) regressions.
"""

import csv
import datetime
import hashlib
from pathlib import Path

import pytest

from src.domain.model.record_factory import build_record_model
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

from tests.benchmark.conftest import Timer


# ---------------------------------------------------------------------------
# Guardrail 1: Cache key computation must be fast even with many headers
# ---------------------------------------------------------------------------
@pytest.mark.perf_guardrail
class TestCacheKeyPerformance:
    """Cache key computation: SHA-256 of sorted headers + fingerprint.

    Budget: 50ms for 500 headers. Typical: <1ms.
    Catches: accidental O(n^2) string building or redundant hashing.
    """

    @staticmethod
    def _build_cache_key(headers: list[str], schema: TargetSchema) -> str:
        normalized = "|".join(sorted(h.lower().strip() for h in headers))
        key_input = f"{schema.fingerprint}:{normalized}"
        return hashlib.sha256(key_input.encode()).hexdigest()

    def test_500_headers_under_50ms(self) -> None:
        headers = [f"Column_{i}" for i in range(500)]
        with Timer() as t:
            self._build_cache_key(headers, DEFAULT_TARGET_SCHEMA)
        assert t.elapsed_ms < 50, f"Cache key took {t.elapsed_ms:.1f}ms (budget: 50ms)"

    def test_1000_headers_scales_linearly(self) -> None:
        """1000 headers should not take more than ~3x the time of 500."""
        headers_500 = [f"Column_{i}" for i in range(500)]
        headers_1000 = [f"Column_{i}" for i in range(1000)]

        with Timer() as t500:
            self._build_cache_key(headers_500, DEFAULT_TARGET_SCHEMA)
        with Timer() as t1000:
            self._build_cache_key(headers_1000, DEFAULT_TARGET_SCHEMA)

        # Allow 4x ratio to account for noise; O(n^2) would show >10x
        ratio = t1000.elapsed_ms / max(t500.elapsed_ms, 0.001)
        assert ratio < 4, (
            f"Scaling ratio {ratio:.1f}x suggests non-linear growth "
            f"(500h={t500.elapsed_ms:.2f}ms, 1000h={t1000.elapsed_ms:.2f}ms)"
        )


# ---------------------------------------------------------------------------
# Guardrail 2: Dynamic model generation must be fast
# ---------------------------------------------------------------------------
@pytest.mark.perf_guardrail
class TestRecordModelBuildPerformance:
    """build_record_model generates a Pydantic model from a TargetSchema.

    Budget: 100ms for a fresh (uncached) build with 20 fields.
    The LRU cache means repeated calls are near-instant, but the first
    call for a new schema must also be fast.
    """

    @staticmethod
    def _make_large_schema(n_fields: int) -> TargetSchema:
        fields: dict[str, FieldDefinition] = {}
        for i in range(n_fields):
            if i % 4 == 0:
                fields[f"Field_{i}"] = FieldDefinition(
                    type=FieldType.STRING, not_empty=True
                )
            elif i % 4 == 1:
                fields[f"Field_{i}"] = FieldDefinition(type=FieldType.DATE)
            elif i % 4 == 2:
                fields[f"Field_{i}"] = FieldDefinition(
                    type=FieldType.FLOAT, non_negative=True
                )
            else:
                fields[f"Field_{i}"] = FieldDefinition(
                    type=FieldType.CURRENCY,
                    allowed_values=["USD", "GBP", "EUR"],
                )
        return TargetSchema(name=f"perf_test_{n_fields}", fields=fields)

    def test_20_field_schema_under_100ms(self) -> None:
        schema = self._make_large_schema(20)
        # Clear the LRU cache to force a fresh build
        from src.domain.model.record_factory import _build_cached

        _build_cached.cache_clear()

        with Timer() as t:
            build_record_model(schema)

        assert t.elapsed_ms < 100, (
            f"Model build took {t.elapsed_ms:.1f}ms (budget: 100ms)"
        )

    def test_cached_build_under_1ms(self) -> None:
        schema = DEFAULT_TARGET_SCHEMA
        # Warm the cache
        build_record_model(schema)

        with Timer() as t:
            build_record_model(schema)

        assert t.elapsed_ms < 1, (
            f"Cached model lookup took {t.elapsed_ms:.3f}ms (budget: 1ms)"
        )


# ---------------------------------------------------------------------------
# Guardrail 3: Row validation throughput
# ---------------------------------------------------------------------------
@pytest.mark.perf_guardrail
class TestRowValidationThroughput:
    """Pydantic model_validate on 1000 rows must complete within budget.

    Budget: 500ms for 1000 valid rows. Typical: 50-100ms.
    Catches: accidentally running validators in O(n^2) or per-row I/O.
    """

    def test_1000_valid_rows_under_500ms(self) -> None:
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
            for i in range(1000)
        ]

        with Timer() as t:
            for row in rows:
                model.model_validate(row)

        assert t.elapsed_ms < 500, (
            f"1000 rows took {t.elapsed_ms:.1f}ms (budget: 500ms)"
        )

    def test_validation_scales_linearly(self) -> None:
        model = build_record_model(DEFAULT_TARGET_SCHEMA)
        base_row = {
            "Policy_ID": "POL-0001",
            "Inception_Date": datetime.date(2025, 1, 1),
            "Expiry_Date": datetime.date(2025, 12, 31),
            "Sum_Insured": 100000.0,
            "Gross_Premium": 5000.0,
            "Currency": "USD",
        }

        def validate_n(n: int) -> float:
            rows = [base_row] * n
            with Timer() as t:
                for row in rows:
                    model.model_validate(row)
            return t.elapsed_ms

        t500 = validate_n(500)
        t1000 = validate_n(1000)
        ratio = t1000 / max(t500, 0.001)
        assert ratio < 3, (
            f"Scaling ratio {ratio:.1f}x (500={t500:.1f}ms, 1000={t1000:.1f}ms)"
        )


# ---------------------------------------------------------------------------
# Guardrail 4: MappingResult + ConfidenceReport construction
# ---------------------------------------------------------------------------
@pytest.mark.perf_guardrail
class TestMappingResultPerformance:
    """Building a MappingResult with many columns and computing ConfidenceReport.

    Budget: 50ms for 100 mappings. Typical: <5ms.
    Catches: O(n^2) duplicate checking or confidence aggregation.
    """

    def test_100_mappings_under_50ms(self) -> None:
        mappings = [
            ColumnMapping(
                source_header=f"Source_{i}",
                target_field=f"Target_{i}",
                confidence=0.85,
            )
            for i in range(100)
        ]
        with Timer() as t:
            result = MappingResult(mappings=mappings, unmapped_headers=[])
            ConfidenceReport.from_mapping_result(
                result,
                threshold=0.6,
                valid_fields={f"Target_{i}" for i in range(100)},
            )
        assert t.elapsed_ms < 50, (
            f"MappingResult + ConfidenceReport took {t.elapsed_ms:.1f}ms (budget: 50ms)"
        )


# ---------------------------------------------------------------------------
# Guardrail 5: CSV ingestor file reading
# ---------------------------------------------------------------------------
@pytest.mark.perf_guardrail
class TestIngestorPerformance:
    """Polars CSV reading for a 10,000-row file.

    Budget: 500ms for reading headers + 5-row preview from a 10k-row file.
    Typical: <50ms. Catches: accidentally reading the whole file for preview.
    """

    def test_10k_row_csv_headers_under_500ms(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "large.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Policy No.", "GWP", "Currency"])
            for i in range(10_000):
                writer.writerow([f"POL-{i:05d}", 50000 + i, "USD"])

        from src.adapters.parsers.ingestor import PolarsIngestor

        ingestor = PolarsIngestor()

        with Timer() as t:
            headers = ingestor.get_headers(str(csv_path))
            preview = ingestor.get_preview(str(csv_path), n=5)

        assert len(headers) == 3
        assert len(preview) == 5
        assert t.elapsed_ms < 500, f"Ingestor took {t.elapsed_ms:.1f}ms (budget: 500ms)"


# ---------------------------------------------------------------------------
# Guardrail 6: Schema fingerprint stability and speed
# ---------------------------------------------------------------------------
@pytest.mark.perf_guardrail
class TestSchemaFingerprintPerformance:
    """Schema fingerprint computation (blake2b hash of JSON-serialized fields).

    Budget: 10ms per call. Typical: <0.5ms.
    """

    def test_fingerprint_under_10ms(self) -> None:
        with Timer() as t:
            for _ in range(100):
                _ = DEFAULT_TARGET_SCHEMA.fingerprint
        per_call = t.elapsed_ms / 100
        assert per_call < 10, f"Fingerprint took {per_call:.3f}ms/call (budget: 10ms)"
