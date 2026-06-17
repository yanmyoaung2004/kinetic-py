from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.providers.provider import UnifiedProvider, UnifiedProviderConfig, call_with_fallback
from src.types.agent import ToolDefinition
from src.types.llm import ChatMessage


@pytest.fixture
def provider():
    # Use a non-SDK URL so _fetch_generate is used
    return UnifiedProvider(
        UnifiedProviderConfig(
            base_url="http://unknown-provider:9999/v1",
            api_key="test-key",
            model="test-model",
        )
    )


@pytest.mark.asyncio
async def test_fetch_generate_text_response(provider):
    mock_response = {
        "choices": [{"message": {"role": "assistant", "content": "Hello world"}}],
    }

    async def mock_post(*args, **kwargs):
        m = AsyncMock()
        m.status_code = 200
        m.json = lambda: mock_response
        m.raise_for_status = lambda: None
        return m

    with patch.object(provider._client_http, "post", mock_post):
        result = await provider.generate([ChatMessage(role="user", content="hi")])
        assert result.content == "Hello world"
        assert result.role == "assistant"


@pytest.mark.asyncio
async def test_fetch_generate_tool_call(provider):
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "test_tool", "arguments": json.dumps({"arg": "val"})},
    }
    mock_response = {
        "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [tool_call]}}],
    }

    async def mock_post(*args, **kwargs):
        m = AsyncMock()
        m.status_code = 200
        m.json = lambda: mock_response
        m.raise_for_status = lambda: None
        return m

    with patch.object(provider._client_http, "post", mock_post):
        result = await provider.generate_with_tools(
            [ChatMessage(role="user", content="use tool")],
            [
                ToolDefinition(
                    function={
                        "name": "test_tool",
                        "description": "test",
                        "parameters": {"type": "object", "properties": {}, "required": []},
                    }
                )
            ],
        )
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["function"]["name"] == "test_tool"


@pytest.mark.asyncio
async def test_fetch_generate_xml_tool_call(provider):
    """Test XML <function> tag detection for models without native tool calling"""
    mock_response = {
        "choices": [{"message": {"role": "assistant", "content": '<function=test_tool>{"arg": "val"}</function>'}}],
    }

    async def mock_post(*args, **kwargs):
        m = AsyncMock()
        m.status_code = 200
        m.json = lambda: mock_response
        m.raise_for_status = lambda: None
        return m

    with patch.object(provider._client_http, "post", mock_post):
        result = await provider.generate_with_tools(
            [ChatMessage(role="user", content="use xml tool")],
            [
                ToolDefinition(
                    function={
                        "name": "test_tool",
                        "description": "test",
                        "parameters": {"type": "object", "properties": {}, "required": []},
                    }
                )
            ],
        )
        assert result.tool_calls is not None
        assert result.tool_calls[0]["function"]["name"] == "test_tool"
        assert json.loads(result.tool_calls[0]["function"]["arguments"]) == {"arg": "val"}


@pytest.mark.asyncio
async def test_fallback_all_fail():
    providers = [
        UnifiedProvider(UnifiedProviderConfig(base_url="http://fail1", api_key="", model="fail1")),
        UnifiedProvider(UnifiedProviderConfig(base_url="http://fail2", api_key="", model="fail2")),
    ]

    async def fail_fn(p):
        raise RuntimeError(f"{p.model} failed")

    with pytest.raises(RuntimeError, match="All providers failed"):
        await call_with_fallback(providers, fail_fn)


@pytest.mark.asyncio
async def test_fallback_success_after_failure():
    working = UnifiedProvider(
        UnifiedProviderConfig(
            base_url="http://localhost:11434/v1",
            api_key="",
            model="working",
        )
    )

    call_count = 0

    async def conditional_fn(p):
        nonlocal call_count
        call_count += 1
        if p.model == "fail":
            raise RuntimeError("fail")
        return {"content": "success", "tool_calls": None, "role": "assistant"}

    with patch.object(
        working, "_fetch_generate", return_value={"content": "success", "tool_calls": None, "role": "assistant"}
    ):
        result = await call_with_fallback(
            [
                UnifiedProvider(UnifiedProviderConfig(base_url="http://fail", api_key="", model="fail")),
                working,
            ],
            conditional_fn,
        )
        assert result["content"] == "success"


# ── to_dict message serialization ──


class TestMessageSerialization:
    """Verify ChatMessage.to_dict() includes tool-related fields."""

    def test_assistant_with_tool_calls(self):
        msg = ChatMessage(
            role="assistant",
            content="",
            tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "test", "arguments": "{}"}}],
        )
        d = msg.to_dict()
        assert d["role"] == "assistant"
        assert d["content"] == ""
        assert "tool_calls" in d
        assert d["tool_calls"][0]["id"] == "call_1"

    def test_tool_result_with_tool_call_id(self):
        msg = ChatMessage(
            role="tool",
            content='{"result": "done"}',
            tool_call_id="call_1",
        )
        d = msg.to_dict()
        assert d["role"] == "tool"
        assert d["tool_call_id"] == "call_1"
        assert d["content"] == '{"result": "done"}'

    def test_system_message_no_extra_fields(self):
        msg = ChatMessage(role="system", content="You are a bot.")
        d = msg.to_dict()
        assert d == {"role": "system", "content": "You are a bot."}


# ── Provider request body inspection ──


class TestRequestBodySerialization:
    """Verify _fetch_generate sends correct JSON body."""

    @pytest.mark.asyncio
    async def test_sends_tool_calls_in_messages(self, provider):
        """Messages with tool_calls are serialized via to_dict() into request body."""
        sent_body = {}

        async def mock_post(*args, **kwargs):
            nonlocal sent_body
            sent_body = kwargs.get("json", {})
            m = AsyncMock()
            m.status_code = 200
            m.json = lambda: {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
            m.raise_for_status = lambda: None
            return m

        messages = [
            ChatMessage(role="user", content="hi"),
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[{"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}],
            ),
            ChatMessage(role="tool", content="result", tool_call_id="c1"),
        ]

        with patch.object(provider._client_http, "post", mock_post):
            await provider.generate(messages)

        msgs = sent_body.get("messages", [])
        assert len(msgs) == 3
        assert "tool_calls" in msgs[1]
        assert msgs[1]["tool_calls"][0]["id"] == "c1"
        assert msgs[2]["tool_call_id"] == "c1"


# ── Empty response handling ──


@pytest.mark.asyncio
async def test_finish_reason_stop_returns_empty_content(provider):
    """finish_reason='stop' with no content returns LLMResponse(content='')."""
    mock_response = {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "reasoning_content": "thinking..."},
                "finish_reason": "stop",
            }
        ],
    }

    async def mock_post(*args, **kwargs):
        m = AsyncMock()
        m.status_code = 200
        m.json = lambda: mock_response
        m.raise_for_status = lambda: None
        return m

    with patch.object(provider._client_http, "post", mock_post):
        result = await provider.generate_with_tools(
            [ChatMessage(role="user", content="hi")],
            [
                ToolDefinition(
                    function={
                        "name": "t",
                        "description": "test",
                        "parameters": {"type": "object", "properties": {}, "required": []},
                    }
                )
            ],
        )
        assert result.content == ""
        assert result.tool_calls is None


@pytest.mark.asyncio
async def test_finish_reason_not_stop_still_raises(provider):
    """finish_reason='length' with no content still raises (not a clean stop)."""
    mock_response = {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant"},
                "finish_reason": "length",
            }
        ],
    }

    async def mock_post(*args, **kwargs):
        m = AsyncMock()
        m.status_code = 200
        m.json = lambda: mock_response
        m.raise_for_status = lambda: None
        return m

    with patch.object(provider._client_http, "post", mock_post):
        with pytest.raises(RuntimeError, match="empty response"):
            await provider.generate_with_tools(
                [ChatMessage(role="user", content="hi")],
                [
                    ToolDefinition(
                        function={
                            "name": "t",
                            "description": "test",
                            "parameters": {"type": "object", "properties": {}, "required": []},
                        }
                    )
                ],
            )
