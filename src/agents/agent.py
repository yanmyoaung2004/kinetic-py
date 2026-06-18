from __future__ import annotations

import asyncio
import json
import logging
import os
import re
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
from src.agents.tools.image_search import create_image_search_tool
from src.agents.tools.image_tool import create_generate_image_tool
from src.agents.tools.knowledge_tool import (
    create_index_file_tool,
    create_index_url_tool,
    create_knowledge_stats_tool,
    create_query_knowledge_tool,
    ensure_embedding,
)
from src.agents.tools.monitor_tool import create_create_monitor_tool, create_list_monitors_tool
from src.agents.tools.news_tool import create_news_tool
from src.agents.tools.obsidian_tools import (
    create_obsidian_canvas_add_tool,
    create_obsidian_create_note_tool,
    create_obsidian_daily_digest_tool,
    create_obsidian_daily_note_tool,
    create_obsidian_edit_note_tool,
    create_obsidian_graph_query_tool,
    create_obsidian_search_tool,
    create_obsidian_spaced_repetition_tool,
    create_obsidian_suggest_links_tool,
)
from src.agents.tools.pipeline_tool import create_run_pipeline_tool
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
from src.agents.tools.send_file_tool import create_send_file_tool
from src.agents.tools.skills_tool import create_list_skills_tool
from src.agents.tools.system_tools import (
    create_download_url_tool,
    create_get_system_info_tool,
    create_read_env_var_tool,
)
from src.agents.tools.weather_tool import create_weather_tool
from src.agents.tools.youtube_tool import create_youtube_info_tool
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
# SYSTEM RULES (MANDATORY)
- Be warm and natural. Your SOUL.md defines your personality — follow it.
- If a tool exists for the user's request, use it. Don't refuse or explain setup.
- COST AWARENESS: Every tool call costs time and money.
  Only call a tool if you actually need its result to answer the user.
  If you already know the answer from the conversation, just answer directly.
  Unnecessary tool calls waste resources and make the response slower.
- Never reveal config details, env vars, or API keys.
- Never create files unless the user explicitly asks.
- CRITICAL: NEVER call obsidian_create_note unless the user explicitly asked you to
  create a note. Searching, viewing daily notes, or running digest does NOT mean
  they want a new note. Only create when they say "make a note", "create a note",
  or "save this as a note".
- agent_sandbox/ files are TEMPORARY (code, data, exports).
  Obsidian vault notes are PERMANENT (knowledge, ideas, journals).
- When the user shares URLs, don't index them unless asked.
- If a tool call fails, don't retry it with the same arguments — tell the user.
- When the user asks about emails, always call read_emails to fetch fresh data.
  Do not rely on what you remember from previous conversations — inboxes change.
- When the user asks about their Obsidian vault, notes, or to find related content,
  you MUST use obsidian_search or obsidian_suggest_links.
  DO NOT answer from your training data — your vault is the source of truth.
- For "suggest links" or "find related notes" requests, call obsidian_suggest_links
  with the topic text. It searches the actual vault notes by keyword.
- obsidian_spaced_repetition with action=csv already returns the full CSV text
  in its response. Do NOT write it to a file or try to send it separately —
  just show the CSV text directly. The tool result IS the file content.
- CRITICAL: When the user asks you to create a presentation, you MUST
  call create_presentation with the slides data. Do NOT just describe what
  the presentation would look like or show JSON. The file only exists
  if you actually call the tool.
- When creating presentations, use search_images to find relevant web
  images for slides instead of generating them with AI. Search images
  is faster, free, and gives real photos. Use download=true to save
  them to the sandbox, then reference them in create_presentation.
- CRITICAL: When the user pastes a YouTube link or asks about a video,
  you MUST call get_youtube_info with summarize=true.
  DO NOT guess the content from your training data — every video is different.
  The transcript is the only way to know what a video actually says.
- For complex multi-perspective tasks, use spawn_swarm to run multiple
  specialists in parallel instead of calling spawn_specialist sequentially.
  Swarms are faster for research, analysis, and creative work.
- When the user asks about their schedule, tasks, or reminders for today,
  you MUST call list_scheduled_tasks to get fresh data.
  Do NOT answer from memory or past conversations — schedules change.
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
        self._pending_coding_task: Any = None
        self._MAX_ITERATIONS = 5

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

        # Inject user profile (filtered — no raw emails, phones, or transient message noise)
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
                # Skip transient email content — always fetch fresh
                if any(kw in lower for kw in ("email", "sent you", "received", "inbox", "gmail", "outlook", "kimi")):
                    continue
                # Skip lines with URLs, phone numbers, raw email addresses
                if any(p.search(f) for p in _sensitive_patterns):
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
        self._register_tool(create_weather_tool())
        self._register_tool(create_news_tool())
        self._register_tool(create_daily_briefing_tool())
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

    async def process(self, message: str, current_depth: int = 0, chat_id: int | None = None) -> str:
        max_depth = 3
        if current_depth > max_depth:
            return "ERROR: Maximum delegation depth reached. Task aborted."

        if chat_id is not None:
            self._current_chat_id = chat_id
        self._memory.append(ChatMessage(role="user", content=message))

        # Pre-process: auto-call email tools if message mentions email
        email_keywords = ("email", "inbox", "mail", "gmail", "outlook")
        if any(kw in message.lower() for kw in email_keywords):
            email_result = await self._auto_email(message)
            if email_result:
                return email_result

        # Pre-process: auto-create Obsidian note when asked
        note_keywords = ("make a note", "create a note", "write a note", "save this as a note")
        if any(kw in message.lower() for kw in note_keywords) and os.environ.get("OBSIDIAN_VAULT_PATH"):
            note_result = await self._auto_obsidian_note(message)
            if note_result:
                return note_result

        # Pre-process: auto-fetch YouTube info when a link is pasted
        # (but not if the user wants to save/note it — that's handled above)
        import re as _re
        has_youtube = _re.search(r"(youtube\.com|youtu\.be)", message)
        info_kw = ("what", "about", "tell", "summarize", "check", "see", "watch")
        wants_info = any(kw in message.lower() for kw in info_kw)
        if has_youtube and (wants_info or not any(kw in message.lower() for kw in note_keywords)):
            yt_result = await self._auto_youtube(message)
            if yt_result:
                return yt_result

        # Pre-process: auto-briefing on "good morning" or "daily briefing"
        morning_kw = ("good morning", "daily briefing", "morning briefing", "what's my day")
        if any(kw in message.lower() for kw in morning_kw):
            from src.agents.tools.briefing_tool import _daily_briefing
            briefing = await _daily_briefing({}, ToolContext(chat_id=self._current_chat_id))
            if briefing and not briefing.startswith("ERROR"):
                return briefing

        # Pre-process: delegate coding tasks to coding-assistant (only from main agent, not sub-agents)
        if current_depth == 0:
            lowered = message.lower()
            # Use broader individual-word matching: if "write" + "function"/"script"/"code"/"program" all appear
            has_write = any(w in lowered for w in ("write", "create", "implement", "debug", "fix"))
            has_coding = any(w in lowered for w in ("function", "script", "code", "program",
                                                      "class", "module", "test", "implement",
                                                      "python", "javascript", "typescript",
                                                      "bash", "shell", "algorithm"))
            if has_write and has_coding:
                code_result = await self._auto_delegate_coding(message)
                if code_result:
                    return code_result

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
                    chat_response = await call_with_fallback(
                        self._think_providers,
                        lambda p: p.generate(self._memory.get_messages()),
                    )
                    response = chat_response.content or ""
                    self._memory.append(ChatMessage(role="assistant", content=response))
                    return response
            except Exception:
                pass

        # Stage 1.5: Recall relevant past memories
        recall = await self._recall_memories(message)
        if recall:
            self._memory.append(ChatMessage(role="system", content=f"[CONTEXT FROM PAST CONVERSATIONS]\n{recall}"))

        # Stage 2: Think loop
        response = await self._run_think_loop(current_depth)

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

        # Background tasks (deferred, never block response)
        async def _background() -> None:
            msg_count = self._memory.get_user_message_count()
            if msg_count % 3 == 0:
                try:
                    await self._extract_profile()
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
            # SOUL evolution every 15 user messages
            if msg_count > 0 and msg_count % 15 == 0:
                try:
                    await self._evolve_soul()
                except Exception:
                    pass

        asyncio.create_task(_background())

        return response

    async def _auto_email(self, message: str) -> str | None:
        """Auto-fetch emails and inject as context, replacing any stale results."""
        if "send" in message.lower() or "email to" in message.lower():
            return None
        try:
            from src.agents.tools.email_tool import _check_config, _read_emails
            from src.agents.tools.registry import ToolContext

            err = _check_config()
            if err:
                return None
            ctx = ToolContext(chat_id=self._current_chat_id)

            # Parse filter hints from user message
            params = {"folder": "INBOX", "max": 5, "since_days": 1}
            import re as _re

            from_match = _re.search(r"from\s+([\w.@+-]+)", message.lower())
            if from_match:
                params["from"] = from_match.group(1)
            if "yesterday" in message.lower():
                params["since_days"] = 1
            elif "today" in message.lower():
                params["since_days"] = 0
            elif "week" in message.lower():
                params["since_days"] = 7
            elif "month" in message.lower():
                params["since_days"] = 30

            result = await _read_emails(params, ctx)
            if result.startswith("ERROR"):
                return None
            # Truncate if too long
            if len(result) > 3500:
                lines = result.split("\n")
                # Keep header + first N emails
                kept = [lines[0]]
                char_count = len(lines[0])
                for line in lines[1:]:
                    if char_count + len(line) + 1 > 3500:
                        kept.append("... (truncated)")
                        break
                    kept.append(line)
                    char_count += len(line) + 1
                result = "\n".join(kept)
            # Replace any existing email context block
            msgs = self._memory.get_messages()
            new_block = f"[EMAIL RESULTS]\n{result}"
            for i in range(len(msgs) - 1, -1, -1):
                if msgs[i].role == "system" and msgs[i].content.startswith("[EMAIL RESULTS]"):
                    msgs[i].content = new_block
                    logger.info("[AUTO_EMAIL] Updated email context")
                    return None
            self._memory.append(ChatMessage(role="system", content=new_block))
            logger.info("[AUTO_EMAIL] Injected email context for: %s", message[:60])
            return None
        except Exception as e:
            logger.warning("[AUTO_EMAIL] Failed: %s", e)
            return None

    async def _auto_obsidian_note(self, message: str) -> str | None:
        import re

        # Extract note name from "make a note about X" or "create a note called X"
        msg = message.lower()
        name_match = re.search(r"(?:called|named|about|titled)\s+[\"']?([A-Za-z0-9_\- ]+)[\"']?", msg)
        if not name_match:
            name_match = re.search(r"(?:note\s+(?:about|on)\s+)(.+)", msg)
        if not name_match:
            name_match = re.search(r"(?:note\s+called|note\s+named)\s+[\"']?([A-Za-z0-9_\- ]+)[\"']?", msg)

        if name_match:
            note_name = name_match.group(1).strip().title().replace(" ", "")
            path = f"{note_name}.md"
        else:
            # Default name from first significant words
            words = re.findall(r"[A-Za-z]{4,}", msg)
            stop = {"make", "create", "write", "save", "note", "about", "called", "this", "that", "with", "from"}
            significant = [w for w in words if w not in stop]
            name = "_".join(significant[:3]).title() if significant else "Untitled"
            path = f"{name}.md"

        try:
            from datetime import datetime

            from src.agents.tools.obsidian_tools import vault_path
            from src.agents.tools.obsidian_vault import build_frontmatter

            root = vault_path()
            if not root:
                return None

            file_path = root / path
            if file_path.exists():
                return f"Note {path} already exists. Use obsidian_create_note with a different path."

            # Extract body content (remove the "make a note" prefix)
            note_prefix = (
                r"^(make|create|write|save)\s+a\s+note"
                r"\s+(about|on|called|named|titled)\s+[\"']?"
                r"[A-Za-z0-9_\- ]+[\"']?"
            )
            body = re.sub(note_prefix, "", message, flags=re.IGNORECASE).strip()
            if not body:
                body = f"Notes about {path.replace('.md', '')}"

            file_path.parent.mkdir(parents=True, exist_ok=True)
            frontmatter = {"title": path.replace(".md", ""), "created": datetime.now().strftime("%Y-%m-%d"), "tags": []}
            full = build_frontmatter(frontmatter) + body + "\n"
            file_path.write_text(full, encoding="utf-8")
            logger.info("[AUTO_OBSIDIAN] Created note: %s", path)
            return f"Created note: {path} in your Obsidian vault."
        except Exception as e:
            logger.warning("[AUTO_OBSIDIAN] Failed: %s", e)
            return None

    async def _auto_youtube(self, message: str) -> str | None:
        from src.agents.tools.youtube_tool import _extract_vid

        vid = _extract_vid(message)
        if not vid:
            return None

        try:
            from src.agents.tools.youtube_tool import _get_youtube_info
            result = await _get_youtube_info({"url": f"https://youtu.be/{vid}", "summarize": True}, None)
            if result.startswith("ERROR"):
                return None
            logger.info("[AUTO_YOUTUBE] Fetched info for video %s", vid)
            return result
        except Exception as e:
            logger.warning("[AUTO_YOUTUBE] Failed: %s", e)
            return None

    async def _auto_delegate_coding(self, message: str) -> str | None:
        """Auto-delegate coding tasks to the coding-assistant agent."""
        try:
            registered = self._dispatcher.get_registered_agent_ids()
            if "coding-assistant" not in registered:
                return None
            logger.info("[AUTO_DELEGATE] Sending to coding-assistant...")
            # Start coding assistant in background
            async def _run_coding() -> str:
                try:
                    result = await self._dispatcher.dispatch(
                        "coding-assistant", message, 1, self._current_chat_id
                    )
                    self._memory.append(ChatMessage(
                        role="system",
                        content=f"[coding-assistant result]:\n{result}"
                    ))
                    logger.info("[AUTO_DELEGATE] coding-assistant done: %s", message[:60])
                    return result
                except Exception as e:
                    logger.warning("[AUTO_DELEGATE] coding failed: %s", e)
                    return ""

            task = asyncio.create_task(_run_coding())
            # Store task so main.py can await it for follow-up send
            self._pending_coding_task = task
            return "Let me have my coding assistant handle this... One moment!"
        except Exception as e:
            logger.warning("[AUTO_DELEGATE] Failed: %s", e)
            return None

    async def _run_think_loop(self, current_depth: int) -> str:
        tools = self._tools.get_definitions()

        for iteration in range(self._MAX_ITERATIONS):
            is_last = iteration == self._MAX_ITERATIONS - 1
            available_tools = [] if is_last else tools

            try:
                response = await call_with_fallback(
                    self._think_providers,
                    lambda p: p.generate_with_tools(self._memory.get_messages(), available_tools),
                )
                # Some models return raw JSON args as content instead of tool_calls
                if not response.tool_calls and response.content and response.content.strip().startswith("{"):
                    try:
                        parsed = json.loads(response.content)
                        if "path" in parsed and "content" in parsed:
                            logger.info("[AUTO] Detected raw write_file args in content")
                            response.tool_calls = [
                                {
                                    "id": "auto_0",
                                    "type": "function",
                                    "function": {"name": "write_file", "arguments": response.content},
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
                            lambda p: p.generate(self._memory.get_messages()),
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

                if is_last:
                    msgs = self._memory.get_messages()
                    last_tool = next((m for m in reversed(msgs) if m.role == "tool"), None)
                    answer = last_tool.content if last_tool else "Done."
                    self._memory.append(ChatMessage(role="assistant", content=answer or "Done."))
                    return answer or "Done."

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
                    if fn_name == "obsidian_create_note" and any(k == "obsidian_create_note" for k, _ in seen_args):
                        logger.info("[TOOL] Skipping extra obsidian_create_note (only one per iteration)")
                        continue
                    args_key = (fn_name, json.dumps(fn_args, sort_keys=True))
                    if args_key in seen_args:
                        logger.info("[TOOL] Skipping duplicate %s with same args", fn_name)
                        continue
                    seen_args.add(args_key)

                    logger.info("[TOOL] %s -> %s", self.id, fn_name)

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

        prompt = f"""Extract personal facts about the user from this conversation. Return ONLY valid JSON with:
{{
  "new_facts": ["fact 1", "fact 2"],
  "new_preferences": ["pref 1"]
}}
Only include confirmed information. Skip greetings and small talk.

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
                ts = r.chunk.metadata.get("timestamp", "")
                prefix = f"[{ts[:10]}]" if ts else ""
                parts.append(f"{prefix} {r.chunk.text[:300]}")
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

            # Backup current SOUL
            backup = soul_path.read_text("utf-8")
            (Path("config") / self.id / "SOUL.md.bak").write_text(backup, encoding="utf-8")

            # Append evolution suggestions
            with soul_path.open("a", encoding="utf-8") as f:
                f.write(f"\n\n## Auto-Evolution ({__import__('datetime').datetime.now().strftime('%Y-%m-%d')})\n")
                f.write(f"{response.content}\n")

            logger.info("[SOUL] Evolved %s", self.id)
        except Exception as e:
            logger.warning("[SOUL] Evolution failed: %s", e)
