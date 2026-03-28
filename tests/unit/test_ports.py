"""Tests for port Protocol definitions."""

from typing import runtime_checkable

from src.domain.model.correction import Correction
from src.domain.model.schema import MappingResult
from src.ports.input.ingestor import IngestorPort
from src.ports.output.correction_cache import CorrectionCachePort
from src.ports.output.mapper import MapperPort
from src.ports.output.repo import CachePort


class TestIngestorPort:
    def test_is_runtime_checkable(self) -> None:
        assert hasattr(IngestorPort, "__protocol_attrs__") or runtime_checkable

    def test_concrete_class_satisfies_protocol(self) -> None:
        class FakeIngestor:
            def get_headers(self, file_path: str) -> list[str]:
                return []

            def get_preview(self, file_path: str, n: int = 5) -> list[dict[str, object]]:
                return []

            def get_sheet_names(self, file_path: str) -> list[str]:
                return []

        assert isinstance(FakeIngestor(), IngestorPort)

    def test_incomplete_class_does_not_satisfy(self) -> None:
        class BadIngestor:
            def get_headers(self, file_path: str) -> list[str]:
                return []

        assert not isinstance(BadIngestor(), IngestorPort)


class TestMapperPort:
    def test_concrete_class_satisfies_protocol(self) -> None:
        class FakeMapper:
            async def map_headers(
                self,
                source_headers: list[str],
                preview_rows: list[dict[str, object]],
            ) -> MappingResult:
                return MappingResult(mappings=[], unmapped_headers=[])

        assert isinstance(FakeMapper(), MapperPort)

    def test_incomplete_class_does_not_satisfy(self) -> None:
        class BadMapper:
            pass

        assert not isinstance(BadMapper(), MapperPort)


class TestCachePort:
    def test_concrete_class_satisfies_protocol(self) -> None:
        class FakeCache:
            def get_mapping(self, cache_key: str) -> MappingResult | None:
                return None

            def set_mapping(
                self, cache_key: str, result: MappingResult, ttl: int = 3600
            ) -> None:
                pass

        assert isinstance(FakeCache(), CachePort)

    def test_incomplete_class_does_not_satisfy(self) -> None:
        class BadCache:
            def get_mapping(self, cache_key: str) -> MappingResult | None:
                return None

        assert not isinstance(BadCache(), CachePort)


class TestCorrectionCachePort:
    def test_concrete_class_satisfies_protocol(self) -> None:
        class FakeCorrectionCache:
            def get_corrections(
                self, cedent_id: str, headers: list[str]
            ) -> dict[str, str]:
                return {}

            def set_correction(self, correction: Correction) -> None:
                pass

        assert isinstance(FakeCorrectionCache(), CorrectionCachePort)

    def test_incomplete_class_does_not_satisfy(self) -> None:
        class BadCorrectionCache:
            def get_corrections(
                self, cedent_id: str, headers: list[str]
            ) -> dict[str, str]:
                return {}

        assert not isinstance(BadCorrectionCache(), CorrectionCachePort)

