"""Orchestrates spreadsheet mapping: ingest, cache, SLM map, validate."""

import hashlib

from src.domain.model.errors import MappingConfidenceLowError
from src.domain.model.schema import MappingResult
from src.ports.input.ingestor import IngestorPort
from src.ports.output.mapper import MapperPort
from src.ports.output.repo import CachePort

DEFAULT_CONFIDENCE_THRESHOLD = 0.6


class MappingService:
    """Central domain service. Depends only on ports, never on adapters.

    Flow:
        1. Ingestor extracts headers and preview rows from the file
        2. Cache is checked using a deterministic key derived from headers
        3. On cache miss, the SLM mapper is called
        4. Confidence is validated against the threshold
        5. Result is cached and returned
    """

    def __init__(
        self,
        ingestor: IngestorPort,
        mapper: MapperPort,
        cache: CachePort,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._ingestor = ingestor
        self._mapper = mapper
        self._cache = cache
        self._confidence_threshold = confidence_threshold

    async def process_file(self, file_path: str) -> MappingResult:
        """Map a spreadsheet's headers to the target schema."""
        headers = self._ingestor.get_headers(file_path)
        preview = self._ingestor.get_preview(file_path)

        cache_key = self._build_cache_key(headers)

        cached = self._cache.get_mapping(cache_key)
        if cached is not None:
            return cached

        result = await self._mapper.map_headers(headers, preview)
        self._check_confidence(result)

        self._cache.set_mapping(cache_key, result)
        return result

    def _build_cache_key(self, headers: list[str]) -> str:
        """SHA-256 of sorted, lowercased, stripped headers.

        Deterministic: same headers in any order produce the same key.
        """
        normalized = "|".join(sorted(h.lower().strip() for h in headers))
        return hashlib.sha256(normalized.encode()).hexdigest()

    def _check_confidence(self, result: MappingResult) -> None:
        """Raise if any mapping falls below the confidence threshold."""
        for mapping in result.mappings:
            if mapping.confidence < self._confidence_threshold:
                msg = (
                    f"Mapping '{mapping.source_header}' -> '{mapping.target_field}' "
                    f"has confidence {mapping.confidence}, "
                    f"below threshold {self._confidence_threshold}"
                )
                raise MappingConfidenceLowError(msg)
