from __future__ import annotations

import asyncio
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
    temperature: float = 0.3  # Lower = less creative, less hallucination


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

    async def generate_stream(
        self, messages: list[ChatMessage], on_token: Callable[[str], Any],
    ) -> LLMResponse:
        """Stream tokens via on_token callback, returns final response."""
        full_content = ""
        tool_calls: list[dict[str, Any]] | None = None

        if self._use_sdk and self._client_openai:
            stream_coro = self._client_openai.chat.completions.create(
                model=self.model,
                messages=[m.to_dict() for m in messages],  # type: ignore[misc]
                temperature=self._config.temperature,
                stream=True,
            )
            stream = await stream_coro  # type: ignore[union-attr]
            async for chunk in stream:  # type: ignore[union-attr]
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    full_content += delta.content
                    on_token(delta.content)
        else:
            # Fetch path: stream via httpx SSE
            base = self._config.base_url.rstrip("/")
            body = {
                "model": self.model,
                "messages": [m.to_dict() for m in messages],
                "temperature": self._config.temperature,
                "stream": True,
            }
            headers = {
                "Content-Type": "application/json",
            }
            if self._config.api_key:
                headers["Authorization"] = f"Bearer {self._config.api_key}"
            assert self._client_http is not None
            async with self._client_http.stream(
                "POST", f"{base}/chat/completions", json=body, headers=headers,
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str and data_str != "[DONE]":
                            try:
                                data = json.loads(data_str)
                                choice = data.get("choices", [{}])[0]
                                delta = choice.get("delta", {})
                                if delta.get("content"):
                                    full_content += delta["content"]
                                    on_token(delta["content"])
                            except json.JSONDecodeError:
                                pass

        return LLMResponse(content=full_content or None, tool_calls=tool_calls, role="assistant")

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
            temperature=self._config.temperature,
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
            "temperature": self._config.temperature,
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
        raw_messages = [m.to_dict() for m in messages]
        body: dict[str, Any] = {
            "model": self.model,
            "messages": raw_messages,
            "temperature": self._config.temperature,
        }
        # DeepSeek via OpenCode Go: disable thinking mode to avoid reasoning_content issues
        if "deepseek" in self.model.lower() or "opencode" in self._config.base_url.lower():
            body["thinking"] = {"type": "disabled"}
        if tools:
            body["tools"] = [t.to_dict() for t in tools]
            body["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
        }
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

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
    max_retries: int = 2,
) -> LLMResponse:
    if not providers:
        raise RuntimeError("No providers available for call.")
    errors: list[str] = []
    for i, provider in enumerate(providers):
        for attempt in range(max_retries):
            try:
                return await call_fn(provider)
            except Exception as err:
                if "429" in str(err) and attempt < max_retries - 1:
                    import os
                    base_wait = int(os.environ.get("RATE_LIMIT_RETRY_SECONDS", "3"))
                    wait = base_wait * (attempt + 1)
                    logger.warning(
                        "[RATE_LIMIT] %s rate limited (429). Retrying in %ds... (attempt %d/%d)",
                        provider.model, wait, attempt + 1, max_retries,
                    )
                    await asyncio.sleep(wait)
                    continue
                msg = f"{provider.model}: {err}"
                errors.append(msg)
                logger.warning(
                    "[FAILOVER] %s failed: %s. %s",
                    provider.model,
                    err,
                    "Trying fallback..." if i < len(providers) - 1 else "No more fallbacks.",
                )
                break
    raise RuntimeError("All providers failed:\n" + "\n".join(errors))
