"""Groq SLM adapter implementing MapperPort.

Calls Groq's Llama 3.1 via the OpenAI-compatible SDK to map messy
spreadsheet headers to the standardized reinsurance schema. The prompt
is structured to:
- Enumerate all 6 target fields explicitly
- Emphasize that "GWP" usually means Gross_Premium
- Include sample rows so the SLM can disambiguate by data shape
- Request JSON-only output via response_format
"""

import json

import openai

from src.domain.model.errors import SLMUnavailableError
from src.domain.model.schema import VALID_TARGET_FIELDS, MappingResult

SYSTEM_PROMPT = f"""You are a reinsurance data specialist. Map spreadsheet column headers \
to the standard schema.

Target schema fields: {", ".join(sorted(VALID_TARGET_FIELDS))}.

Important context:
- "GWP" typically means Gross_Premium
- "TSI" or "Total Sum Insured" means Sum_Insured
- "Ccy" or "Currency Code" means Currency
- Policy identifiers may appear as "Policy No.", "Policy Number", "Certificate", etc.

Respond ONLY with valid JSON matching this structure:
{{"mappings": [{{"source_header": "...", "target_field": "...", "confidence": 0.95}}], \
"unmapped_headers": ["..."]}}

Rules:
- target_field MUST be one of: {", ".join(sorted(VALID_TARGET_FIELDS))}
- confidence is a float between 0.0 and 1.0
- Headers that don't map to any target field go in unmapped_headers"""

DEFAULT_MODEL = "llama-3.1-70b-versatile"


class GroqMapper:
    """MapperPort implementation that calls Groq's Llama 3.1 for header mapping."""

    def __init__(
        self,
        client: openai.AsyncOpenAI,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self._client = client
        self._model = model

    async def map_headers(
        self,
        source_headers: list[str],
        preview_rows: list[dict[str, object]],
    ) -> MappingResult:
        """Map source headers to target schema fields via SLM."""
        user_message = self._build_user_message(source_headers, preview_rows)

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
            )
        except Exception as e:
            raise SLMUnavailableError(str(e)) from e

        return self._parse_response(response)

    def _build_user_message(
        self,
        source_headers: list[str],
        preview_rows: list[dict[str, object]],
    ) -> str:
        return (
            f"Source headers: {json.dumps(source_headers)}\n"
            f"Sample rows: {json.dumps(preview_rows, default=str)}"
        )

    def _parse_response(self, response: object) -> MappingResult:
        """Extract and validate MappingResult from the SLM response."""
        choices = getattr(response, "choices", [])
        if not choices:
            msg = "SLM returned empty response"
            raise SLMUnavailableError(msg)

        content = choices[0].message.content
        if content is None:
            msg = "SLM returned empty content"
            raise SLMUnavailableError(msg)

        try:
            return MappingResult.model_validate_json(content)
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            msg = f"Failed to parse SLM response: {e}"
            raise SLMUnavailableError(msg) from e
