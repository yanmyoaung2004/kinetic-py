from __future__ import annotations

import pytest

from src.agents.orchestrator import KinetiCDispatcher
from src.types.agent import AgentCard
from src.types.model_config import ModelConfig, StageModelConfig


class TestDispatcher:
    @pytest.fixture
    def dispatcher(self, tmp_path):
        import os

        original = os.getcwd()
        os.chdir(tmp_path)
        config = ModelConfig(
            mode="single",
            defaults={
                "think": StageModelConfig(provider="test", model="test-model"),
                "classify": StageModelConfig(provider="test", model="test-model"),
                "tool_call": StageModelConfig(provider="test", model="test-model"),
                "answer": StageModelConfig(provider="test", model="test-model"),
            },
            providers={"test": type("", (), {"base_url": "http://localhost:11434/v1", "api_key_env": ""})()},
        )
        endpoints = {"test": {"base_url": "http://localhost:11434/v1", "api_key": ""}}
        yield KinetiCDispatcher(config, endpoints)
        os.chdir(original)

    def test_register_and_get_ids(self, dispatcher):
        dispatcher.register_agent(
            AgentCard(
                id="agent1",
                system_prompt="test",
                provider="test",
                model="test-model",
                type="library",
                can_delegate=False,
            )
        )
        dispatcher.register_agent(
            AgentCard(
                id="agent2",
                system_prompt="test",
                provider="test",
                model="test-model",
                type="library",
                can_delegate=False,
            )
        )
        ids = dispatcher.get_registered_agent_ids()
        assert "agent1" in ids
        assert "agent2" in ids

    def test_stage_override(self, dispatcher):
        result = dispatcher.set_stage_override("think", "test", "new-model")
        assert "new-model" in result
        assert dispatcher._stage_overrides["think"].model == "new-model"

    def test_clear_stage_override(self, dispatcher):
        dispatcher.set_stage_override("think", "test", "m")
        result = dispatcher.clear_stage_override("think")
        assert "reset" in result
        assert "think" not in dispatcher._stage_overrides

    def test_get_provider_list(self, dispatcher):
        result = dispatcher.get_provider_list()
        assert "test" in result

    def test_get_uptime(self, dispatcher):
        uptime = dispatcher.get_uptime()
        assert "h" in uptime or "m" in uptime or "s" in uptime

    def test_get_agent_count_empty(self, dispatcher):
        assert dispatcher.get_agent_count() == 0

    def test_session_management(self, dispatcher):
        assert dispatcher.get_active_session() == "default"
        result = dispatcher.set_session("workshop")
        assert "workshop" in result
        assert dispatcher.get_active_session() == "workshop"

    def test_resolve_think_stage(self, dispatcher):
        card = AgentCard(id="test", system_prompt="", provider="test", model="test-model", type="library")
        stage = dispatcher._resolve_think_stage(card)
        assert stage.provider == "test"
        assert stage.model == "test-model"

    def test_resolve_think_stage_with_override(self, dispatcher):
        dispatcher.set_stage_override("think", "test", "override-model")
        card = AgentCard(id="test", system_prompt="", provider="test", model="test-model", type="library")
        stage = dispatcher._resolve_think_stage(card)
        assert stage.model == "override-model"

    def test_create_sub_agent_no_parent(self, dispatcher):
        with pytest.raises(RuntimeError, match="FORBIDDEN"):
            import asyncio

            asyncio.run(dispatcher.create_sub_agent("nonexistent", {"name": "sub", "soul": "be helpful", "model": "m"}))
