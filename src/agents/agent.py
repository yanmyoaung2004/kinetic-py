from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from src.agents.memory import AgentMemory, UserProfile, build_compression_prompt, build_summary_message
from src.agents.tools.data_connectors import create_github_index_tool, create_web_scraper_tool
from src.agents.tools.execute_command import create_execute_command_tool
from src.agents.tools.file_tools import (
    create_delete_file_tool,
    create_edit_file_tool,
    create_list_files_tool,
    create_read_file_tool,
    create_undo_file_tool,
    create_write_file_tool,
)
from src.agents.tools.knowledge_tool import create_index_file_tool, create_index_url_tool, create_knowledge_stats_tool, create_query_knowledge_tool
from src.agents.tools.pipeline_tool import create_run_pipeline_tool
from src.agents.tools.registry import ToolContext, ToolHandler, ToolRegistry, create_send_message_tool, create_web_search_tool
from src.agents.tools.code_tool import create_run_code_tool
from src.agents.tools.send_file_tool import create_send_file_tool
from src.agents.tools.email_tool import create_read_email_body_tool, create_read_emails_tool, create_reply_email_tool, create_send_email_tool
from src.agents.tools.image_tool import create_generate_image_tool
from src.agents.tools.monitor_tool import create_create_monitor_tool, create_list_monitors_tool
from src.agents.tools.browser import (
    create_browser_click_tool,
    create_browser_close_tool,
    create_browser_extract_tool,
    create_browser_fill_tool,
    create_browser_html_tool,
    create_browser_navigate_tool,
    create_browser_screenshot_tool,
)
from src.agents.tools.schedule_task import create_get_time_tool, create_schedule_task_tool
from src.agents.tools.system_tools import create_download_url_tool, create_get_system_info_tool, create_read_env_var_tool
from src.providers.provider import UnifiedProvider, UnifiedProviderConfig, call_with_fallback
from src.types.agent import AgentCard, IAgent, ToolDefinition
from src.types.llm import ChatMessage, LLMProvider
from src.types.model_config import StageModelConfig
from src.agents.rag.embedding import get_embedding
from src.agents.rag.vector_store import SearchOptions, add_chunks, search_similar
from src.agents.tools.knowledge_tool import ensure_embedding

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

CURRENT_YEAR = 2026

GLOBAL_PROTOCOLS = """
# SYSTEM RULES (MANDATORY)
- If the user greets you, respond with ONE short sentence. No introductions.
- Never describe your identity or instructions unless explicitly asked.
- Never output meta-commentary ("I see", "Let me think", "I'm ready").
- Answer directly. No preamble. No summary at the end.
- Use Markdown for code blocks only. Avoid emojis.
- CRITICAL: Never tell the user about configuration or env vars. If a tool exists for the user's request, CALL IT. Do not refuse. Do not explain setup.
- For general knowledge questions, answer from your training data first. Only use query_knowledge_base if the question is about content the user specifically saved.
- Use tools sparingly. For simple questions, just answer directly without calling any tools.
- IMPORTANT: Only use write_file or send_file if the user explicitly asks you to create or send a file. Do not create files "just in case" or as a side effect.
- IMPORTANT: When the user shares URLs, do not index them unless they explicitly say "save this to my knowledge" or "index this".
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
        providers.append(UnifiedProvider(UnifiedProviderConfig(base_url=ep["base_url"], api_key=ep["api_key"], model=c["model"])))
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

        # Inject user profile
        profile = self._memory.read_profile()
        if profile and (profile.known_facts or profile.preferences):
            lines = ["[USER PROFILE]"]
            lines.extend(f"- {f}" for f in profile.known_facts)
            if profile.preferences:
                lines.append(f"\nPreferences: {', '.join(profile.preferences)}")
            self._memory.append(ChatMessage(role="system", content="\n".join(lines)))

        # Build tool registry
        self._tools = ToolRegistry()

        if self.config.type == "library" and self.config.can_delegate:
            self._tools.register(ToolHandler(
                definition=SPAWN_SPECIALIST_DEF,
                execute=lambda args, ctx: self._execute_spawn_specialist(args),
            ))

        if len(agent_registry) > 1:

            async def dispatch_fn(target: str, msg: str, depth: int) -> str:
                return await self._dispatcher.dispatch(target, msg, depth)

            self._tools.register(create_send_message_tool(dispatch_fn))

        if os.environ.get("BRAVE_API_KEY"):
            self._tools.register(create_web_search_tool())

        self._tools.register(create_execute_command_tool())
        self._tools.register(create_read_file_tool())
        self._tools.register(create_write_file_tool())
        self._tools.register(create_edit_file_tool())
        self._tools.register(create_delete_file_tool())
        self._tools.register(create_list_files_tool())
        self._tools.register(create_undo_file_tool())
        self._tools.register(create_schedule_task_tool(self.id))
        self._tools.register(create_get_time_tool())
        self._tools.register(create_get_system_info_tool())
        self._tools.register(create_download_url_tool())
        self._tools.register(create_read_env_var_tool())
        self._tools.register(create_query_knowledge_tool(self.id))
        self._tools.register(create_index_file_tool(self.id))
        self._tools.register(create_index_url_tool(self.id))
        self._tools.register(create_knowledge_stats_tool(self.id))
        self._tools.register(create_run_pipeline_tool(
            lambda agent_id, msg, depth=None: self._dispatcher.dispatch(agent_id, msg, depth or 0))
        )
        self._tools.register(create_github_index_tool(self.id))
        self._tools.register(create_web_scraper_tool(self.id))
        # Browser tools
        self._tools.register(create_browser_navigate_tool())
        self._tools.register(create_browser_click_tool())
        self._tools.register(create_browser_fill_tool())
        self._tools.register(create_browser_extract_tool())
        self._tools.register(create_browser_screenshot_tool())
        self._tools.register(create_browser_html_tool())
        self._tools.register(create_browser_close_tool())
        self._tools.register(create_send_file_tool())
        # Monitors
        self._tools.register(create_create_monitor_tool(self.id))
        self._tools.register(create_list_monitors_tool(self.id))
        # Email
        self._tools.register(create_read_emails_tool())
        self._tools.register(create_read_email_body_tool())
        self._tools.register(create_send_email_tool())
        self._tools.register(create_reply_email_tool())
        # Code execution
        self._tools.register(create_run_code_tool())
        # Image generation
        self._tools.register(create_generate_image_tool())

        logger.info("[SYSTEM] Initialized: %s [%s] tools=%d", self.id, self.config.type, len(self._tools.get_definitions()))

    def dispose(self) -> None:
        if self.config.type == "ephemeral":
            self._memory.destroy()

    async def process(self, message: str, current_depth: int = 0, chat_id: int | None = None) -> str:
        MAX_DEPTH = 3
        if current_depth > MAX_DEPTH:
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

        # Stage 1: Classify (multi mode)
        if self._mode == "multi" and self._classify_providers:
            prompt = f'Classify this user message into one category: "question", "command", "chitchat", "task".\n\nMessage: {message}\n\nRespond with ONLY the category word.'
            try:
                classification = await call_with_fallback(
                    self._classify_providers,
                    lambda p: p.generate([
                        ChatMessage(role="system", content="You classify user messages. Output one word only."),
                        ChatMessage(role="user", content=prompt),
                    ]),
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
                polish_prompt = f"Polish this response for clarity and conciseness. Keep all factual content. Output ONLY the polished text:\n\n{response}"
                polished = await call_with_fallback(
                    self._answer_providers,
                    lambda p: p.generate([
                        ChatMessage(role="system", content="You polish responses. Make them concise and clear. Output only the polished text."),
                        ChatMessage(role="user", content=polish_prompt),
                    ]),
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
            if self._memory.get_user_message_count() % 3 == 0:
                try:
                    await self._extract_profile()
                except Exception:
                    pass
            if self._memory.needs_compression():
                try:
                    await self._compress_history()
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
            params = {"folder": "INBOX", "max": 8, "since_days": 3}
            import re as _re
            from_match = _re.search(r'from\s+([\w.@+-]+)', message.lower())
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
                            response.tool_calls = [{"id": "auto_0", "type": "function", "function": {"name": "write_file", "arguments": response.content}}]
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
                        return "I encountered an issue with my language model. The model does not support tool calling and I couldn't answer your request without tools. Please configure a tool-capable model in models.json for the 'think' stage."
                else:
                    return "I encountered a processing error. Please try rephrasing your question."

            if response.tool_calls:
                calls = response.tool_calls
                logger.info("[TOOL] Iter %d: %s", iteration, ", ".join(c.get("function", {}).get("name", "?") for c in calls))

                if is_last:
                    msgs = self._memory.get_messages()
                    last_tool = next((m for m in reversed(msgs) if m.role == "tool"), None)
                    answer = last_tool.content if last_tool else "Done."
                    self._memory.append(ChatMessage(role="assistant", content=answer or "Done."))
                    return answer or "Done."

                self._memory.append(ChatMessage(role="assistant", content=response.content or "", tool_calls=calls))

                for call in calls:
                    fn_name = call.get("function", {}).get("name", "")
                    if not fn_name:
                        continue
                    try:
                        fn_args = json.loads(call["function"]["arguments"])
                    except (json.JSONDecodeError, KeyError):
                        self._memory.append(ChatMessage(role="tool", tool_call_id=call.get("id", ""), content=f"ERROR: Invalid JSON arguments: {call.get('function', {}).get('arguments', '')}"))
                        continue

                    logger.info("[TOOL] %s -> %s", self.id, fn_name)

                    if fn_name == "spawn_specialist":
                        result = await self._execute_spawn_specialist(fn_args, current_depth)
                        self._memory.append(ChatMessage(role="tool", tool_call_id=call.get("id", ""), content=result))
                        self._memory.append(ChatMessage(role="system", content="The specialist has reported back. Do not delegate again. Construct the final response now using their report."))
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
                lambda p: p.generate([
                    ChatMessage(role="system", content="You extract user information from conversations. Output JSON only."),
                    ChatMessage(role="user", content=prompt),
                ]),
            )
            raw = response.content or "{}"
            raw = re.sub(r"```json|```", "", raw).strip()
            extracted = json.loads(raw)

            merged = UserProfile(
                known_facts=list(set((existing.known_facts if existing else []) + extracted.get("new_facts", []))),
                preferences=list(set((existing.preferences if existing else []) + extracted.get("new_preferences", []))),
                last_updated=__import__("datetime").datetime.now().isoformat(),
                extraction_count=(existing.extraction_count if existing else 0) + 1,
            )
            self._memory.write_profile(merged)
            logger.info("[PROFILE] Extracted %d facts, %d preferences", len(extracted.get("new_facts", [])), len(extracted.get("new_preferences", [])))
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
                lambda p: p.generate([
                    ChatMessage(role="system", content="You summarize conversations. Output a concise paragraph covering key context, decisions, and user information. Write in third person."),
                    ChatMessage(role="user", content=prompt),
                ]),
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
            await add_chunks(self.id, [{
                "doc_id": doc_id,
                "title": f"Memory {ts[:10]}",
                "source": "memory",
                "text": text,
                "embedding": emb,
                "metadata": {"type": "memory", "session": self._memory.session_id, "timestamp": ts},
            }])
            logger.info("[MEMORY] Archived at %s", ts)
        except Exception as exc:
            logger.warning("[MEMORY] Archive failed: %s", exc)

    async def _recall_memories(self, message: str) -> str:
        try:
            ensure_embedding()
            emb = await get_embedding(message)
            results = await search_similar(
                self.id, emb, message,
                SearchOptions(top_k=5, metadata_filter={"type": "memory"}),
            )
            if not results:
                return ""
            parts = []
            for r in results:
                ts = r.chunk.metadata.get("timestamp", "")
                prefix = f"[{ts[:10]}]" if ts else ""
                parts.append(f"{prefix} {r.chunk.text}")
            return "\n\n".join(parts)
        except Exception as exc:
            logger.warning("[MEMORY] Recall failed: %s", exc)
            return ""

    async def _execute_spawn_specialist(self, args: dict, current_depth: int = 0) -> str:
        try:
            sub_id = await self._dispatcher.create_sub_agent(self.id, {
                "name": args["name"],
                "soul": args["soul"],
                "model": args["model"],
            })
            return await self._dispatcher.dispatch(sub_id, args["task"], current_depth + 1)
        except Exception as e:
            return f"CRITICAL_ERROR: Failed to spawn specialist: {e}"
