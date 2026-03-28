"""Tests for NullCorrectionCache and RedisCorrectionCache adapters."""

import pytest

from src.adapters.storage.correction_cache import NullCorrectionCache
from src.domain.model.correction import Correction
from src.ports.output.correction_cache import CorrectionCachePort


class TestNullCorrectionCacheProtocol:
    def test_satisfies_correction_cache_port(self) -> None:
        assert isinstance(NullCorrectionCache(), CorrectionCachePort)


class TestNullCorrectionCache:
    def test_get_corrections_returns_empty_dict(self) -> None:
        cache = NullCorrectionCache()
        result = cache.get_corrections("ABC", ["GWP", "Policy No."])
        assert result == {}

    def test_set_correction_is_noop(self) -> None:
        cache = NullCorrectionCache()
        correction = Correction(
            cedent_id="ABC", source_header="GWP", target_field="Gross_Premium"
        )
        cache.set_correction(correction)  # should not raise

    def test_get_corrections_with_empty_headers(self) -> None:
        cache = NullCorrectionCache()
        result = cache.get_corrections("ABC", [])
        assert result == {}

    def test_get_corrections_returns_empty_for_any_cedent(self) -> None:
        cache = NullCorrectionCache()
        assert cache.get_corrections("any_cedent", ["h1"]) == {}
        assert cache.get_corrections("", ["h1"]) == {}
        assert cache.get_corrections("x" * 1000, ["h1"]) == {}
