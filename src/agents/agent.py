from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.agents.memory import AgentMemory, UserProfile, build_compression_prompt, build_summary_message
from src.agents.rag.embedding import get_embedding
from src.agents.rag.vector_store import SearchOptions, add_chunks, search_similar
from src.agents.tools.briefing_tool import create_daily_briefing_tool
from src.agents.tools.browser import (
    create_browser_click_tool,
    create_browser_close_tool,
    create_browser_extract_tool,
    create_browser_fill_tool,
    create_browser_html_tool,
    create_browser_navigate_tool,
    create_browser_screenshot_tool,
)
from src.agents.tools.code_tool import create_run_code_tool
from src.agents.tools.data_connectors import create_github_index_tool, create_web_scraper_tool
from src.agents.tools.email_tool import (
    create_read_email_body_tool,
    create_read_emails_tool,
    create_reply_email_tool,
    create_send_email_tool,
)
from src.agents.tools.execute_command import create_execute_command_tool
from src.agents.tools.file_tools import (
    create_delete_file_tool,
    create_edit_file_tool,
    create_list_files_tool,
    create_read_file_tool,
    create_undo_file_tool,
    create_write_file_tool,
)
from src.agents.tools.git_tool import create_git_tool
from src.agents.tools.habit_tool import create_habit_tools
from src.agents.tools.image_search import create_image_search_tool
from src.agents.tools.image_tool import create_generate_image_tool
from src.agents.tools.knowledge_tool import (
    create_index_file_tool,
    create_index_url_tool,
    create_knowledge_stats_tool,
    create_query_knowledge_tool,
    ensure_embedding,
)
from src.agents.tools.maintenance_tools import create_maintenance_tools
from src.agents.tools.monitor_tool import create_create_monitor_tool, create_list_monitors_tool
from src.agents.tools.news_tool import create_news_tool
from src.agents.tools.obsidian_second_brain import inject_knowledge, search_vault_for_context
from src.agents.tools.obsidian_tools import (
    create_obsidian_canvas_add_tool,
    create_obsidian_create_note_tool,
    create_obsidian_daily_digest_tool,
    create_obsidian_daily_note_tool,
    create_obsidian_edit_note_tool,
    create_obsidian_graph_query_tool,
    create_obsidian_recent_tool,
    create_obsidian_search_tool,
    create_obsidian_spaced_repetition_tool,
    create_obsidian_suggest_links_tool,
    create_obsidian_tags_tool,
    create_obsidian_template_tool,
)
from src.agents.tools.opencode_tool import create_apply_opencode_tool, create_call_opencode_tool
from src.agents.tools.pipeline_tool import create_run_pipeline_tool
from src.agents.tools.pomodoro_tool import create_pomodoro_tools
from src.agents.tools.presentation_tool import create_presentation_tool
from src.agents.tools.registry import (
    ToolContext,
    ToolHandler,
    ToolRegistry,
    create_send_message_tool,
    create_web_search_tool,
)
from src.agents.tools.schedule_task import (
    create_get_time_tool,
    create_list_tasks_tool,
    create_remove_task_tool,
    create_schedule_task_tool,
)
from src.agents.tools.security_tools import create_security_tools
from src.agents.tools.send_file_tool import create_send_file_tool
from src.agents.tools.skills_tool import create_list_skills_tool
from src.agents.tools.system_tools import (
    create_download_url_tool,
    create_get_system_info_tool,
    create_read_env_var_tool,
)
from src.agents.tools.tts_tool import create_tts_speak_tool
from src.agents.tools.weather_tool import create_weather_tool
from src.agents.tools.youtube_tool import create_youtube_info_tool
from src.agents.tools.zip_tool import create_unzip_tool, create_zip_tool
from src.providers.provider import UnifiedProvider, UnifiedProviderConfig, call_with_fallback
from src.types.agent import AgentCard, IAgent, ToolDefinition
from src.types.llm import ChatMessage
from src.types.model_config import StageModelConfig

logger = logging.getLogger("kinetic.agent")

SPAWN_SPECIALIST_DEF: ToolDefinition = ToolDefinition(
    function={
        "name": "spawn_specialist",
        "description": "Creates a temporary specialized agent to handle a sub-task.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The role name (e.g., 'PythonExpert')"},
                "soul": {"type": "string", "description": "The system prompt/personality for this specialist"},
                "model": {"type": "string", "description": "Model to use for the specialist"},
                "task": {"type": "string", "description": "The specific task to send"},
            },
            "required": ["name", "soul", "model", "task"],
        },
    },
)

SPAWN_SWARM_DEF: ToolDefinition = ToolDefinition(
    function={
        "name": "spawn_swarm",
        "description": (
            "Spawns MULTIPLE sub-agents in parallel to work on different"
            " aspects of a complex task, then merges their results."
            " Use for research, analysis, or multi-perspective tasks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "The overall task description"},
                "agents": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Agent name / focus area"},
                            "soul": {"type": "string", "description": "System prompt for this specialist"},
                            "task": {"type": "string", "description": "Specific sub-task for this agent"},
                        },
                        "required": ["name", "soul", "task"],
                    },
                    "description": "List of 2-5 agents to spawn in parallel",
                },
            },
            "required": ["task", "agents"],
        },
    },
)

CURRENT_YEAR = 2026

GLOBAL_PROTOCOLS = """
# IDENTITY
- When asked "who are you", answer with your name.
- When asked "who created you", answer "Yan Myo Aung".

# ANTI-HALLUCINATION RULES
- If you don't know something, say "I don't know" or "I'm not sure." Do NOT guess.
- Your training data has a knowledge cutoff. You may not know recent events, API changes,
  or new tools. For current info, use web_search. Don't guess about recent developments.
- If you use a tool and it returns an error, tell the user the error. Don't make up results.
- Never state facts you aren't confident about. Guessing is worse than saying "I don't know."
- If the user says "thanks" or "ok", just acknowledge briefly. Don't infer new work.

# TOOL USAGE
- If a tool exists for what the user asks, call it. Don't just talk about doing it.
- Never create files, notes, or reminders unless the user explicitly asks.
- Never reveal config details, env vars, or API keys.
- If a tool call fails, tell the user. Don't retry with the same arguments.
- When you send a file via send_file, just say "Sent!" or "Here's your file."
  Do NOT include the file contents in your text response — binary content will corrupt the chat.
- If a task requires a specialist agent, you MUST call send_message. Just saying "I will delegate" does nothing.

# SOURCES OF TRUTH
- Emails → call read_emails. Don't guess what's in the inbox.
- Obsidian vault → call obsidian_search. Don't guess what notes exist.
- YouTube → call get_youtube_info. Don't guess video content.
- Schedule → call list_scheduled_tasks. Don't guess what's scheduled.

# SECOND BRAIN (OBSIDIAN)
- When the user asks something, relevant vault notes are automatically injected as context.
- When you learn new information about the user, it's auto-saved to the vault.
- After creating a note, use obsidian_suggest_links to find and suggest related notes.
- Knowledge is saved to the "Inbox" folder with auto-tagging.

# TTS / VOICE MODE
- When TTS mode is active, your full response is read aloud.
- You can provide a separate speakable version by wrapping it in [speak: ...] tags.
  Example: "Hello! 👋 [speak: Hello there.] How can I help?"
- The [speak: ...] text should be conversational, omit emojis, and flow naturally when spoken.
- If you don't provide [speak: ...], the raw text will be cleaned automatically (emojis and markdown removed).
"""


def _create_think_providers(
    think_stage: StageModelConfig,
    endpoints: dict[str, dict[str, str]],
) -> list[UnifiedProvider]:
    configs = [{"provider": think_stage.provider, "model": think_stage.model}]
    if think_stage.fallbacks:
        for fb in think_stage.fallbacks:
            configs.append({"provider": fb["provider"], "model": fb["model"]})

    providers: list[UnifiedProvider] = []
    for c in configs:
        ep = endpoints.get(c["provider"])
        if not ep:
            raise ValueError(f"Unknown provider '{c['provider']}' for model '{c['model']}'. Check models.json.")
        providers.append(
            UnifiedProvider(UnifiedProviderConfig(base_url=ep["base_url"], api_key=ep["api_key"], model=c["model"]))
        )
    return providers


# ── Smart tool filtering ──────────────────────────────
_CORE_TOOLS = {
    "read_file", "write_file", "edit_file", "delete_file", "list_files", "undo_file",
    "download_url", "execute_command", "run_code",
    "send_file", "send_message",
    "get_current_time", "get_system_info", "read_env_var",
    "web_search", "query_knowledge_base",
    "schedule_task", "list_scheduled_tasks", "create_monitor", "list_monitors",
    "spawn_specialist", "run_pipeline",
    "generate_image", "image_search", "get_youtube_info",
    "zip", "unzip", "git", "weather", "news", "daily_briefing",
    "list_skills", "call_opencode", "apply_opencode", "create_presentation",
    "browser_navigate", "browser_click", "browser_fill", "browser_extract",
    "browser_screenshot", "browser_html", "browser_close",
    "read_emails", "read_email_body", "send_email", "reply_to_email",
    "index_file", "index_url", "index_github", "scrape_and_index", "knowledge_stats",
    "tts_speak",
}

_TOOL_GROUPS = [
    ("security_", {"scan", "vulnerability", "virus", "malware", "defender", "firewall",
                   "block", "unblock", "port", "network", "process", "kill", "threat",
                   "cve", "ip", "audit", "user", "permission", "log", "event", "usb",
                   "startup", "wifi", "dns", "traceroute", "whois", "bandwidth",
                   "ping", "host", "password", "encrypt"}),
    ("obsidian_", {"obsidian", "vault", "note", "notes", "daily", "journal",
                   "template", "tag", "flashcard", "brain", "markdown"}),
    ("habit_", {"habit", "streak", "track"}),
    ("pomodoro_", {"pomodoro", "focus", "timer", "break"}),
    ("system_", {"disk", "temp", "cleanup", "startup"}),
    ("network_", {"dns", "traceroute", "whois", "bandwidth"}),
]


class AgentInstance(IAgent):
    def __init__(
        self,
        agent_id: str,
        config: AgentCard,
        dispatcher: Any,  # KinetiCDispatcher, avoid circular import
        think_stage: StageModelConfig,
        endpoints: dict[str, dict[str, str]],
        workspaces_dir: str | Path,
        agent_registry: list[str],
        max_memory_messages: int | None = None,
        session_id: str | None = None,
        mode: str = "single",
        classify_stage: StageModelConfig | None = None,
        tool_call_stage: StageModelConfig | None = None,
        answer_stage: StageModelConfig | None = None,
    ) -> None:
        self.id = agent_id
        self.config = config
        self._dispatcher = dispatcher
        self._mode = mode
        self._current_chat_id: int | None = None
        self._on_token: Callable[[str], None] | None = None
        self._last_tool_sequence: list[str] = []
        self._last_user_message: str = ""
        self._MAX_ITERATIONS = 3

        self._think_providers = _create_think_providers(think_stage, endpoints)
        self._classify_providers: list[UnifiedProvider] | None = None
        self._tool_call_providers: list[UnifiedProvider] | None = None
        self._answer_providers: list[UnifiedProvider] | None = None

        if mode == "multi":
            if classify_stage:
                self._classify_providers = _create_think_providers(classify_stage, endpoints)
            if tool_call_stage:
                self._tool_call_providers = _create_think_providers(tool_call_stage, endpoints)
            if answer_stage:
                self._answer_providers = _create_think_providers(answer_stage, endpoints)

        self._memory = AgentMemory(agent_id, workspaces_dir, max_memory_messages, session_id)

        # Inject system prompt
        soul = f"{self.config.system_prompt}\n{GLOBAL_PROTOCOLS}"
        existing = self._memory.get_messages()
        if not existing:
            self._memory.append(ChatMessage(role="system", content=soul))
        elif self._memory.refresh_system_prompt(soul):
            logger.info("[SYSTEM] Refreshed stale system prompt for %s", self.id)

        # Inject user profile (filtered — only permanent facts)
        profile = self._memory.read_profile()
        if profile and (profile.known_facts or profile.preferences):
            import re as _re

            _sensitive_patterns = [
                _re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
                _re.compile(r"\b\+?\d[\d\s\-().]{6,}\d\b"),
                _re.compile(r"\bhttp[s]?://\S+\b"),
            ]

            filtered = []
            for f in profile.known_facts:
                lower = f.lower()
                # Skip email/notification content — always fetch fresh
                if any(kw in lower for kw in ("email", "sent you", "received", "inbox", "gmail", "outlook", "kimi")):
                    continue
                # Skip URLs, phone numbers, emails
                if any(p.search(f) for p in _sensitive_patterns):
                    continue
                # Skip temporary/transient facts
                if any(kw in lower for kw in (
                    "reminder", "alarm", "canceled", "cancelled",
                    "having dinner", "having lunch", "eating", "going out", "back home",
                    "good night", "good morning", "water reminder", "hydration",
                    "currently", "just now", "right now", "tonight", "today's class",
                    "scheduled", "rescheduled", "postponed", "delay",
                    "5-minute", "10-second", "in 5 minutes", "in 10 minutes",
                    "nickname", "called as", "addressed as", "pinch", "boss",
                    "does not want", "don't want", "no alarm", "no reminder",
                    "sleep now", "going to sleep", "headed to bed",
                )):
                    continue
                # Skip preference about assistant's name or tone
                if any(kw in lower for kw in ("assistant should be", "assistant called", "call me", "address me as")):
                    continue
                filtered.append(f)

            if filtered or profile.preferences:
                lines = ["[USER PROFILE]"]
                lines.extend(f"- {f}" for f in filtered)
                if profile.preferences:
                    lines.append(f"\nPreferences: {', '.join(profile.preferences)}")
                self._memory.append(ChatMessage(role="system", content="\n".join(lines)))

        # Build tool registry
        self._tools = ToolRegistry()
        self._allowed_tools = set(t.lower() for t in self.config.tools) if self.config.tools else None

        if self.config.type == "library" and self.config.can_delegate:
            self._register_tool(
                ToolHandler(
                    definition=SPAWN_SPECIALIST_DEF,
                    execute=lambda args, ctx: self._execute_spawn_specialist(args),
                )
            )
            self._register_tool(
                ToolHandler(
                    definition=SPAWN_SWARM_DEF,
                    execute=lambda args, ctx: self._execute_spawn_swarm(args),
                )
            )

        if len(agent_registry) > 1:

            async def dispatch_fn(target: str, msg: str, depth: int) -> str:
                return await self._dispatcher.dispatch(target, msg, depth)

            self._register_tool(create_send_message_tool(dispatch_fn))

        if os.environ.get("BRAVE_API_KEY"):
            self._register_tool(create_web_search_tool())

        self._register_tool(create_execute_command_tool())
        self._register_tool(create_read_file_tool())
        self._register_tool(create_write_file_tool())
        self._register_tool(create_edit_file_tool())
        self._register_tool(create_delete_file_tool())
        self._register_tool(create_list_files_tool())
        self._register_tool(create_undo_file_tool())
        self._register_tool(create_schedule_task_tool(self.id))
        self._register_tool(create_list_tasks_tool())
        self._register_tool(create_remove_task_tool())
        self._register_tool(create_get_time_tool())
        self._register_tool(create_get_system_info_tool())
        self._register_tool(create_download_url_tool())
        self._register_tool(create_read_env_var_tool())
        self._register_tool(create_query_knowledge_tool(self.id))
        self._register_tool(create_index_file_tool(self.id))
        self._register_tool(create_index_url_tool(self.id))
        self._register_tool(create_knowledge_stats_tool(self.id))
        self._register_tool(
            create_run_pipeline_tool(
                lambda agent_id, msg, depth=None: self._dispatcher.dispatch(agent_id, msg, depth or 0)  # type: ignore[misc]
            )
        )
        self._register_tool(create_github_index_tool(self.id))
        self._register_tool(create_web_scraper_tool(self.id))
        # Browser tools
        self._register_tool(create_browser_navigate_tool())
        self._register_tool(create_browser_click_tool())
        self._register_tool(create_browser_fill_tool())
        self._register_tool(create_browser_extract_tool())
        self._register_tool(create_browser_screenshot_tool())
        self._register_tool(create_browser_html_tool())
        self._register_tool(create_browser_close_tool())
        self._register_tool(create_send_file_tool())
        # Monitors
        self._register_tool(create_create_monitor_tool(self.id))
        self._register_tool(create_list_monitors_tool(self.id))
        # Email
        self._register_tool(create_read_emails_tool())
        self._register_tool(create_read_email_body_tool())
        self._register_tool(create_send_email_tool())
        self._register_tool(create_reply_email_tool())
        # Code execution
        self._register_tool(create_run_code_tool())
        # Image generation
        self._register_tool(create_generate_image_tool())
        self._register_tool(create_image_search_tool())
        self._register_tool(create_youtube_info_tool())
        self._register_tool(create_zip_tool())
        self._register_tool(create_unzip_tool())
        self._register_tool(create_git_tool())
        # OpenCode tools for main + coding-assistant
        if agent_id in ("main", "coding-assistant"):
            self._register_tool(create_call_opencode_tool())
            self._register_tool(create_apply_opencode_tool())
        self._register_tool(create_weather_tool())
        self._register_tool(create_news_tool())
        self._register_tool(create_daily_briefing_tool())
        # TTS
        self._register_tool(create_tts_speak_tool())
        # Security tools (available to all agents, filtered by tool whitelist in agents.json)
        for tool in create_security_tools():
            self._register_tool(tool)
        # Skills discovery
        self._register_tool(create_list_skills_tool())
        # Presentations
        self._register_tool(create_presentation_tool())
        # Obsidian (only if vault is configured)
        if os.environ.get("OBSIDIAN_VAULT_PATH"):
            self._register_tool(create_obsidian_create_note_tool())
            self._register_tool(create_obsidian_edit_note_tool())
            self._register_tool(create_obsidian_search_tool())
            self._register_tool(create_obsidian_graph_query_tool())
            self._register_tool(create_obsidian_daily_note_tool())
            self._register_tool(create_obsidian_suggest_links_tool())
            self._register_tool(create_obsidian_daily_digest_tool())
            self._register_tool(create_obsidian_canvas_add_tool())
            self._register_tool(create_obsidian_spaced_repetition_tool())
            self._register_tool(create_obsidian_template_tool())
            self._register_tool(create_obsidian_recent_tool())
            self._register_tool(create_obsidian_tags_tool())

        # Maintenance tools
        for tool in create_maintenance_tools():
            self._register_tool(tool)

        # Productivity tools
        for tool in create_pomodoro_tools():
            self._register_tool(tool)
        for tool in create_habit_tools():
            self._register_tool(tool)

        logger.info(
            "[SYSTEM] Initialized: %s [%s] tools=%d", self.id, self.config.type, len(self._tools.get_definitions())
        )

    def _register_tool(self, handler: ToolHandler) -> None:
        name = handler.definition.function["name"]
        if self._allowed_tools is not None and name not in self._allowed_tools:
            return
        self._tools.register(handler)

    def dispose(self) -> None:
        if self.config.type == "ephemeral":
            self._memory.destroy()

    async def process(
        self, message: str, current_depth: int = 0, chat_id: int | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        max_depth = 3
        if current_depth > max_depth:
            return "ERROR: Maximum delegation depth reached. Task aborted."

        if chat_id is not None:
            self._current_chat_id = chat_id
        self._on_token = on_token
        self._last_tool_sequence = []
        self._last_user_message = message
        self._memory.append(ChatMessage(role="user", content=message))


        # Stage 1: Classify (multi mode)
        if self._mode == "multi" and self._classify_providers:
            prompt = (
                "Classify this user message into one category:"
                ' "question", "command", "chitchat", "task".'
                f"\n\nMessage: {message}\n\nRespond with ONLY the category word."
            )
            try:
                classification = await call_with_fallback(
                    self._classify_providers,
                    lambda p: p.generate(
                        [
                            ChatMessage(role="system", content="You classify user messages. Output one word only."),
                            ChatMessage(role="user", content=prompt),
                        ]
                    ),
                )
                cls = (classification.content or "").strip().lower()
                logger.info("[CLASSIFY] %s -> %s", self.id, cls)
                if cls == "chitchat":
                    from datetime import datetime as _dt2
                    now2 = _dt2.now().strftime("%A %Y-%m-%d %H:%M (%I:%M %p)")
                    chat_msgs = list(self._memory.get_messages()) + [
                        ChatMessage(role="system", content=f"[Current time: {now2}]")
                    ]
                    chat_response = await call_with_fallback(
                        self._think_providers,
                        lambda p: p.generate(chat_msgs),
                    )
                    response = chat_response.content or ""
                    self._memory.append(ChatMessage(role="assistant", content=response))
                    return response
            except Exception:
                pass

        # Stage 1.5: Recall relevant past memories (injected into think loop, not persisted)
        recall = await self._recall_memories(message)

        # Stage 1.6: Recall relevant Obsidian notes (auto-indexing)
        if os.environ.get("OBSIDIAN_VAULT_PATH"):
            try:
                vault_ctx = await search_vault_for_context(message)
                if vault_ctx:
                    recall = (recall + "\n\n" + vault_ctx) if recall else vault_ctx
            except Exception:
                pass

        # Stage 1.7: Inject matching learned skills as context
        try:
            from src.agents.skill_learner import find_matching_skills
            skills = await find_matching_skills(message)
            if skills:
                skill_text = "\n\n".join(s["content"] for s in skills)
                self._memory.append(ChatMessage(
                    role="system",
                    content=f"[LEARNED SKILLS]\n{skill_text}",
                ))
                logger.info("[SKILL] Injected %d matching skills", len(skills))
        except Exception:
            pass

        # Stage 2: Think loop
        response = await self._run_think_loop(current_depth, recall=recall, on_token=on_token)

        # Stage 3: Polish (multi mode)
        if self._mode == "multi" and self._answer_providers and response:
            try:
                polish_prompt = (
                    "Polish this response for clarity and conciseness."
                    " Keep all factual content. Output ONLY the polished text:\n\n"
                    f"{response}"
                )
                polished = await call_with_fallback(
                    self._answer_providers,
                    lambda p: p.generate(
                        [
                            ChatMessage(
                                role="system",
                                content=(
                                    "You polish responses. Make them concise and clear. Output only the polished text."
                                ),
                            ),
                            ChatMessage(role="user", content=polish_prompt),
                        ]
                    ),
                )
                if polished.content:
                    msgs = self._memory.get_messages()
                    for i in range(len(msgs) - 1, -1, -1):
                        if msgs[i].role == "assistant":
                            msgs[i].content = polished.content
                            break
                    response = polished.content
            except Exception:
                pass

        # Auto-learn: save multi-step tool sequences as reusable skills
        if self._last_tool_sequence and len(self._last_tool_sequence) >= 2 and current_depth == 0:
            try:
                from src.agents.skill_learner import extract_and_save_skill
                skill = await extract_and_save_skill(
                    self._last_user_message,
                    self._last_tool_sequence,
                    self.id,
                )
                if skill:
                    logger.info("[SKILL] Auto-learned skill: %s", skill)
            except Exception:
                pass

        # Background tasks (deferred, never block response)
        async def _background() -> None:
            msg_count = self._memory.get_user_message_count()
            if msg_count % 3 == 0:
                try:
                    await self._extract_profile()
                except Exception:
                    pass
            if msg_count % 10 == 0 and os.environ.get("OBSIDIAN_VAULT_PATH"):
                try:
                    # Knowledge injection: save conversation insights to vault
                    conv = self._memory.get_messages()[-6:]
                    conv_dicts = [
                        {"role": m.role, "content": m.content or ""}
                        for m in conv if m.role in ("user", "assistant") and m.content
                    ]
                    note = await inject_knowledge(conv_dicts, self.id)
                    if note:
                        logger.info("[BRAIN] Injected knowledge -> %s", note)
                except Exception:
                    pass
            if msg_count > 0 and msg_count % 5 == 0:
                try:
                    await self._snapshot_memory()
                except Exception:
                    pass
            if self._memory.needs_compression():
                try:
                    await self._compress_history()
                except Exception:
                    pass
            # SOUL evolution every 50 user messages (was 15 — too frequent)
            if msg_count > 0 and msg_count % 50 == 0:
                try:
                    await self._evolve_soul()
                except Exception:
                    pass

        asyncio.create_task(_background())

        return response

    async def _run_think_loop(
        self, current_depth: int, recall: str = "",
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        all_tools = self._tools.get_definitions()
        # Smart filter: keep core tools + tools matching message keywords
        msg_lower = self._last_user_message.lower()
        tools = [t for t in all_tools if t.function["name"] in _CORE_TOOLS
                 or any(t.function["name"].startswith(prefix) and any(kw in msg_lower for kw in kws)
                        for prefix, kws in _TOOL_GROUPS)]

        # Build context block (not persisted to memory)
        from datetime import datetime as _dt
        now = _dt.now().strftime("%A %Y-%m-%d %H:%M (%I:%M %p)")
        context_parts = [f"[Current time: {now}]"]
        if recall:
            context_parts.append(f"[CONTEXT FROM PAST CONVERSATIONS]\n{recall}")

        for iteration in range(self._MAX_ITERATIONS):
            is_last = iteration == self._MAX_ITERATIONS - 1
            available_tools = [] if is_last else tools

            # Inject context before each LLM call without persisting
            msgs = list(self._memory.get_messages())
            msgs.append(ChatMessage(role="system", content="\n".join(context_parts)))

            try:
                # Use streaming on the final text-only iteration
                if on_token and is_last and not available_tools:
                    try:
                        response = await call_with_fallback(
                            self._think_providers,
                            lambda p: p.generate_stream(msgs, on_token),
                        )
                    except Exception:
                        # Stream failed — fall back to normal generation
                        response = await call_with_fallback(
                            self._think_providers,
                            lambda p: p.generate_with_tools(msgs, available_tools),
                        )
                else:
                    response = await call_with_fallback(
                        self._think_providers,
                        lambda p: p.generate_with_tools(msgs, available_tools),
                    )
                # Some models return raw JSON args as content instead of tool_calls
                if response.tool_calls:
                    # Discard text content when tool calls are present
                    # (LLMs sometimes echo the tool call as text in content)
                    response.content = None
                elif response.content and response.content.strip().startswith("{"):
                    try:
                        parsed = json.loads(response.content)
                        if "path" in parsed and "content" in parsed:
                            logger.info("[AUTO] Detected raw write_file args in content")
                            response.tool_calls = [
                                {
                                    "id": "auto_0",
                                    "type": "function",
                                    "function": {"name": "sandbox_write_file", "arguments": response.content},
                                }
                            ]
                            response.content = None
                    except (json.JSONDecodeError, TypeError):
                        pass
            except Exception as err:
                if available_tools:
                    logger.warning("[TOOL_FALLBACK] Model rejected tools (%s). Retrying without tools.", err)
                    try:
                        response = await call_with_fallback(
                            self._think_providers,
                            lambda p: p.generate(msgs),
                        )
                    except Exception:
                        return (
                            "I encountered an issue with my language model."
                            " The model does not support tool calling and"
                            " I couldn't answer your request without tools."
                            " Please configure a tool-capable model in"
                            " models.json for the 'think' stage."
                        )
                else:
                    return "I encountered a processing error. Please try rephrasing your question."

            if response.tool_calls:
                calls = response.tool_calls
                logger.info(
                    "[TOOL] Iter %d: %s", iteration, ", ".join(c.get("function", {}).get("name", "?") for c in calls)
                )

                if is_last and response.tool_calls:
                    # Give the LLM one more chance to format a natural response
                    msgs = list(self._memory.get_messages())
                    try:
                        final = await call_with_fallback(
                            self._think_providers,
                            lambda p: p.generate(msgs),
                        )
                        answer = final.content or "Done."
                    except Exception:
                        last_tool = next((m for m in reversed(msgs) if m.role == "tool"), None)
                        answer = last_tool.content if last_tool else "Done."
                    self._memory.append(ChatMessage(role="assistant", content=answer))
                    return answer

                self._memory.append(ChatMessage(role="assistant", content=response.content or "", tool_calls=calls))

                seen_args: set[tuple[str, str]] = set()
                for call in calls:
                    fn_name = call.get("function", {}).get("name", "")
                    if not fn_name:
                        continue

                    try:
                        fn_args = json.loads(call["function"]["arguments"])
                    except (json.JSONDecodeError, KeyError):
                        self._memory.append(
                            ChatMessage(
                                role="tool",
                                tool_call_id=call.get("id", ""),
                                content=f"ERROR: Invalid JSON: {call.get('function', {}).get('arguments', '')}",
                            )
                        )
                        continue

                    # Dedup: skip if same tool + same args already called this iteration
                    # obsidian_create_note: only ONCE per iteration regardless of args
                    # If opencode was called, skip apply_opencode in same iteration
                    if fn_name == "apply_opencode" and any(k == "call_opencode" for k, _ in seen_args):
                        logger.info("[TOOL] Skipping apply_opencode — call_opencode just started")
                        continue
                    if fn_name == "obsidian_create_note" and any(k == "obsidian_create_note" for k, _ in seen_args):
                        logger.info("[TOOL] Skipping extra obsidian_create_note (only one per iteration)")
                        continue
                    args_key = (fn_name, json.dumps(fn_args, sort_keys=True))
                    if args_key in seen_args:
                        logger.info("[TOOL] Skipping duplicate %s with same args", fn_name)
                        continue
                    seen_args.add(args_key)

                    logger.info("[TOOL] %s -> %s", self.id, fn_name)
                    if fn_name not in ("get_current_time",) and fn_name not in self._last_tool_sequence:
                        self._last_tool_sequence.append(fn_name)

                    if fn_name == "spawn_specialist":
                        result = await self._execute_spawn_specialist(fn_args, current_depth)
                        self._memory.append(ChatMessage(role="tool", tool_call_id=call.get("id", ""), content=result))
                        self._memory.append(
                            ChatMessage(
                                role="system",
                                content=(
                                    "The specialist has reported back."
                                    " Do not delegate again."
                                    " Construct the final response now using their report."
                                ),
                            )
                        )
                    else:
                        ctx = ToolContext(depth=current_depth, chat_id=self._current_chat_id)
                        result = await self._tools.execute(fn_name, fn_args, ctx)
                        self._memory.append(ChatMessage(role="tool", tool_call_id=call.get("id", ""), content=result))
                        # If opencode was called, stop — it runs async, no need to continue
                        if fn_name == "call_opencode":
                            return "OpenCode is handling this in the background. You can keep chatting!"
                continue

            if response.content:
                self._memory.append(ChatMessage(role="assistant", content=response.content))
                return response.content

            # Model returned nothing — consider it done
            msgs = self._memory.get_messages()
            last_tool = next((m for m in reversed(msgs) if m.role == "tool"), None)
            answer = last_tool.content if last_tool else "Done."
            self._memory.append(ChatMessage(role="assistant", content=answer))
            return answer

        return "ERROR: Iteration limit exceeded. Agent failed to converge on a final answer."

    async def _extract_profile(self) -> None:
        existing = self._memory.read_profile()
        recent = [m for m in self._memory.get_messages() if m.role in ("user", "assistant")][-6:]
        if len(recent) < 2:
            return

        conversation = "\n".join(f"{'User' if m.role == 'user' else 'Assistant'}: {m.content[:500]}" for m in recent)

        prompt = f"""Extract PERMANENT personal facts about the user. Return ONLY valid JSON:
{{
  "new_facts": ["fact 1", "fact 2"],
  "new_preferences": ["pref 1"]
}}

RULES:
- Only include PERMANENT facts (name, job, skills, location, long-term goals)
- NEVER include temporary state (what they're currently doing, eating, planning tonight)
- NEVER include one-time events (reminders, alarms, cancellations)
- NEVER include preferences about the assistant's name/tone/style
- Skip greetings, small talk, and scheduling
- If a fact is already in "Previous known facts", don't repeat it

Previous known facts: {json.dumps(existing.known_facts if existing else [])}

Conversation:
{conversation}"""

        try:
            response = await call_with_fallback(
                self._think_providers,
                lambda p: p.generate(
                    [
                        ChatMessage(
                            role="system", content="You extract user information from conversations. Output JSON only."
                        ),
                        ChatMessage(role="user", content=prompt),
                    ]
                ),
            )
            raw = response.content or "{}"
            raw = re.sub(r"```json|```", "", raw).strip()
            extracted = json.loads(raw)

            merged = UserProfile(
                known_facts=list(set((existing.known_facts if existing else []) + extracted.get("new_facts", []))),
                preferences=list(
                    set((existing.preferences if existing else []) + extracted.get("new_preferences", []))
                ),
                last_updated=__import__("datetime").datetime.now().isoformat(),
                extraction_count=(existing.extraction_count if existing else 0) + 1,
            )
            self._memory.write_profile(merged)
            logger.info(
                "[PROFILE] Extracted %d facts, %d preferences",
                len(extracted.get("new_facts", [])),
                len(extracted.get("new_preferences", [])),
            )
        except Exception:
            pass

    async def _compress_history(self) -> None:
        candidates = self._memory.get_compression_candidates()
        if len(candidates) < 5:
            return

        prompt = build_compression_prompt(candidates)
        try:
            response = await call_with_fallback(
                self._think_providers,
                lambda p: p.generate(
                    [
                        ChatMessage(
                            role="system",
                            content=(
                                "You summarize conversations."
                                " Output a concise paragraph covering"
                                " key context, decisions, and user information."
                                " Write in third person."
                            ),
                        ),
                        ChatMessage(role="user", content=prompt),
                    ]
                ),
            )
            if response.content:
                await self._archive_memory(response.content)
                summary = build_summary_message(response.content)
                self._memory.apply_compression(summary)
        except Exception:
            pass

    async def _archive_memory(self, text: str) -> None:
        try:
            ensure_embedding()
            emb = await get_embedding(text)
            doc_id = f"mem_{int(__import__('time').time() * 1000)}"
            ts = __import__("datetime").datetime.now().isoformat()
            await add_chunks(
                self.id,
                [
                    {
                        "doc_id": doc_id,
                        "title": f"Memory {ts[:10]}",
                        "source": "memory",
                        "text": text,
                        "embedding": emb,
                        "metadata": {"type": "memory", "session": self._memory.session_id, "timestamp": ts},
                    }
                ],
            )
            logger.info("[MEMORY] Archived at %s", ts)
        except Exception as exc:
            logger.warning("[MEMORY] Archive failed: %s", exc)

    async def _snapshot_memory(self) -> None:
        messages = self._memory.get_messages()
        non_system = [m for m in messages if m.role != "system"]
        if len(non_system) < 2:
            return
        recent = non_system[-4:]
        summary = " | ".join(f"{m.role}: {m.content[:200]}" for m in recent if m.content)
        try:
            ensure_embedding()
            emb = await get_embedding(summary)
            ts = __import__("datetime").datetime.now().isoformat()
            doc_id = f"snap_{int(__import__('time').time() * 1000)}"
            await add_chunks(
                self.id,
                [
                    {
                        "doc_id": doc_id,
                        "title": f"Session {ts[:10]}",
                        "source": "conversation",
                        "text": summary,
                        "embedding": emb,
                        "metadata": {
                            "type": "memory",
                            "session": self._memory.session_id,
                            "timestamp": ts,
                        },
                    }
                ],
            )
            logger.info("[MEMORY] Snapshot saved (%d messages)", len(non_system))
        except Exception as exc:
            logger.warning("[MEMORY] Snapshot failed: %s", exc)

    async def _recall_memories(self, message: str) -> str:
        try:
            ensure_embedding()
            emb = await get_embedding(message)
            results = await search_similar(
                self.id,
                emb,
                message,
                SearchOptions(top_k=3, metadata_filter={"type": "memory"}),
            )
            if not results:
                return ""
            parts = []
            for r in results:
                if r.score < 0.2:
                    continue
                ts = r.chunk.metadata.get("timestamp", "")
                time_label = ts[:16] if ts else "unknown time"
                parts.append(f"[{time_label}] {r.chunk.text[:200]}")
            return "\n\n".join(parts)
        except Exception as exc:
            logger.warning("[MEMORY] Recall failed: %s", exc)
            return ""

    async def _execute_spawn_specialist(self, args: dict, current_depth: int = 0) -> str:
        try:
            sub_id = await self._dispatcher.create_sub_agent(
                self.id,
                {
                    "name": args["name"],
                    "soul": args["soul"],
                    "model": args["model"],
                },
            )
            return await self._dispatcher.dispatch(sub_id, args["task"], current_depth + 1)
        except Exception as e:
            return f"CRITICAL_ERROR: Failed to spawn specialist: {e}"

    async def _execute_spawn_swarm(self, args: dict, current_depth: int = 0) -> str:
        agents = args.get("agents", [])
        if not agents or len(agents) < 2:
            return "ERROR: Swarm needs at least 2 agents."
        if len(agents) > 5:
            agents = agents[:5]

        try:

            async def _run_agent(spec: dict) -> tuple[str, str]:
                sub_id = await self._dispatcher.create_sub_agent(
                    self.id,
                    {"name": spec["name"], "soul": spec["soul"], "model": ""},
                )
                result = await self._dispatcher.dispatch(sub_id, spec["task"], current_depth + 1)
                return (spec["name"], result)

            results = await asyncio.gather(*[_run_agent(a) for a in agents], return_exceptions=True)

            parts = []
            for r in results:
                if isinstance(r, tuple):
                    name, text = r
                    parts.append(f"## {name}\n{text}")
                elif isinstance(r, Exception):
                    parts.append(f"## Error\n{r}")

            merged = "\n\n".join(parts)

            # Synthesize final response using the main agent's LLM
            synthesis_prompt = (
                f"Task: {args.get('task', '')}\n\n"
                f"Responses from {len(agents)} specialists:\n\n{merged}\n\n"
                "Synthesize these into a coherent, concise final answer."
            )
            synthesis = await call_with_fallback(
                self._think_providers,
                lambda p: p.generate(
                    [
                        ChatMessage(
                            role="system",
                            content="You merge multiple expert analyses into one clear answer.",
                        ),
                        ChatMessage(role="user", content=synthesis_prompt),
                    ]
                ),
            )
            return synthesis.content or merged
        except Exception as e:
            return f"SWARM_ERROR: {e}"

    async def _evolve_soul(self) -> None:
        """Analyze recent conversations and improve SOUL.md."""
        messages = self._memory.get_messages()
        user_msgs = [m for m in messages if m.role == "user"]
        if len(user_msgs) < 10:
            return

        recent = messages[-30:]
        conversation = "\n".join(f"{m.role}: {m.content[:300]}" for m in recent if m.content and m.role != "system")

        try:
            response = await call_with_fallback(
                self._think_providers,
                lambda p: p.generate(
                    [
                        ChatMessage(
                            role="system",
                            content=(
                                "You analyze conversations to improve an AI assistant's SOUL.md"
                                " (personality file). Based on the recent chat, suggest 2-3 specific"
                                " improvements to the assistant's behavior, tone, or capabilities."
                                " Output ONLY the suggested improvements as bullet points."
                            ),
                        ),
                        ChatMessage(role="user", content=f"Recent conversation:\n\n{conversation[:2000]}"),
                    ]
                ),
            )
            if not response.content:
                return

            soul_path = Path("config") / self.id / "SOUL.md"
            if not soul_path.exists():
                return

            # Read current SOUL
            current = soul_path.read_text("utf-8")

            # Only append if suggestions are non-trivial
            if len(response.content.strip()) < 50:
                logger.info("[SOUL] Skipped — suggestions too short")
                return

            # Backup
            (Path("config") / self.id / "SOUL.md.bak").write_text(current, encoding="utf-8")

            # Keep only last 3 auto-evolution sections (remove old ones)
            import re as _re
            sections = _re.split(r"\n## Auto-Evolution \(", current)
            if len(sections) > 4:
                sections = sections[:1] + sections[-(3):]
                current = "## Auto-Evolution (".join(sections)

            # Append
            with soul_path.open("w", encoding="utf-8") as f:
                f.write(current)
                f.write(f"\n\n## Auto-Evolution ({__import__('datetime').datetime.now().strftime('%Y-%m-%d')})\n")
                f.write(f"{response.content}\n")

            logger.info("[SOUL] Evolved %s", self.id)
        except Exception as e:
            logger.warning("[SOUL] Evolution failed: %s", e)
