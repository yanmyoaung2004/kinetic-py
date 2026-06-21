from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

import dotenv
import structlog
from telegram import Chat, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from src.agents.orchestrator import KinetiCDispatcher
from src.agents.tools.send_file_tool import get_pending_files
from src.config.loader import load_model_config, validate_endpoints
from src.utils.file_reader import get_type_label, read_file

_sent_content_hashes: set[int] = set()

dotenv.load_dotenv()

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
for noisy in ("httpx", "httpcore", "telegram", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logger = structlog.get_logger("kinetic")
_shutting_down: asyncio.Event | None = None

MODELS_CONFIG = os.environ.get("MODELS_CONFIG", "config/models.json")
AGENTS_CONFIG = os.environ.get("AGENTS_CONFIG", "config/agents.json")
AGENT_TARGET = os.environ.get("AGENT_TARGET", "main")
API_PORT = int(os.environ.get("API_PORT", "18789"))

ALLOWLIST_STR = os.environ.get("TELEGRAM_ALLOWLIST", "")
ALLOWLIST = [int(s.strip()) for s in ALLOWLIST_STR.split(",") if s.strip()] if ALLOWLIST_STR else []

COMMANDS_HELP = """
/help — Show this message
/models — Show current stage config
/models set think <provider> [model] — Switch provider at runtime
/models reset think — Reset to models.json default
/providers — List available provider endpoints
/status — Bot uptime, active agents, memory info
/profile — Show what I know about you
/profile clear — Reset my knowledge about you
/reset — Clear current conversation's history
/session — Show current session
/session new <name> — Start a fresh conversation session
/session <name> — Switch to an existing session
/session list — List all sessions
/task list — Show scheduled tasks
/task remove <id> — Remove a scheduled task
/knowledge — Show knowledge base stats
/knowledge list — List indexed documents
/knowledge remove <id> — Remove a document from the index
/search <query> — Search conversation history
/perfect — Learn from the last successful workflow
/forget <trigger> — Forget a learned workflow
/workflows — Show all learned workflows
"""


def _convert_markdown(text: str) -> str:
    """Convert Markdown to Telegram HTML format safely — no formatting inside code."""
    import html
    import re

    # Handle <br> tags BEFORE html.escape (they'd become &lt;br&gt; otherwise)
    text = text.replace("<br>", "\n").replace("<br/>", "\n")

    # Escape HTML entities
    text = html.escape(text)

    # Protect code blocks from inline formatting
    placeholders: dict[str, str] = {}

    def _protect(m: re.Match) -> str:
        key = f"\x00CODE{len(placeholders)}\x00"
        placeholders[key] = m.group(0)
        return key

    # Block code ```...```
    text = re.sub(r"```[\s\S]*?```", _protect, text)
    # Inline code `...`
    text = re.sub(r"`[^`]+`", _protect, text)

    # Convert headings to bold (### Title → <b>Title</b>)
    text = re.sub(r"^#{1,6}\s+(.+?)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    # Convert horizontal rules (---) to empty line
    text = re.sub(r"\n-{3,}\n", "\n\n", text)
    # Convert markdown tables to indented lines (| a | b | → \n • a: b)
    text = re.sub(r"^\|(.+)\|$", lambda m: "  • " + " — ".join(
        c.strip() for c in m.group(1).split("|") if c.strip()
    ), text, flags=re.MULTILINE)
    # Remove separator lines in tables (|---|---|)
    text = re.sub(r"^  • [\s\-:]+\s*$", "", text, flags=re.MULTILINE)

    # Apply inline formatting on non-code text only
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"__(.+?)__", r"<u>\1</u>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # Restore protected code blocks
    for key, original in placeholders.items():
        code_html = original
        # Convert code markers to HTML tags
        code_html = re.sub(r"```([\s\S]*?)```", r"<pre>\1</pre>", code_html)
        code_html = re.sub(r"`([^`]+)`", r"<code>\1</code>", code_html)
        text = text.replace(key, code_html)

    # Newlines
    text = re.sub(r"\n{2,}", "\n\n", text)

    # Safety: if HTML is malformed (unmatched tags), fall back to plain text
    if text.count("<code>") != text.count("</code>") or text.count("<pre>") != text.count("</pre>"):
        return html.unescape(re.sub(r"<[^>]+>", "", text))
    if text.count("<b>") != text.count("</b>") or text.count("<i>") != text.count("</i>"):
        return html.unescape(re.sub(r"<[^>]+>", "", text))

    return text


async def _send_long_message(msg: Any, text: str, parse_mode: str | None = "HTML") -> None:
    """Split long messages and send in chunks to avoid Telegram's 4096-char limit."""
    import html as _html
    import re as _re

    max_len = 4000
    if len(text) <= max_len:
        try:
            await msg.reply_text(text, parse_mode=parse_mode)
        except Exception:
            plain = _html.unescape(_re.sub(r"<[^>]+>", "", text))
            await msg.reply_text(plain)
        return
    while text:
        chunk = text[:max_len]
        if len(text) > max_len:
            break_at = chunk.rfind("\n")
            if break_at > max_len // 2:
                chunk = chunk[:break_at]
        try:
            await msg.reply_text(chunk, parse_mode=parse_mode)
        except Exception:
            plain = _html.unescape(_re.sub(r"<[^>]+>", "", chunk))
            await msg.reply_text(plain)
        text = text[len(chunk):].lstrip()


async def _typing_indicator(chat: Chat, task: asyncio.Task) -> None:
    """Keep the typing indicator alive until the task finishes."""
    while not task.done():
        try:
            await chat.send_action("typing")
        except Exception:
            pass
        await asyncio.sleep(4)


class KinetiCBot:
    def __init__(self) -> None:
        logger.info("[MAIN] Loading config...")
        model_config, endpoints, embedding_config = load_model_config(MODELS_CONFIG)

        if embedding_config:
            from src.agents.tools.knowledge_tool import init_knowledge_base

            init_knowledge_base(
                embedding_config.base_url,
                embedding_config.api_key,
                embedding_config.model,
                {"extraBody": embedding_config.extra_body, "encodingFormat": embedding_config.encoding_format},
            )
            logger.info("[RAG] Embedding ready", model=embedding_config.model, url=embedding_config.base_url)
        else:
            logger.info("[RAG] No embedding config. Add 'embedding' to models.json for knowledge base features.")

        self._validate_coro = validate_endpoints(endpoints)
        self._app: Application | None = None

        self.dispatcher = KinetiCDispatcher(model_config, endpoints)
        self.dispatcher.load_and_register_agent(AGENTS_CONFIG)
        self._agent_target = AGENT_TARGET
        self._start_time = __import__("time").time()
        # Multi-user tracking
        self._user_last_active: dict[int, float] = {}
        self._known_users: set[int] = set()
        # Load persisted scheduler state
        self._meta_path = Path("agents_workspace") / "_scheduler_meta.json"
        self._meta_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_briefing_date = ""
        self._warned: set[str] = set()
        if self._meta_path.exists():
            try:
                meta = json.loads(self._meta_path.read_text("utf-8"))
                self._last_briefing_date = meta.get("briefing_date", "")
                self._warned = set(meta.get("warned", []))
                self._known_users = set(meta.get("known_users", []))
            except Exception:
                pass

    async def handle_command(self, update: Update, context: Any = None) -> None:
        msg = update.message
        assert msg is not None
        text = msg.text or ""
        if not text:
            return

        parts = text.split()
        cmd = parts[0].lower()

        if cmd in ("/start", "/help"):
            await msg.reply_text(COMMANDS_HELP)
            return

        if cmd == "/models" and len(parts) >= 4 and parts[1] == "set" and parts[2] == "think":
            provider = parts[3]
            model = " ".join(parts[4:]) if len(parts) > 4 else None
            result = self.dispatcher.set_stage_override("think", provider, model)
            await msg.reply_text(result)
            return

        if cmd == "/models" and len(parts) >= 3 and parts[1] == "reset" and parts[2] == "think":
            result = self.dispatcher.clear_stage_override("think")
            await msg.reply_text(result)
            return

        if cmd == "/models":
            config_text = self.dispatcher.get_active_config()
            reply = f"Current stage configuration:\n{config_text}"
            reply += "\n\nUse /models set think <provider> [model] to switch at runtime."
            await msg.reply_text(reply)
            return

        if cmd == "/providers":
            await msg.reply_text("Available providers:\n" + self.dispatcher.get_provider_list())
            return

        if cmd == "/status":
            await msg.reply_text(
                f"Uptime: {self.dispatcher.get_uptime()}\n"
                f"Active agents: {self.dispatcher.get_agent_count()}\n"
                f"Dispatch target: {self._agent_target}"
            )
            return

        if cmd == "/profile" and len(parts) >= 2 and parts[1] == "clear":
            profile_path = Path("agents_workspace") / self._agent_target / "profile.json"
            if profile_path.exists():
                profile_path.unlink()
                await msg.reply_text("✓ Profile cleared. I'll re-learn from our next conversations.")
            else:
                await msg.reply_text("No profile to clear.")
            return

        if cmd == "/profile":
            import json as _json

            profile_path = Path("agents_workspace") / self._agent_target / "profile.json"
            if profile_path.exists():
                profile = _json.loads(profile_path.read_text("utf-8"))
                facts = "\n".join(f"• {f}" for f in profile.get("known_facts", [])) or "None yet"
                prefs = ", ".join(profile.get("preferences", [])) or "None yet"
                await msg.reply_text(f"Known facts:\n{facts}\n\nPreferences: {prefs}")
            else:
                await msg.reply_text("No profile extracted yet. Send me a few messages and I'll learn about you.")
            return

        if cmd == "/reset":
            from src.agents.memory import AgentMemory

            session_id = self.dispatcher.get_active_session()
            mem = AgentMemory(self._agent_target, "agents_workspace", session_id=session_id)
            mem.reset()
            await msg.reply_text(f"✓ Session '{session_id}' cleared.")
            return

        if cmd == "/session" and len(parts) >= 3 and parts[1] == "new":
            name = "-".join(parts[2:])
            import re as _re

            name = _re.sub(r"[^a-zA-Z0-9_-]", "_", name)
            result = self.dispatcher.set_session(name)
            await msg.reply_text(result)
            return

        if cmd == "/session" and len(parts) >= 2 and parts[1] == "list":
            from src.agents.memory import AgentMemory

            sessions = AgentMemory.list_sessions(self._agent_target, "agents_workspace")
            active = self.dispatcher.get_active_session()
            session_list = (
                "\n".join(f"  {s}{' ← active' if s == active else ''}" for s in sessions)
                if sessions
                else "  (no additional sessions)"
            )
            await msg.reply_text(f"Sessions:\n{session_list}\n\nActive: {active}")
            return

        if cmd == "/session" and len(parts) >= 2:
            name = parts[1]
            from src.agents.memory import AgentMemory

            sessions = AgentMemory.list_sessions(self._agent_target, "agents_workspace")
            if name != "default" and name not in sessions:
                await msg.reply_text(f"Session '{name}' not found. Use /session new {name} to create it.")
                return
            result = self.dispatcher.set_session(name)
            await msg.reply_text(result)
            return

        if cmd == "/session":
            active = self.dispatcher.get_active_session()
            await msg.reply_text(f"Active session: {active}\n\nUse /session new <name> to start a new one.")
            return

        if cmd == "/task" and len(parts) >= 2 and parts[1] == "list":
            from src.agents.tasks.scheduler import list_tasks

            tasks = list_tasks(self._agent_target)
            if not tasks:
                await msg.reply_text("No scheduled tasks.")
                return
            lines = []
            for t in tasks:
                next_time = (
                    __import__("datetime").datetime.fromisoformat(t.next_run).strftime("%c") if t.next_run else "?"
                )
                type_str = f"every {t.interval_ms // 60000}m" if t.interval_ms else "once"
                lines.append(f"  • {t.description} ({type_str}) — next: {next_time} — `{t.id}`")
            await msg.reply_text("Scheduled tasks:\n" + "\n".join(lines))
            return

        if cmd == "/task" and len(parts) >= 3 and parts[1] == "remove":
            from src.agents.tasks.scheduler import remove_task

            ok = remove_task(self._agent_target, parts[2])
            await msg.reply_text(f"{'✓ Task removed.' if ok else 'Task not found.'}")
            return

        if cmd == "/task":
            await msg.reply_text("Usage: /task list | /task remove <id>")
            return

        if cmd == "/knowledge" and len(parts) >= 2 and parts[1] == "list":
            from src.agents.rag.vector_store import list_documents

            docs = await list_documents(self._agent_target)
            if not docs:
                await msg.reply_text("No documents in knowledge base.")
                return
            lines = [f"  • {d.title} ({d.chunk_count} chunks) — `{d.id}`" for d in docs]
            await msg.reply_text("Indexed documents:\n" + "\n".join(lines))
            return

        if cmd == "/knowledge" and len(parts) >= 3 and parts[1] == "remove":
            from src.agents.rag.vector_store import remove_document

            ok = await remove_document(self._agent_target, parts[2])
            await msg.reply_text(f"{'✓ Removed.' if ok else 'Document not found.'}")
            return

        if cmd == "/knowledge":
            from src.agents.rag.vector_store import get_store_stats

            stats = await get_store_stats(self._agent_target)
            await msg.reply_text(
                f"Knowledge base: {stats['doc_count']} documents, {stats['chunk_count']} chunks.\n\n"
                f"Index new content by asking the agent to save files or URLs."
            )
            return

        if cmd == "/search" and len(parts) >= 2:
            query = " ".join(parts[1:]).lower()
            history_path = Path("agents_workspace") / self._agent_target / "history.jsonl"
            if not history_path.exists():
                await msg.reply_text("No conversation history found.")
                return
            matches = []
            try:
                for line in history_path.read_text("utf-8", errors="replace").splitlines():
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        if query in entry.get("content", "").lower():
                            role = entry.get("role", "?")
                            content = entry.get("content", "")[:200]
                            matches.append(f"[{role}] {content}")
                    except json.JSONDecodeError:
                        continue
                    if len(matches) >= 10:
                        break
            except Exception:
                pass
            if not matches:
                await msg.reply_text(f"No matches for '{query}'.")
            else:
                await msg.reply_text(f"Search results for '{query}':\n\n" + "\n---\n".join(matches))
            return

        if cmd == "/perfect":
            from src.agents.learning import save_workflow
            main_agent = self.dispatcher._active_agents.get(self._agent_target)
            seq = getattr(main_agent, "_last_tool_sequence", None) if main_agent else None
            if seq:
                user_msg = getattr(main_agent, "_last_user_message", "") or ""
                trigger = seq[0]
                for prefix in ("sandbox_", "obsidian_", "create_", "get_", "list_"):
                    trigger = trigger.replace(prefix, "")
                if len(trigger) < 3:
                    trigger = "task"
                await save_workflow(trigger.lower(), seq, user_msg[:200])
                await msg.reply_text(f"✓ Learned workflow for '{trigger}': {' → '.join(seq)}")
            else:
                await msg.reply_text("No recent tool calls to learn from.")
            return

        if cmd == "/forget" and len(parts) >= 2:
            from src.agents.learning import forget_workflow
            ok = await forget_workflow(parts[1].lower())
            await msg.reply_text(f"{'✓ Forgotten.' if ok else 'Not found.'}")
            return

        if cmd == "/workflows":
            from src.agents.learning import list_workflows
            wfs = await list_workflows()
            if not wfs:
                await msg.reply_text("No workflows learned yet.")
            else:
                lines = [f"Learned workflows ({len(wfs)}):"]
                for w in wfs:
                    seq = " → ".join(w["tool_sequence"])
                    lines.append(f"  • {w['trigger']} (x{w['success_count']}): {seq}")
                await msg.reply_text("\n".join(lines))
            return

    async def handle_message(self, update: Update, context: Any = None) -> None:
        msg = update.message
        if msg is None or not msg.text:
            return
        chat_id = msg.chat_id
        user_id = update.effective_user.id if update.effective_user else 0
        if chat_id:
            self._user_last_active[chat_id] = __import__("time").time()
            self._known_users.add(chat_id)

        # Authorization
        if ALLOWLIST and user_id not in ALLOWLIST:
            await msg.reply_text("You do not have permission to use this bot.")
            return

        text = msg.text

        # Handle commands
        if text.startswith("/"):
            await self.handle_command(update, context)
            return

        assert msg.chat is not None

        # Streamed message: send initial placeholder, update as tokens arrive
        stream_msg = await msg.reply_text("...", parse_mode="HTML")
        accumulated = ""
        last_edit = 0.0

        def on_token(token: str) -> None:
            nonlocal accumulated, last_edit
            accumulated += token
            now_t = __import__("time").time()
            # Throttle edits to once per 0.8 seconds
            if now_t - last_edit > 0.8:
                last_edit = now_t
                safe_part = _convert_markdown(accumulated)
                # Don't edit if too long (Telegram has 4096 limit for edits too)
                if len(safe_part) < 3500:
                    try:
                        asyncio.create_task(stream_msg.edit_text(safe_part, parse_mode="HTML"))
                    except Exception:
                        pass

        task = asyncio.create_task(
            self.dispatcher.dispatch(self._agent_target, text, 0, chat_id, on_token)
        )
        typing = asyncio.create_task(_typing_indicator(msg.chat, task))
        try:
            response = await task
            # Send the final complete response
            await stream_msg.delete()
            safe = _convert_markdown(response or "(no response)")
            await _send_long_message(msg, safe)
            await self._send_pending_files(chat_id, update)
        except Exception as e:
            await msg.reply_text(f"Error: {e}")
        finally:
            typing.cancel()

    async def _send_pending_files(self, chat_id: int, update: Update) -> None:
        files = get_pending_files(chat_id)
        msg = update.message
        if msg is None:
            return
        assert msg.chat is not None
        for f in files:
            content = f["content"]
            if isinstance(content, str):
                content = content.encode("utf-8")
            content_hash = hash(content)
            if content_hash in _sent_content_hashes:
                continue
            await msg.chat.send_action("upload_document")
            from telegram import InputFile

            await msg.reply_document(document=InputFile(content, filename=f["filename"]))
            _sent_content_hashes.add(content_hash)

    async def handle_file(self, update: Update, context: Any = None) -> None:
        msg = update.message
        if msg is None:
            return
        chat_id = msg.chat_id
        caption = (msg.caption or "").strip()
        if chat_id:
            self._user_last_active[chat_id] = __import__("time").time()
            self._known_users.add(chat_id)

        assert msg.chat is not None

        try:
            from telegram import Document, PhotoSize

            attachment = msg.effective_attachment
            if isinstance(attachment, (Document, PhotoSize)):
                file = await attachment.get_file()
            elif isinstance(attachment, (list, tuple)) and attachment:
                file = await attachment[-1].get_file()
            else:
                await msg.reply_text("Unsupported attachment type.")
                return
            filename = getattr(
                attachment, "file_name", file.file_path.split("/")[-1] if file.file_path else "unknown.txt"
            )

            sandbox = Path("agent_sandbox")
            sandbox.mkdir(exist_ok=True)
            file_path = sandbox / filename
            await file.download_to_drive(file_path)

            is_image = filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"))

            if is_image:
                # Use Groq vision to analyze the image
                from src.agents.tools.groq_media import analyze_image

                await msg.chat.send_action("typing")
                vision_prompt = caption or "Describe this image in detail."
                description = await analyze_image(str(file_path), vision_prompt)
                full_message = f"[Image uploaded and analyzed via Groq vision]\n{description}"
                if caption:
                    full_message += f"\n\nUser said: {caption}"
            else:
                # Text-based file handling
                result = read_file(file_path)
                if result.get("error"):
                    await msg.reply_text(f"Error reading file: {result['error']}")
                    return
                label = get_type_label(result)
                file_content = result.get("content", "")
                chunk_size = 15000

                if len(file_content) > chunk_size and caption:
                    chunks = [file_content[i:i+chunk_size] for i in range(0, len(file_content), chunk_size)]
                    total = len(chunks)
                    for idx, chunk in enumerate(chunks):
                        chunk_msg = (
                            f"[Uploaded via Telegram — {label}: {result['name']}]"
                            f" [Part {idx+1}/{total}]\n\n{chunk}"
                            f"\n\nUser message: {caption}"
                        )
                        task = asyncio.create_task(
                            self.dispatcher.dispatch(self._agent_target, chunk_msg, 0, chat_id)
                        )
                        typing = asyncio.create_task(_typing_indicator(msg.chat, task))
                        response = await task
                        safe = _convert_markdown(response)
                        await _send_long_message(msg, safe)
                        typing.cancel()
                    await self._send_pending_files(chat_id, update)
                    return
                else:
                    info = f"{label}: {result['name']} ({result.get('size', 0)} bytes)"
                    file_info = f"[Uploaded via Telegram — {info}]\n\n"
                    if len(file_content) > chunk_size:
                        file_content = file_content[:chunk_size] + "\n\n[...truncated]"
                    full_message = f"{file_info}{file_content}"
                    if caption:
                        full_message += f"\n\nUser message: {caption}"

            task = asyncio.create_task(self.dispatcher.dispatch(self._agent_target, full_message, 0, chat_id))
            typing = asyncio.create_task(_typing_indicator(msg.chat, task))
            response = await task
            safe = _convert_markdown(response)
            await _send_long_message(msg, safe)
            typing.cancel()
            await self._send_pending_files(chat_id, update)
        except Exception as e:
            await msg.reply_text(f"Error: {e}")

    async def handle_voice(self, update: Update, context: Any = None) -> None:
        msg = update.message
        if msg is None or not msg.voice:
            return
        chat_id = msg.chat_id
        if chat_id:
            self._user_last_active[chat_id] = __import__("time").time()
            self._known_users.add(chat_id)

        assert msg.chat is not None
        await msg.chat.send_action("typing")

        try:
            file = await msg.voice.get_file()
            sandbox = Path("agent_sandbox")
            sandbox.mkdir(exist_ok=True)
            file_path = sandbox / f"voice_{msg.voice.file_id[:10]}.ogg"
            await file.download_to_drive(file_path)

            from src.agents.tools.groq_media import transcribe_audio
            text = await transcribe_audio(str(file_path))
            if text.startswith("ERROR"):
                await msg.reply_text(text)
                return

            file_path.unlink(missing_ok=True)
            full_message = f"[Voice transcribed]: {text}"

            task = asyncio.create_task(self.dispatcher.dispatch(self._agent_target, full_message, 0, chat_id))
            typing = asyncio.create_task(_typing_indicator(msg.chat, task))
            response = await task
            safe = _convert_markdown(response)
            await _send_long_message(msg, safe)
            typing.cancel()
            await self._send_pending_files(chat_id, update)
        except Exception as e:
            await msg.reply_text(f"Error: {e}")

    async def start(self) -> None:
        # Start background tasks first (don't depend on Telegram)
        asyncio.create_task(self._validate_coro)
        asyncio.create_task(self._scheduler_loop())
        asyncio.create_task(self._start_api())

        # Telegram bot (optional — doesn't block API server)
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if token:
            try:
                app = Application.builder().token(token).build()
                app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
                app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, self.handle_file))
                app.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
                app.add_handler(
                    CommandHandler(
                        [
                            "start",
                            "help",
                            "models",
                            "providers",
                            "status",
                            "profile",
                            "reset",
                            "session",
                            "task",
                            "knowledge",
                            "search",
                            "perfect",
                            "forget",
                            "workflows",
                        ],
                        self.handle_command,
                    )
                )

                await app.initialize()
                updater = app.updater
                if updater is not None:
                    await updater.start_polling(allowed_updates=Update.ALL_TYPES)
                await app.start()
                self._app = app
                logger.info("[MAIN] Telegram bot connected.")
            except Exception as e:
                self._app = None
                logger.warning("[MAIN] Telegram bot failed to start: %s. API server still running.", e)
        else:
            self._app = None
            logger.info("[MAIN] No TELEGRAM_BOT_TOKEN — running API-only mode.")

        logger.info("[MAIN] K.I.N.E.T.I.C. is running.")

        # Keep running until interrupted
        global _shutting_down
        if _shutting_down:
            await _shutting_down.wait()
        else:
            await asyncio.Event().wait()

    async def _scheduler_loop(self) -> None:
        global _shutting_down
        # Track which task IDs have been warned to avoid duplicate reminders
        _warned: set[str] = set()
        while not (_shutting_down and _shutting_down.is_set()):
            try:
                from src.agents.tasks.scheduler import get_overdue_tasks, get_upcoming_tasks, mark_task_run

                now = __import__("datetime").datetime.now()

                # ── 1. Overdue tasks (past due) ──
                overdue = get_overdue_tasks()
                for item in overdue:
                    agent_id = item["agent_id"]
                    task = item["task"]
                    task_type = task.get("type", "once")
                    desc = task.get("description", "")
                    chat_id = task.get("chat_id")
                    logger.info("[SCHEDULER] Running overdue task '%s' for %s", desc, agent_id)
                    try:
                        if task_type == "monitor":
                            check_prompt = task.get("query", desc)
                            response = await self.dispatcher.dispatch(agent_id, f"[MONITOR] {check_prompt}")
                            mark_task_run(agent_id, task["id"])
                            resp_upper = (response or "").upper()
                            if any(kw in resp_upper for kw in ("CONDITION_MET", "ALERT", "YES", "CONDITION MET")):
                                if chat_id and self._app:
                                    safe = _convert_markdown(f"[MONITOR] Triggered: {desc}\n\n{response[:500]}")
                                    await self._app.bot.send_message(chat_id=chat_id, text=safe, parse_mode="HTML")
                        else:
                            # Apologize for lateness if more than 2 min overdue
                            apology = ""
                            if chat_id and task.get("next_run", ""):
                                try:
                                    due = __import__("datetime").datetime.fromisoformat(task["next_run"])
                                    late_min = (now - due).total_seconds() / 60
                                    if late_min > 2:
                                        apology = (
                                    f"\n\n(Sorry this reminder is {int(late_min)}m late"
                                    " — I'll do better!)"
                                )
                                except Exception:
                                    pass
                            response = await self.dispatcher.dispatch(agent_id, f"[REMINDER] {desc}")
                            mark_task_run(agent_id, task["id"])
                            if chat_id and self._app:
                                text = (response or "") + apology
                                safe = _convert_markdown(text)
                                await self._app.bot.send_message(chat_id=chat_id, text=safe, parse_mode="HTML")
                    except Exception as e:
                        logger.warning("[SCHEDULER] Task '%s' failed: %s", task.get("id"), e)
                        mark_task_run(agent_id, task["id"])

                # ── 2. Upcoming tasks (5 min warning) ──
                upcoming = get_upcoming_tasks(5)
                for item in upcoming:
                    task_id = item["task"]["id"]
                    if task_id in _warned:
                        continue
                    _warned.add(task_id)
                    desc = item["task"].get("description", "")
                    chat_id = item["task"].get("chat_id")
                    # Skip 5-min warning for tasks due in <3 min (e.g., "remind in 1 min")
                    next_run = item["task"].get("next_run", "")
                    if next_run:
                        try:
                            due_in = (__import__("datetime").datetime.fromisoformat(next_run) - now).total_seconds()
                            if due_in < 180:  # less than 3 minutes
                                continue
                        except Exception:
                            pass
                    if chat_id and self._app:
                        msg = f"⏰ Reminder: {desc} coming up in about 5 minutes."
                        safe = _convert_markdown(msg)
                        await self._app.bot.send_message(chat_id=chat_id, text=safe, parse_mode="HTML")

                # Cleanup: remove warned ids for tasks that no longer exist
                all_ids = {item["task"]["id"] for item in overdue + upcoming}
                _warned &= all_ids

                # ── 3. Morning briefing (7 AM, once per day) — send to ALL known users ──
                today_str = now.strftime("%Y-%m-%d")
                if now.hour == 7 and now.minute < 2 and self._last_briefing_date != today_str:
                    self._last_briefing_date = today_str
                    if self._app and self._known_users:
                        from src.agents.tools.briefing_tool import _daily_briefing
                        from src.agents.tools.registry import ToolContext
                        briefing = await _daily_briefing({}, ToolContext())
                        if briefing and not briefing.startswith("ERROR"):
                            safe = _convert_markdown(f"☀️ Good morning! Here's your briefing.\n\n{briefing}")
                            for cid in self._known_users:
                                try:
                                    await self._app.bot.send_message(chat_id=cid, text=safe, parse_mode="HTML")
                                except Exception:
                                    pass

                # ── 4. Idle check-in (3+ hours) — per user ──
                now_ts = __import__("time").time()
                for cid in list(self._known_users):
                    last_active = self._user_last_active.get(cid, now_ts)
                    idle_hours = (now_ts - last_active) / 3600
                    if idle_hours > 3 and self._app and now.hour < 22:
                        self._user_last_active[cid] = now_ts  # Reset to avoid spam
                        check_in = "Hey, been a while. Just checking in — anything on your mind?"
                        try:
                            await self._app.bot.send_message(chat_id=cid, text=check_in)
                        except Exception:
                            pass
                # Cleanup: remove warned ids for tasks that no longer exist
                all_ids = {item["task"]["id"] for item in overdue + upcoming}
                _warned &= all_ids

                # Persist scheduler meta every cycle
                try:
                    self._meta_path.write_text(json.dumps({
                        "briefing_date": self._last_briefing_date,
                        "warned": list(_warned),
                        "known_users": list(self._known_users),
                    }))
                except Exception:
                    pass
            except Exception:
                pass
            await asyncio.sleep(10)

    async def _start_api(self) -> None:
        import uvicorn

        from src.api.server import create_app

        app = create_app(self.dispatcher, self._agent_target)
        config = uvicorn.Config(app, host="0.0.0.0", port=API_PORT, log_level="info")
        server = uvicorn.Server(config)
        logger.info("[API] Web UI at http://localhost:%d", API_PORT)
        try:
            await server.serve()
        except (Exception, KeyboardInterrupt, asyncio.CancelledError):
            pass


def main() -> None:
    global _shutting_down
    _shutting_down = asyncio.Event()
    bot = KinetiCBot()

    async def _shutdown() -> None:
        if _shutting_down.is_set():
            return
        logger.info("[SHUTDOWN] Stopping...")
        _shutting_down.set()
        # Cancel bot tasks
        if bot._app:
            try:
                await bot._app.stop()
                await bot._app.shutdown()
            except Exception:
                pass

    def _signal_handler() -> None:
        try:
            asyncio.ensure_future(_shutdown())
        except Exception:
            pass

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Register signal handler (Unix) or fallback (Windows)
    try:
        loop.add_signal_handler(
            signal.SIGINT,
            _signal_handler,
        )
        loop.add_signal_handler(
            signal.SIGTERM,
            _signal_handler,
        )
    except (NotImplementedError, AttributeError):
        # Windows: add_signal_handler not supported
        # Use a polling approach — check a flag set by KeyboardInterrupt
        pass

    try:
        loop.run_until_complete(bot.start())
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Windows: KeyboardInterrupt is raised directly
        # Set the event so scheduler and other loops exit
        _shutting_down.set()
    finally:
        # Cancel all remaining tasks gracefully
        pending = asyncio.all_tasks(loop)
        for t in pending:
            t.cancel()
        if pending:
            try:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
        if not loop.is_closed():
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
        logger.info("[MAIN] Stopped.")


if __name__ == "__main__":
    main()
