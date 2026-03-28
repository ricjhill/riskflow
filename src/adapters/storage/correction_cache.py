"""Correction cache adapters for human-verified mapping corrections.

NullCorrectionCache: no-op fallback when Redis is unavailable.
RedisCorrectionCache: Redis hash per cedent (added in Loop 4).
"""

from src.domain.model.correction import Correction


class NullCorrectionCache:
    """No-op correction cache — returns no corrections, discards writes.

    Used when Redis is unavailable or no cedent_id is provided.
    """

    def get_corrections(self, cedent_id: str, headers: list[str]) -> dict[str, str]:
        return {}

    def set_correction(self, correction: Correction) -> None:
        pass
