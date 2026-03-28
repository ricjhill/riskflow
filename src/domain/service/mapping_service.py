"""Orchestrates spreadsheet mapping: ingest, cache, SLM map, validate rows."""

import hashlib

import polars as pl
import structlog
from pydantic import ValidationError

from src.domain.model.errors import MappingConfidenceLowError
from src.domain.model.record_factory import build_record_model
from src.domain.model.schema import (
    ConfidenceReport,
    MappingResult,
    ProcessingResult,
    RowError,
)
from src.domain.model.target_schema import DEFAULT_TARGET_SCHEMA, TargetSchema
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
        5. Result is cached
        6. Full dataframe is read, columns renamed, rows validated as RiskRecords
        7. ProcessingResult returned with valid records and errors
    """

    def __init__(
        self,
        ingestor: IngestorPort,
        mapper: MapperPort,
        cache: CachePort,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        schema: TargetSchema | None = None,
    ) -> None:
        self._ingestor = ingestor
        self._mapper = mapper
        self._cache = cache
        self._confidence_threshold = confidence_threshold
        self._schema = schema or DEFAULT_TARGET_SCHEMA
        self._record_model = build_record_model(self._schema)
        self._logger = structlog.get_logger()

    def get_sheet_names(self, file_path: str) -> list[str]:
        """Return sheet names for Excel files, empty list for CSV."""
        return self._ingestor.get_sheet_names(file_path)

    async def process_file(
        self, file_path: str, *, sheet_name: str | None = None
    ) -> ProcessingResult:
        """Map a spreadsheet's headers and validate all rows."""
        headers = self._ingestor.get_headers(file_path, sheet_name=sheet_name)
        preview = self._ingestor.get_preview(file_path, sheet_name=sheet_name)

        cache_key = self._build_cache_key(headers)

        cached = self._cache.get_mapping(cache_key)
        if cached is not None:
            self._logger.info("cache_lookup", result="hit", cache_key=cache_key)
            mapping = cached
        else:
            self._logger.info("cache_lookup", result="miss", cache_key=cache_key)
            mapping = await self._mapper.map_headers(headers, preview)
            self._check_confidence(mapping)
            self._cache.set_mapping(cache_key, mapping)

        return self._validate_rows(file_path, mapping, sheet_name=sheet_name)

    def _validate_rows(
        self,
        file_path: str,
        mapping: MappingResult,
        *,
        sheet_name: str | None = None,
    ) -> ProcessingResult:
        """Read full dataframe, rename columns, validate each row."""
        # Build rename map: source_header -> target_field
        rename_map = {m.source_header: m.target_field for m in mapping.mappings}

        # Read the full file
        if file_path.endswith(".csv"):
            df = pl.read_csv(file_path)
        elif sheet_name is not None:
            df = pl.read_excel(file_path, sheet_name=sheet_name)
        else:
            df = pl.read_excel(file_path)

        # Rename mapped columns
        df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})

        rows = df.to_dicts()
        valid_records: list[dict[str, object]] = []
        invalid_records: list[dict[str, object]] = []
        errors: list[RowError] = []

        for i, row in enumerate(rows):
            try:
                record = self._record_model.model_validate(row)
                valid_records.append(record.model_dump())
            except (ValidationError, ValueError) as e:
                invalid_records.append(row)
                errors.append(RowError(row=i + 1, error=str(e)))

        return ProcessingResult(
            mapping=mapping,
            confidence_report=ConfidenceReport.from_mapping_result(
                mapping,
                threshold=self._confidence_threshold,
                valid_fields=self._schema.field_names,
            ),
            valid_records=valid_records,
            invalid_records=invalid_records,
            errors=errors,
        )

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
