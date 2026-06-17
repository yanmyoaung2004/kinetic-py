from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from openai import AsyncOpenAI

from src.types.agent import ToolDefinition
from src.types.llm import ChatMessage, LLMResponse

logger = logging.getLogger("kinetic.provider")

SDK_COMPATIBLE_DOMAINS: list[str] = []  # Disabled by default — use fetch path for tests; override when needed

FUNCTION_CALL_RE = re.compile(r"<function=(\w+)>(.*?)</function>", re.DOTALL)


@dataclass
class UnifiedProviderConfig:
    base_url: str
    api_key: str
    model: str
    max_retries: int = 2
    timeout: float = 60.0


def _supports_sdk(base_url: str) -> bool:
    lower = base_url.lower()
    return any(domain in lower for domain in SDK_COMPATIBLE_DOMAINS)


class UnifiedProvider:
    def __init__(self, config: UnifiedProviderConfig) -> None:
        self.model = config.model
        self._config = config
        self._use_sdk = _supports_sdk(config.base_url)
        self._client_http: httpx.AsyncClient | None = None
        self._client_openai: AsyncOpenAI | None = None

        self._client_http = httpx.AsyncClient(timeout=config.timeout)
        if self._use_sdk:
            try:
                self._client_openai = AsyncOpenAI(
                    api_key=config.api_key or None,
                    base_url=config.base_url,
                    timeout=config.timeout,
                    max_retries=config.max_retries,
                )
            except Exception:
                self._use_sdk = False

    async def generate(self, messages: list[ChatMessage]) -> LLMResponse:
        if self._use_sdk and self._client_openai:
            return await self._sdk_generate(messages)
        return await self._fetch_generate(messages)

    async def generate_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
    ) -> LLMResponse:
        if self._use_sdk and self._client_openai:
            return await self._sdk_generate_with_tools(messages, tools)
        return await self._fetch_generate(messages, tools)

    async def _sdk_generate(self, messages: list[ChatMessage]) -> LLMResponse:
        assert self._client_openai is not None
        response = await self._client_openai.chat.completions.create(
            model=self.model,
            messages=[m.to_dict() for m in messages],  # type: ignore[misc]
        )
        choice = response.choices[0]
        message = choice.message
        tool_calls = None
        if message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                fn = getattr(tc, "function", None)
                if fn is not None:
                    tool_calls.append(
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": fn.name,
                                "arguments": fn.arguments,
                            },
                        }
                    )
        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            role=message.role or "assistant",
        )

    async def _sdk_generate_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
    ) -> LLMResponse:
        assert self._client_openai is not None
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],  # type: ignore[misc]
        }
        if tools:
            kwargs["tools"] = [t.to_dict() for t in tools]
            kwargs["tool_choice"] = "auto"

        response = await self._client_openai.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message
        tool_calls = None
        if message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                fn = getattr(tc, "function", None)
                if fn is not None:
                    tool_calls.append(
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": fn.name,
                                "arguments": fn.arguments,
                            },
                        }
                    )
        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            role=message.role or "assistant",
        )

    async def _fetch_generate(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
    ) -> LLMResponse:
        assert self._client_http is not None
        client = self._client_http
        base = self._config.base_url.rstrip("/")
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
        }
        if tools:
            body["tools"] = [t.to_dict() for t in tools]
            body["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._config.api_key}",
        }

        response = await client.post(
            f"{base}/chat/completions",
            json=body,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content")
        tool_calls: list[dict[str, Any]] | None = message.get("tool_calls")

        # Detect <function> XML tool calls for models without native tool support
        if not tool_calls and content and tools:
            match = FUNCTION_CALL_RE.search(content)
            if match:
                try:
                    args = json.loads(match.group(2))
                    tool_calls = [
                        {
                            "id": f"call_{id(content)}",
                            "type": "function",
                            "function": {"name": match.group(1), "arguments": json.dumps(args)},
                        }
                    ]
                    content = None  # Don't return content when we have a tool call
                except json.JSONDecodeError:
                    pass

        if not tool_calls and not content:
            if tools and choice.get("finish_reason") != "stop":
                raise RuntimeError(
                    f"{self.model}: model returned empty response "
                    f"(no tool calls, no content) — may not support tool calling"
                )
            # Model is done (finish_reason: stop) — return empty content
            return LLMResponse(
                content="",
                tool_calls=None,
                role=message.get("role", "assistant"),
            )

        return LLMResponse(
            content=content if not tool_calls else None,
            tool_calls=tool_calls,
            role=message.get("role", "assistant"),
        )


async def call_with_fallback(
    providers: list[UnifiedProvider],
    call_fn: Callable[[UnifiedProvider], Any],
) -> LLMResponse:
    if not providers:
        raise RuntimeError("No providers available for call.")
    errors: list[str] = []
    for i, provider in enumerate(providers):
        try:
            return await call_fn(provider)
        except Exception as err:
            msg = f"{provider.model}: {err}"
            errors.append(msg)
            logger.warning(
                "[FAILOVER] %s failed: %s. %s",
                provider.model,
                err,
                "Trying fallback..." if i < len(providers) - 1 else "No more fallbacks.",
            )
    raise RuntimeError("All providers failed:\n" + "\n".join(errors))
