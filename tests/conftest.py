from __future__ import annotations

from typing import Any

import pytest


class MockProvider:
    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.model = "mock-model"
        self.responses = responses or []
        self.call_count = 0

    async def generate(self, messages: list) -> dict[str, Any]:
        return self._next_response()

    async def generate_with_tools(self, messages: list, tools: list | None = None) -> dict[str, Any]:
        return self._next_response()

    def _next_response(self) -> dict[str, Any]:
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return {"content": "Mock response", "tool_calls": None, "role": "assistant"}


@pytest.fixture
def mock_provider():
    return MockProvider()


@pytest.fixture
def mock_endpoints():
    return {
        "test": {"base_url": "http://localhost:11434/v1", "api_key": ""},
    }


@pytest.fixture
def tmp_workspace(tmp_path):
    ws = tmp_path / "agents_workspace"
    ws.mkdir()
    return ws
