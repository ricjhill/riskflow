"""Tests for GroqMapper SLM adapter.

All tests mock the openai.AsyncOpenAI client — no real API calls.
Tests verify prompt construction, response parsing, and error handling.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.slm.mapper import GroqMapper
from src.domain.model.errors import SLMUnavailableError
from src.domain.model.schema import MappingResult
from src.ports.output.mapper import MapperPort


def _mock_completion(content: str) -> MagicMock:
    """Build a mock ChatCompletion response."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _valid_response_json() -> str:
    return json.dumps(
        {
            "mappings": [
                {
                    "source_header": "Policy No.",
                    "target_field": "Policy_ID",
                    "confidence": 0.99,
                },
                {
                    "source_header": "GWP",
                    "target_field": "Gross_Premium",
                    "confidence": 0.95,
                },
            ],
            "unmapped_headers": ["Extra Column"],
        }
    )


class TestGroqMapperProtocol:
    def test_satisfies_mapper_port(self) -> None:
        client = AsyncMock()
        assert isinstance(GroqMapper(client=client), MapperPort)


class TestPromptConstruction:
    @pytest.mark.asyncio
    async def test_prompt_contains_all_target_fields(self) -> None:
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            _valid_response_json()
        )
        mapper = GroqMapper(client=client)

        await mapper.map_headers(
            ["Policy No.", "GWP"],
            [{"Policy No.": "P001", "GWP": 50000}],
        )

        call_args = client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        system_msg = messages[0]["content"]

        for field in [
            "Policy_ID",
            "Inception_Date",
            "Expiry_Date",
            "Sum_Insured",
            "Gross_Premium",
            "Currency",
        ]:
            assert field in system_msg, f"{field} missing from system prompt"

    @pytest.mark.asyncio
    async def test_prompt_contains_gwp_hint(self) -> None:
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            _valid_response_json()
        )
        mapper = GroqMapper(client=client)

        await mapper.map_headers(["GWP"], [{"GWP": 50000}])

        call_args = client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        system_msg = messages[0]["content"]
        assert "GWP" in system_msg
        assert "Gross_Premium" in system_msg

    @pytest.mark.asyncio
    async def test_prompt_includes_source_headers(self) -> None:
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            _valid_response_json()
        )
        mapper = GroqMapper(client=client)

        await mapper.map_headers(
            ["Policy No.", "Start Date"],
            [{"Policy No.": "P001", "Start Date": "2024-01-01"}],
        )

        call_args = client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_msg = messages[1]["content"]
        assert "Policy No." in user_msg
        assert "Start Date" in user_msg

    @pytest.mark.asyncio
    async def test_prompt_includes_sample_rows(self) -> None:
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            _valid_response_json()
        )
        mapper = GroqMapper(client=client)

        await mapper.map_headers(
            ["ID"],
            [{"ID": "P001"}, {"ID": "P002"}],
        )

        call_args = client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_msg = messages[1]["content"]
        assert "P001" in user_msg
        assert "P002" in user_msg

    @pytest.mark.asyncio
    async def test_requests_json_response_format(self) -> None:
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            _valid_response_json()
        )
        mapper = GroqMapper(client=client)

        await mapper.map_headers(["ID"], [{"ID": "P001"}])

        call_args = client.chat.completions.create.call_args
        assert call_args.kwargs["response_format"] == {"type": "json_object"}


class TestResponseParsing:
    @pytest.mark.asyncio
    async def test_parses_valid_response(self) -> None:
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            _valid_response_json()
        )
        mapper = GroqMapper(client=client)

        result = await mapper.map_headers(
            ["Policy No.", "GWP"],
            [{"Policy No.": "P001", "GWP": 50000}],
        )

        assert isinstance(result, MappingResult)
        assert len(result.mappings) == 2
        assert result.mappings[0].target_field == "Policy_ID"
        assert result.mappings[1].target_field == "Gross_Premium"
        assert result.unmapped_headers == ["Extra Column"]

    @pytest.mark.asyncio
    async def test_raises_on_malformed_json(self) -> None:
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            "this is not json at all"
        )
        mapper = GroqMapper(client=client)

        with pytest.raises(SLMUnavailableError, match="parse"):
            await mapper.map_headers(["ID"], [{"ID": "P001"}])

    @pytest.mark.asyncio
    async def test_raises_on_valid_json_wrong_schema(self) -> None:
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            json.dumps({"wrong_field": "wrong_value"})
        )
        mapper = GroqMapper(client=client)

        with pytest.raises(SLMUnavailableError, match="parse"):
            await mapper.map_headers(["ID"], [{"ID": "P001"}])

    @pytest.mark.asyncio
    async def test_raises_on_empty_content(self) -> None:
        client = AsyncMock()
        message = MagicMock()
        message.content = None
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        client.chat.completions.create.return_value = response
        mapper = GroqMapper(client=client)

        with pytest.raises(SLMUnavailableError, match="empty"):
            await mapper.map_headers(["ID"], [{"ID": "P001"}])


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_wraps_api_error(self) -> None:
        client = AsyncMock()
        client.chat.completions.create.side_effect = Exception("API timeout")
        mapper = GroqMapper(client=client)

        with pytest.raises(SLMUnavailableError, match="API timeout"):
            await mapper.map_headers(["ID"], [{"ID": "P001"}])

    @pytest.mark.asyncio
    async def test_wraps_connection_error(self) -> None:
        client = AsyncMock()
        client.chat.completions.create.side_effect = ConnectionError(
            "unreachable"
        )
        mapper = GroqMapper(client=client)

        with pytest.raises(SLMUnavailableError, match="unreachable"):
            await mapper.map_headers(["ID"], [{"ID": "P001"}])
