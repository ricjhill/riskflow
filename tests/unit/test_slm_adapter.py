"""Tests for GroqMapper SLM adapter.

All tests mock the openai.AsyncOpenAI client — no real API calls.
Tests verify prompt construction, response parsing, error handling,
duration logging, and semaphore-based concurrency limiting.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

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
        client.chat.completions.create.return_value = _mock_completion(_valid_response_json())
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
        client.chat.completions.create.return_value = _mock_completion(_valid_response_json())
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
        client.chat.completions.create.return_value = _mock_completion(_valid_response_json())
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
        client.chat.completions.create.return_value = _mock_completion(_valid_response_json())
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
        client.chat.completions.create.return_value = _mock_completion(_valid_response_json())
        mapper = GroqMapper(client=client)

        await mapper.map_headers(["ID"], [{"ID": "P001"}])

        call_args = client.chat.completions.create.call_args
        assert call_args.kwargs["response_format"] == {"type": "json_object"}


class TestResponseParsing:
    @pytest.mark.asyncio
    async def test_parses_valid_response(self) -> None:
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(_valid_response_json())
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
        client.chat.completions.create.return_value = _mock_completion("this is not json at all")
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


class TestResponseParsingEdgeCases:
    @pytest.mark.asyncio
    async def test_raises_on_empty_choices(self) -> None:
        """SLM returns response with empty choices list."""
        client = AsyncMock()
        response = MagicMock()
        response.choices = []
        client.chat.completions.create.return_value = response
        mapper = GroqMapper(client=client)

        with pytest.raises(SLMUnavailableError, match="empty"):
            await mapper.map_headers(["ID"], [{"ID": "P001"}])

    @pytest.mark.asyncio
    async def test_raises_on_invalid_confidence_in_response(self) -> None:
        """SLM returns valid JSON but confidence > 1.0 — MappingResult validation fails."""
        bad_json = json.dumps(
            {
                "mappings": [
                    {
                        "source_header": "GWP",
                        "target_field": "Gross_Premium",
                        "confidence": 1.5,
                    }
                ],
                "unmapped_headers": [],
            }
        )
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(bad_json)
        mapper = GroqMapper(client=client)

        with pytest.raises(SLMUnavailableError, match="parse"):
            await mapper.map_headers(["GWP"], [{"GWP": 50000}])


class TestPromptConstructionWithCustomSchema:
    @pytest.mark.asyncio
    async def test_schema_with_no_hints_says_no_aliases(self) -> None:
        """A schema with no slm_hints should produce 'No known aliases'."""
        from src.domain.model.target_schema import FieldDefinition, FieldType, TargetSchema

        schema = TargetSchema(
            name="no_hints",
            fields={"Name": FieldDefinition(type=FieldType.STRING)},
        )
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            json.dumps(
                {
                    "mappings": [
                        {"source_header": "Name", "target_field": "Name", "confidence": 0.9}
                    ],
                    "unmapped_headers": [],
                }
            )
        )
        mapper = GroqMapper(client=client, schema=schema)
        await mapper.map_headers(["Name"], [{"Name": "Alice"}])

        system_msg = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "No known aliases" in system_msg

    @pytest.mark.asyncio
    async def test_custom_schema_fields_in_prompt(self) -> None:
        """Custom schema field names should appear in the system prompt."""
        from src.domain.model.target_schema import FieldDefinition, FieldType, TargetSchema

        schema = TargetSchema(
            name="custom",
            fields={
                "Vessel_Name": FieldDefinition(type=FieldType.STRING),
                "Cargo_Value": FieldDefinition(type=FieldType.FLOAT),
            },
        )
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(
            json.dumps(
                {
                    "mappings": [
                        {"source_header": "Ship", "target_field": "Vessel_Name", "confidence": 0.9}
                    ],
                    "unmapped_headers": ["Value"],
                }
            )
        )
        mapper = GroqMapper(client=client, schema=schema)
        await mapper.map_headers(["Ship", "Value"], [{"Ship": "MV Star", "Value": 1000}])

        system_msg = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "Vessel_Name" in system_msg
        assert "Cargo_Value" in system_msg


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
        client.chat.completions.create.side_effect = ConnectionError("unreachable")
        mapper = GroqMapper(client=client)

        with pytest.raises(SLMUnavailableError, match="unreachable"):
            await mapper.map_headers(["ID"], [{"ID": "P001"}])


class TestSLMCallDurationLogging:
    """Issue #116: map_headers should log slm_call with duration_ms, model, headers_count."""

    @pytest.fixture(autouse=True)
    def _capture_logs(self) -> None:  # type: ignore[misc]
        """Configure structlog to capture log events, restoring config after."""
        self.captured_events: list[dict[str, object]] = []
        old_config = structlog.get_config()

        def capture(
            logger: object, method_name: str, event_dict: dict[str, object]
        ) -> dict[str, object]:
            self.captured_events.append(event_dict.copy())
            raise structlog.DropEvent

        structlog.configure(
            processors=[capture],
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=False,
        )
        yield
        structlog.configure(**old_config)

    @pytest.mark.asyncio
    async def test_logs_slm_call_event(self) -> None:
        """Successful SLM call emits an slm_call log event."""
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(_valid_response_json())
        mapper = GroqMapper(client=client)

        await mapper.map_headers(
            ["Policy No.", "GWP"],
            [{"Policy No.": "P001", "GWP": 50000}],
        )

        slm_events = [e for e in self.captured_events if e.get("event") == "slm_call"]
        assert len(slm_events) == 1

    @pytest.mark.asyncio
    async def test_slm_call_includes_duration_ms(self) -> None:
        """slm_call event must contain duration_ms as a non-negative int."""
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(_valid_response_json())
        mapper = GroqMapper(client=client)

        await mapper.map_headers(["GWP"], [{"GWP": 50000}])

        slm_event = next(e for e in self.captured_events if e.get("event") == "slm_call")
        assert "duration_ms" in slm_event
        assert isinstance(slm_event["duration_ms"], int)
        assert slm_event["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_slm_call_includes_model(self) -> None:
        """slm_call event must contain the model name."""
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(_valid_response_json())
        mapper = GroqMapper(client=client, model="llama-3.3-70b-versatile")

        await mapper.map_headers(["GWP"], [{"GWP": 50000}])

        slm_event = next(e for e in self.captured_events if e.get("event") == "slm_call")
        assert slm_event["model"] == "llama-3.3-70b-versatile"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("headers", "preview", "expected_count"),
        [
            ([], [], 0),
            (["GWP"], [{"GWP": 50000}], 1),
            (
                ["Policy No.", "GWP", "Extra"],
                [{"Policy No.": "P001", "GWP": 50000, "Extra": "x"}],
                3,
            ),
        ],
        ids=["zero_headers", "one_header", "three_headers"],
    )
    async def test_slm_call_includes_headers_count(
        self,
        headers: list[str],
        preview: list[dict[str, object]],
        expected_count: int,
    ) -> None:
        """slm_call event must contain the correct number of source headers."""
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(_valid_response_json())
        mapper = GroqMapper(client=client)

        await mapper.map_headers(headers, preview)

        slm_event = next(e for e in self.captured_events if e.get("event") == "slm_call")
        assert slm_event["headers_count"] == expected_count

    @pytest.mark.asyncio
    async def test_no_slm_call_log_on_api_error(self) -> None:
        """When the API call raises, no slm_call event should be emitted."""
        client = AsyncMock()
        client.chat.completions.create.side_effect = Exception("timeout")
        mapper = GroqMapper(client=client)

        with pytest.raises(SLMUnavailableError):
            await mapper.map_headers(["ID"], [{"ID": "P001"}])

        slm_events = [e for e in self.captured_events if e.get("event") == "slm_call"]
        assert len(slm_events) == 0


class TestSemaphoreConcurrencyLimiting:
    """GroqMapper accepts an optional asyncio.Semaphore to limit concurrent API calls."""

    @pytest.mark.asyncio
    async def test_mapper_accepts_optional_semaphore(self) -> None:
        """Constructing GroqMapper with a semaphore does not raise."""
        client = AsyncMock()
        sem = asyncio.Semaphore(3)
        mapper = GroqMapper(client=client, semaphore=sem)
        assert mapper is not None

    @pytest.mark.asyncio
    async def test_mapper_without_semaphore_still_works(self) -> None:
        """Backward compat: no semaphore means no concurrency limit."""
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(_valid_response_json())
        mapper = GroqMapper(client=client)

        result = await mapper.map_headers(["GWP"], [{"GWP": 50000}])
        assert len(result.mappings) == 2

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self) -> None:
        """With Semaphore(1), two concurrent calls are serialized, not parallel.

        We record timestamps to prove the second call doesn't start until
        the first completes — the opposite of test_5_concurrent_uploads_overlap.
        """
        timestamps: list[tuple[str, float, float]] = []

        async def slow_api_call(**kwargs: object) -> MagicMock:
            start = time.monotonic()
            await asyncio.sleep(0.1)
            end = time.monotonic()
            call_id = f"call_{len(timestamps)}"
            timestamps.append((call_id, start, end))
            return _mock_completion(_valid_response_json())

        client = AsyncMock()
        client.chat.completions.create.side_effect = slow_api_call

        sem = asyncio.Semaphore(1)
        mapper = GroqMapper(client=client, semaphore=sem)

        # Fire two calls concurrently
        await asyncio.gather(
            mapper.map_headers(["A"], [{"A": 1}]),
            mapper.map_headers(["B"], [{"B": 2}]),
        )

        assert len(timestamps) == 2
        (_, start_0, end_0) = timestamps[0]
        (_, start_1, end_1) = timestamps[1]

        # With Semaphore(1), the second call starts AFTER the first ends
        assert start_1 >= end_0 - 0.01, (
            f"Second call started at {start_1:.3f} before first ended at {end_0:.3f} "
            "— semaphore did not serialize"
        )


class TestSemaphoreWaitLogging:
    """DEBUG-level semaphore_wait event shows time spent waiting for the semaphore."""

    @pytest.fixture(autouse=True)
    def _capture_logs(self) -> None:  # type: ignore[misc]
        """Configure structlog to capture log events, restoring config after."""
        self.captured_events: list[dict[str, object]] = []
        old_config = structlog.get_config()

        def capture(
            logger: object, method_name: str, event_dict: dict[str, object]
        ) -> dict[str, object]:
            self.captured_events.append(event_dict.copy())
            raise structlog.DropEvent

        structlog.configure(
            processors=[capture],
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=False,
        )
        yield
        structlog.configure(**old_config)

    @pytest.mark.asyncio
    async def test_semaphore_wait_logged_with_duration(self) -> None:
        """When semaphore is present, a semaphore_wait DEBUG event is emitted."""
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(_valid_response_json())
        sem = asyncio.Semaphore(3)
        mapper = GroqMapper(client=client, semaphore=sem)

        await mapper.map_headers(["GWP"], [{"GWP": 50000}])

        wait_events = [e for e in self.captured_events if e.get("event") == "semaphore_wait"]
        assert len(wait_events) == 1
        assert "duration_ms" in wait_events[0]
        assert isinstance(wait_events[0]["duration_ms"], int)
        assert wait_events[0]["duration_ms"] >= 0
        assert wait_events[0]["model"] == "llama-3.3-70b-versatile"

    @pytest.mark.asyncio
    async def test_no_semaphore_wait_without_semaphore(self) -> None:
        """Without a semaphore, no semaphore_wait event is emitted."""
        client = AsyncMock()
        client.chat.completions.create.return_value = _mock_completion(_valid_response_json())
        mapper = GroqMapper(client=client)

        await mapper.map_headers(["GWP"], [{"GWP": 50000}])

        wait_events = [e for e in self.captured_events if e.get("event") == "semaphore_wait"]
        assert len(wait_events) == 0
