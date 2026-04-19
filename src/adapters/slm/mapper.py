"""Groq SLM adapter implementing MapperPort.

Calls Groq's Llama 3.3 via the OpenAI-compatible SDK to map messy
spreadsheet headers to the target schema. The prompt is built
dynamically from the TargetSchema:
- Enumerates all target fields from the schema
- Includes SLM hints (common aliases) if the schema defines them
- Includes sample rows so the SLM can disambiguate by data shape
- Requests JSON-only output via response_format
"""

import asyncio
import json
import time

import openai
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from src.domain.model.errors import SLMUnavailableError
from src.domain.model.schema import MappingResult
from src.domain.model.target_schema import DEFAULT_TARGET_SCHEMA, TargetSchema

DEFAULT_MODEL = "llama-3.3-70b-versatile"


def _build_system_prompt(schema: TargetSchema) -> str:
    """Build the system prompt dynamically from the target schema."""
    field_names = sorted(schema.field_names)
    fields_str = ", ".join(field_names)

    prompt = (
        "You are a reinsurance data specialist. Map spreadsheet column headers "
        "to the standard schema.\n\n"
        f"Target schema fields: {fields_str}.\n"
    )

    if schema.slm_hints:
        prompt += "\nKnown aliases:\n"
        for hint in schema.slm_hints:
            prompt += f'- "{hint.source_alias}" typically means {hint.target}\n'
    else:
        prompt += "\nNo known aliases for this schema.\n"

    prompt += (
        "\nRespond ONLY with valid JSON matching this structure:\n"
        '{"mappings": [{"source_header": "...", "target_field": "...", "confidence": <float>}], '
        '"unmapped_headers": ["..."]}\n\n'
        "Rules:\n"
        f"- target_field MUST be one of: {fields_str}\n"
        "- confidence is a float between 0.0 and 1.0 — estimate YOUR certainty:\n"
        "  - 0.9-1.0: exact or near-exact name match\n"
        "  - 0.7-0.9: strong match via known alias or clear context\n"
        "  - 0.4-0.7: uncertain, plausible but ambiguous\n"
        "  - below 0.4: guess, low certainty\n"
        "- Do NOT default all confidences to the same value — vary based on match quality\n"
        "- Headers that don't map to any target field go in unmapped_headers"
    )

    return prompt


class GroqMapper:
    """MapperPort implementation that calls Groq's Llama 3.3 for header mapping."""

    def __init__(
        self,
        client: openai.AsyncOpenAI,
        model: str = DEFAULT_MODEL,
        schema: TargetSchema | None = None,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._schema = schema or DEFAULT_TARGET_SCHEMA
        self._system_prompt = _build_system_prompt(self._schema)
        self._logger = structlog.get_logger()
        self._semaphore = semaphore

    async def map_headers(
        self,
        source_headers: list[str],
        preview_rows: list[dict[str, object]],
    ) -> MappingResult:
        """Map source headers to target schema fields via SLM."""
        user_message = self._build_user_message(source_headers, preview_rows)

        try:
            start = time.monotonic()
            response = await self._call_with_retry(user_message)
            duration_ms = int((time.monotonic() - start) * 1000)
        except openai.RateLimitError as e:
            raise SLMUnavailableError(str(e)) from e
        except Exception as e:
            raise SLMUnavailableError(str(e)) from e

        self._logger.info(
            "slm_call",
            duration_ms=duration_ms,
            model=self._model,
            headers_count=len(source_headers),
        )

        return self._parse_response(response)

    @retry(
        retry=retry_if_exception_type(openai.RateLimitError),
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=1, max=10),
        reraise=True,
    )
    async def _call_with_retry(self, user_message: str) -> object:
        """Call the SLM with retry on rate limit (429). Non-retryable errors propagate immediately."""
        if self._semaphore:
            sem_start = time.monotonic()
            async with self._semaphore:
                sem_duration_ms = int((time.monotonic() - sem_start) * 1000)
                self._logger.debug(
                    "semaphore_wait",
                    duration_ms=sem_duration_ms,
                    model=self._model,
                )
                return await self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": self._system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    response_format={"type": "json_object"},
                )
        return await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
        )

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
