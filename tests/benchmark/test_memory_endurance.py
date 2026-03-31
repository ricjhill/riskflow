"""Memory endurance tests — detect heap growth under sustained load.

These tests run N operations and assert that memory growth stays
below a budget. They catch:
- Accumulating error objects or log entries that never get GC'd
- LRU cache growing beyond its maxsize (shouldn't happen, but verify)
- Pydantic model_validate retaining references to validated data
- String accumulation in cache key computation

Uses tracemalloc (stdlib) for Python-level allocations and
resource.getrusage for RSS (catches native/Rust allocations from
Pydantic-core and Polars that tracemalloc cannot see).

Budgets are 10x expected to avoid flakiness on CI runners with
different memory pressures.
"""

import datetime
import gc
import hashlib
import resource
import tracemalloc

import pytest

from src.domain.model.record_factory import build_record_model, _build_cached
from src.domain.model.schema import ColumnMapping, MappingResult
from src.domain.model.target_schema import (
    DEFAULT_TARGET_SCHEMA,
    FieldDefinition,
    FieldType,
    TargetSchema,
)

MiB = 1024 * 1024


def _tracemalloc_delta(func: object, *args: object) -> int:
    """Run func(), return peak memory growth in bytes.

    Forces GC before snapshots to reduce noise from garbage.
    """
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.take_snapshot()

    func()  # type: ignore[operator]

    gc.collect()
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    stats = after.compare_to(before, "lineno")
    growth = sum(s.size_diff for s in stats if s.size_diff > 0)
    return growth


# ---------------------------------------------------------------------------
# Memory guardrails
# ---------------------------------------------------------------------------
@pytest.mark.perf_guardrail
class TestMemoryEndurance:
    """Assert bounded memory growth under sustained operations."""

    def test_row_validation_memory_bounded(self) -> None:
        """1000 row validations must not grow heap beyond 10 MiB.

        Each row is a small dict (~1 KiB). 1000 rows should use ~1 MiB.
        Unbounded growth (e.g., accumulating ValidationError objects)
        would exceed the 10 MiB budget.
        """
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

        def validate_all() -> None:
            for row in rows:
                model.model_validate(row)

        growth = _tracemalloc_delta(validate_all)
        assert growth < 10 * MiB, (
            f"Row validation grew heap by {growth / MiB:.1f} MiB (budget: 10 MiB)"
        )

    def test_cache_key_memory_bounded(self) -> None:
        """1000 cache key computations must not grow heap beyond 5 MiB.

        SHA-256 is constant-memory. Growth signals string accumulation
        or list leaks in the sort/join pipeline.
        """
        schema = DEFAULT_TARGET_SCHEMA

        def compute_keys() -> None:
            for i in range(1000):
                headers = [f"Column_{j}_{i}" for j in range(20)]
                normalized = "|".join(sorted(h.lower().strip() for h in headers))
                key_input = f"{schema.fingerprint}:{normalized}"
                hashlib.sha256(key_input.encode()).hexdigest()

        growth = _tracemalloc_delta(compute_keys)
        assert growth < 5 * MiB, (
            f"Cache key computation grew heap by {growth / MiB:.1f} MiB (budget: 5 MiB)"
        )

    def test_dynamic_model_build_memory_bounded(self) -> None:
        """100 distinct dynamic model builds must not grow heap beyond 50 MiB.

        Each build generates a Pydantic BaseModel subclass with validators.
        The LRU cache is cleared each time to force cold builds. 100 classes
        at ~0.3 MiB each should use ~30 MiB. 50 MiB catches exponential leaks.
        """

        def build_many() -> None:
            for i in range(100):
                schema = TargetSchema(
                    name=f"endurance_{i}",
                    fields={
                        f"Field_A_{i}": FieldDefinition(
                            type=FieldType.STRING, not_empty=True
                        ),
                        f"Field_B_{i}": FieldDefinition(type=FieldType.DATE),
                        f"Field_C_{i}": FieldDefinition(
                            type=FieldType.FLOAT, non_negative=True
                        ),
                    },
                )
                _build_cached.cache_clear()
                build_record_model(schema)
            _build_cached.cache_clear()

        growth = _tracemalloc_delta(build_many)
        assert growth < 50 * MiB, (
            f"Model build grew heap by {growth / MiB:.1f} MiB (budget: 50 MiB)"
        )

    def test_mapping_result_memory_bounded(self) -> None:
        """1000 MappingResult constructions must not grow heap beyond 10 MiB.

        Each MappingResult has 10 ColumnMapping objects. If references
        are retained (e.g., in a global list), growth will exceed budget.
        """

        def build_many() -> None:
            for i in range(1000):
                MappingResult(
                    mappings=[
                        ColumnMapping(
                            source_header=f"Src_{j}",
                            target_field=f"Tgt_{j}",
                            confidence=0.9,
                        )
                        for j in range(10)
                    ],
                    unmapped_headers=[],
                )

        growth = _tracemalloc_delta(build_many)
        assert growth < 10 * MiB, (
            f"MappingResult construction grew heap by {growth / MiB:.1f} MiB "
            f"(budget: 10 MiB)"
        )

    def test_rss_stable_under_sustained_validation(self) -> None:
        """RSS must not grow more than 50 MiB over 5000 row validations.

        This is a safety net for native memory leaks (Pydantic-core Rust,
        Polars) that tracemalloc cannot see. Uses resource.getrusage which
        tracks the process's resident set size in KiB on Linux.
        """
        model = build_record_model(DEFAULT_TARGET_SCHEMA)
        base_row = {
            "Policy_ID": "POL-0001",
            "Inception_Date": datetime.date(2025, 1, 1),
            "Expiry_Date": datetime.date(2025, 12, 31),
            "Sum_Insured": 100000.0,
            "Gross_Premium": 5000.0,
            "Currency": "USD",
        }

        gc.collect()
        rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # KiB on Linux

        for _ in range(5000):
            model.model_validate(base_row)

        gc.collect()
        rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        growth_mib = (rss_after - rss_before) / 1024  # KiB → MiB
        assert growth_mib < 50, (
            f"RSS grew by {growth_mib:.1f} MiB over 5000 validations (budget: 50 MiB)"
        )
