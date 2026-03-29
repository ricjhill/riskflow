"""Tests for schema-aware SLM prompt generation.

Loop 17: GroqMapper builds the system prompt from the TargetSchema
instead of using hardcoded field names and hints. This allows the
SLM to map to any schema, not just the default 6-field reinsurance one.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.slm.mapper import GroqMapper
from src.domain.model.target_schema import (
    DEFAULT_TARGET_SCHEMA,
    FieldDefinition,
    FieldType,
    SLMHint,
    TargetSchema,
)


def _mock_completion(
    mappings: list[dict], unmapped: list[str] | None = None
) -> MagicMock:
    """Build a mock ChatCompletion response."""
    content = json.dumps(
        {
            "mappings": mappings,
            "unmapped_headers": unmapped or [],
        }
    )
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


CUSTOM_SCHEMA = TargetSchema(
    name="marine_cargo",
    fields={
        "Vessel_Name": FieldDefinition(type=FieldType.STRING, not_empty=True),
        "Voyage_Date": FieldDefinition(type=FieldType.DATE),
        "Cargo_Value": FieldDefinition(type=FieldType.FLOAT, non_negative=True),
    },
    slm_hints=[
        SLMHint(source_alias="Ship", target="Vessel_Name"),
        SLMHint(source_alias="Departure", target="Voyage_Date"),
    ],
)

SCHEMA_NO_HINTS = TargetSchema(
    name="minimal",
    fields={
        "ID": FieldDefinition(type=FieldType.STRING, not_empty=True),
        "Amount": FieldDefinition(type=FieldType.FLOAT, non_negative=True),
    },
)


class TestSchemaAwarePrompt:
    """GroqMapper builds the prompt from the provided TargetSchema."""

    @pytest.mark.asyncio
    async def test_prompt_uses_custom_field_names(self) -> None:
        """Prompt includes field names from the custom schema, not hardcoded ones."""
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            [
                {
                    "source_header": "Ship",
                    "target_field": "Vessel_Name",
                    "confidence": 0.9,
                }
            ]
        )
        mapper = GroqMapper(client=client, schema=CUSTOM_SCHEMA)

        await mapper.map_headers(["Ship"], [{"Ship": "MV Atlantic"}])

        system_msg = client.chat.completions.create.call_args.kwargs["messages"][0][
            "content"
        ]
        assert "Vessel_Name" in system_msg
        assert "Voyage_Date" in system_msg
        assert "Cargo_Value" in system_msg

    @pytest.mark.asyncio
    async def test_prompt_does_not_contain_hardcoded_fields_with_custom_schema(
        self,
    ) -> None:
        """With a custom schema, the default field names should NOT appear."""
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            [
                {
                    "source_header": "Ship",
                    "target_field": "Vessel_Name",
                    "confidence": 0.9,
                }
            ]
        )
        mapper = GroqMapper(client=client, schema=CUSTOM_SCHEMA)

        await mapper.map_headers(["Ship"], [{"Ship": "MV Atlantic"}])

        system_msg = client.chat.completions.create.call_args.kwargs["messages"][0][
            "content"
        ]
        assert "Gross_Premium" not in system_msg
        assert "Sum_Insured" not in system_msg
        assert "Currency" not in system_msg

    @pytest.mark.asyncio
    async def test_prompt_includes_slm_hints(self) -> None:
        """SLM hints from the schema appear in the prompt."""
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            [
                {
                    "source_header": "Ship",
                    "target_field": "Vessel_Name",
                    "confidence": 0.9,
                }
            ]
        )
        mapper = GroqMapper(client=client, schema=CUSTOM_SCHEMA)

        await mapper.map_headers(["Ship"], [{"Ship": "MV Atlantic"}])

        system_msg = client.chat.completions.create.call_args.kwargs["messages"][0][
            "content"
        ]
        assert "Ship" in system_msg
        assert "Vessel_Name" in system_msg
        assert "Departure" in system_msg
        assert "Voyage_Date" in system_msg

    @pytest.mark.asyncio
    async def test_prompt_with_no_hints_omits_hint_section(self) -> None:
        """When schema has no SLM hints, the prompt skips the hint section."""
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            [{"source_header": "X", "target_field": "ID", "confidence": 0.9}]
        )
        mapper = GroqMapper(client=client, schema=SCHEMA_NO_HINTS)

        await mapper.map_headers(["X"], [{"X": "123"}])

        system_msg = client.chat.completions.create.call_args.kwargs["messages"][0][
            "content"
        ]
        assert "ID" in system_msg
        assert "Amount" in system_msg
        # Should not have a "common aliases" or "hint" section
        assert (
            "alias" not in system_msg.lower()
            or "no known aliases" in system_msg.lower()
        )

    @pytest.mark.asyncio
    async def test_default_schema_prompt_backward_compatible(self) -> None:
        """With DEFAULT_TARGET_SCHEMA, prompt contains all 6 standard fields and GWP hint."""
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            [
                {
                    "source_header": "GWP",
                    "target_field": "Gross_Premium",
                    "confidence": 0.95,
                }
            ]
        )
        mapper = GroqMapper(client=client, schema=DEFAULT_TARGET_SCHEMA)

        await mapper.map_headers(["GWP"], [{"GWP": 50000}])

        system_msg = client.chat.completions.create.call_args.kwargs["messages"][0][
            "content"
        ]
        for field in [
            "Policy_ID",
            "Inception_Date",
            "Expiry_Date",
            "Sum_Insured",
            "Gross_Premium",
            "Currency",
        ]:
            assert field in system_msg
        assert "GWP" in system_msg

    @pytest.mark.asyncio
    async def test_target_field_constraint_in_prompt(self) -> None:
        """Prompt tells the SLM that target_field MUST be one of the schema fields."""
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            [{"source_header": "X", "target_field": "Vessel_Name", "confidence": 0.9}]
        )
        mapper = GroqMapper(client=client, schema=CUSTOM_SCHEMA)

        await mapper.map_headers(["X"], [{"X": "test"}])

        system_msg = client.chat.completions.create.call_args.kwargs["messages"][0][
            "content"
        ]
        # The prompt should constrain target_field to schema fields
        assert "MUST be one of" in system_msg or "must be one of" in system_msg
