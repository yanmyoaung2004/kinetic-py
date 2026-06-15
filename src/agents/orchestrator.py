from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from src.agents.agent import AgentInstance
from src.types.agent import AgentCard, IAgent
from src.types.model_config import ModelConfig, StageModelConfig

logger = logging.getLogger("kinetic.orchestrator")

CONFIG_DIR = Path("config")
WORKSPACE_DIR = Path("agents_workspace")


class KinetiCDispatcher:
    def __init__(
        self,
        model_config: ModelConfig,
        endpoints: dict[str, dict[str, str]],
    ) -> None:
        self._model_config = model_config
        self._endpoints = endpoints
        self._registry: dict[str, AgentCard] = {}
        self._active_agents: dict[str, IAgent] = {}
        self._eviction_tasks: dict[str, asyncio.Task] = {}
        self._child_counts: dict[str, int] = {}
        self._stage_overrides: dict[str, StageModelConfig] = {}
        self.current_session: str = "default"
        self._start_time = __import__("time").time()

        self._IDLE_TIMEOUT_MS = 5 * 60 * 1000
        self._MAX_SUB_AGENTS = 3

        WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("[DISPATCHER] Workspace: %s", WORKSPACE_DIR.resolve())

    def load_and_register_agent(self, config_path: str | Path | None = None) -> None:
        path = Path(config_path) if config_path else CONFIG_DIR / "agents.json"
        if not path.exists():
            raise FileNotFoundError(f"[K.I.N.E.T.I.C ERROR] Could not find agents.json at {path.resolve()}")

        data = json.loads(path.read_text("utf-8"))
        config_dir = path.parent

        for agent_data in data.get("registry", []):
            system_prompt = "You are a helpful K.I.N.E.T.I.C. agent."
            if agent_data.get("soulPath"):
                soul_path = (config_dir / agent_data["soulPath"]).resolve()
                if soul_path.exists():
                    system_prompt = soul_path.read_text("utf-8")
                else:
                    logger.warning("[!] Soul missing for %s: %s", agent_data["id"], soul_path)

            available = list(self._model_config.providers.keys())
            self.register_agent(AgentCard(
                id=agent_data["id"],
                system_prompt=system_prompt,
                provider=agent_data.get("provider", available[0] if available else "openrouter"),
                model=agent_data.get("model", self._model_config.defaults.get("think", StageModelConfig("", "")).model),
                type=agent_data.get("type", "library"),
                api_key="",
                can_delegate=agent_data.get("can_delegate", True),
                soul_path=str((config_dir / agent_data["soulPath"]).resolve()) if agent_data.get("soulPath") else None,
            ))
        logger.info("[DISPATCHER] Registered %d agents from config.", len(data.get("registry", [])))

    def register_agent(self, card: AgentCard) -> None:
        self._registry[card.id] = card

    def get_registered_agent_ids(self) -> list[str]:
        return list(self._registry.keys())

    async def create_sub_agent(self, parent_id: str, specs: dict[str, str]) -> str:
        parent = self._active_agents.get(parent_id)
        if not parent or parent.config.type != "library":
            raise RuntimeError(f"FORBIDDEN: Agent {parent_id} lacks clearance to spawn sub-agents.")

        count = self._child_counts.get(parent_id, 0)
        if count >= self._MAX_SUB_AGENTS:
            raise RuntimeError(f"QUOTA_EXCEEDED: Maximum sub-agent limit reached for {parent_id}.")

        parent_card = self._registry.get(parent_id)
        if not parent_card:
            raise RuntimeError(f"REGISTRY_ERROR: Parent agent {parent_id} not found.")

        sub_id = f"tmp_{specs['name']}_{int(__import__('time').time() * 1000)}"
        sub_path = WORKSPACE_DIR / sub_id
        sub_path.mkdir(parents=True, exist_ok=True)
        (sub_path / "soul.md").write_text(specs["soul"])

        card = AgentCard(
            id=sub_id,
            system_prompt=specs["soul"],
            model=specs["model"],
            type="ephemeral",
            parent_id=parent_id,
            can_delegate=False,
            provider=parent_card.provider,
            api_key=parent_card.api_key,
        )
        (sub_path / "config.json").write_text(json.dumps({"id": sub_id, "soul": specs["soul"]}))
        self.register_agent(card)
        self._child_counts[parent_id] = count + 1
        return sub_id

    async def dispatch(
        self,
        target_id: str,
        message: str,
        current_depth: int = 0,
        chat_id: int | None = None,
    ) -> str:
        self._clear_agent_timeout(target_id)
        try:
            agent = await self._get_or_initialize_agent(target_id)
            return await agent.process(message, current_depth, chat_id)
        finally:
            self._schedule_eviction(target_id)

    async def _get_or_initialize_agent(self, target_id: str) -> IAgent:
        agent = self._active_agents.get(target_id)
        if agent is not None:
            return agent

        card = self._registry.get(target_id)
        if not card:
            raise RuntimeError(f"REGISTRY_ERROR: Agent '{target_id}' does not exist.")

        think_stage = self._resolve_think_stage(card)
        agent_ids = self.get_registered_agent_ids()
        max_mem = os_env_int("AGENT_MEMORY_MAX")
        mode = self._model_config.mode or "single"
        d = self._model_config.defaults

        agent = AgentInstance(
            agent_id=target_id,
            config=card,
            dispatcher=self,
            think_stage=think_stage,
            endpoints=self._endpoints,
            workspaces_dir=str(WORKSPACE_DIR),
            agent_registry=agent_ids,
            max_memory_messages=max_mem,
            session_id=self.current_session,
            mode=mode,
            classify_stage=d.get("classify"),
            tool_call_stage=d.get("tool_call"),
            answer_stage=d.get("answer"),
        )
        self._active_agents[target_id] = agent
        return agent

    def _clear_cached_agents(self) -> None:
        for agent_id, agent in list(self._active_agents.items()):
            if agent.config.type != "ephemeral":
                self._clear_agent_timeout(agent_id)
                agent.dispose()
                del self._active_agents[agent_id]

    def set_stage_override(self, stage: str, provider: str, model: str | None = None) -> str:
        available = list(self._model_config.providers.keys())
        if provider not in available:
            return f"Provider '{provider}' not found. Available: {', '.join(available)}"
        default_model = self._model_config.defaults.get("think", StageModelConfig("", "")).model
        self._stage_overrides[stage] = StageModelConfig(provider=provider, model=model or default_model)
        self._clear_cached_agents()
        return f"✓ {stage} -> {provider}/{model or default_model}"

    def clear_stage_override(self, stage: str) -> str:
        self._stage_overrides.pop(stage, None)
        return f"✓ {stage} reset to default."

    def get_active_config(self) -> str:
        lines: list[str] = []
        d = self._model_config.defaults
        stage_keys = ["classify", "think", "tool_call", "answer"] if self._model_config.mode == "multi" else ["think"]
        for stage in stage_keys:
            sc = d.get(stage)
            if not sc:
                continue
            override = self._stage_overrides.get(stage)
            display = f"{override.provider}/{override.model}" if override else f"{sc.provider}/{sc.model}"
            tag = " (overridden)" if override else ""
            lines.append(f"  {stage:<12} {display}{tag}")
        return "\n".join(lines)

    def get_provider_list(self) -> str:
        import os
        lines: list[str] = []
        for name, ep in self._model_config.providers.items():
            key_status = "✓" if os.environ.get(ep.api_key_env) else "⏭"
            lines.append(f"  {name:<14} {ep.base_url:<42} {key_status}")
        return "\n".join(lines)

    def get_uptime(self) -> str:
        delta = int(__import__("time").time() - self._start_time)
        h, remainder = divmod(delta, 3600)
        m, s = divmod(remainder, 60)
        return f"{h}h {m}m {s}s"

    def get_agent_count(self) -> int:
        return len(self._active_agents)

    def set_session(self, session_id: str) -> str:
        self.current_session = session_id
        self._clear_cached_agents()
        return f"✓ Switched to session '{session_id}'."

    def get_active_session(self) -> str:
        return self.current_session

    def _resolve_think_stage(self, card: AgentCard) -> StageModelConfig:
        d = self._model_config.defaults
        available = list(self._model_config.providers.keys())

        override = self._stage_overrides.get("think")
        if override and override.provider in available:
            return override

        provider = card.provider
        model = card.model
        if provider not in available:
            fallback = available[0] if available else ""
            logger.warning("[CONFIG] Agent '%s' references provider '%s' not in models.json. Falling back to '%s'.", card.id, provider, fallback)
            provider = fallback
            model = d.get("think", StageModelConfig("", "")).model

        return StageModelConfig(provider=provider, model=model, fallbacks=d.get("think", StageModelConfig("", "")).fallbacks)

    def _schedule_eviction(self, target_id: str) -> None:
        self._clear_agent_timeout(target_id)

        async def _evict_after_timeout() -> None:
            await asyncio.sleep(self._IDLE_TIMEOUT_MS / 1000)
            self._evict(target_id)

        task = asyncio.create_task(_evict_after_timeout())
        self._eviction_tasks[target_id] = task

    def _clear_agent_timeout(self, target_id: str) -> None:
        task = self._eviction_tasks.pop(target_id, None)
        if task and not task.done():
            task.cancel()

    def _evict(self, target_id: str) -> None:
        agent = self._active_agents.pop(target_id, None)
        if agent is None:
            return
        agent.dispose()
        if agent.config.type == "ephemeral":
            target_path = WORKSPACE_DIR / target_id
            if target_path.exists():
                shutil.rmtree(target_path)
            parent_id = agent.config.parent_id
            if parent_id:
                count = self._child_counts.get(parent_id, 1)
                self._child_counts[parent_id] = count - 1
        self._eviction_tasks.pop(target_id, None)


def os_env_int(name: str, default: int | None = None) -> int | None:
    import os
    try:
        return int(os.environ.get(name, ""))
    except (ValueError, TypeError):
        return default
