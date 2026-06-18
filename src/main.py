from __future__ import annotations

import asyncio
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
"""


def _convert_markdown(text: str) -> str:
    """Convert Markdown to Telegram HTML format safely — no formatting inside code."""
    import html
    import re

    # Escape HTML entities first
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

    async def handle_message(self, update: Update, context: Any = None) -> None:
        msg = update.message
        if msg is None or not msg.text:
            return
        chat_id = msg.chat_id
        user_id = update.effective_user.id if update.effective_user else 0

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
        task = asyncio.create_task(self.dispatcher.dispatch(self._agent_target, text, 0, chat_id))
        typing = asyncio.create_task(_typing_indicator(msg.chat, task))
        try:
            response = await task
            safe = _convert_markdown(response or "(no response)")
            await _send_long_message(msg, safe)
            await self._send_pending_files(chat_id, update)

            # Check if agent has a pending coding task (for follow-up result)
            main_agent = self.dispatcher._active_agents.get(self._agent_target)
            if main_agent and hasattr(main_agent, "_pending_coding_task"):
                coding_task = main_agent._pending_coding_task
                if coding_task and not coding_task.done():
                    new_typing = asyncio.create_task(_typing_indicator(msg.chat, coding_task))
                    coding_result = await coding_task
                    new_typing.cancel()
                    if coding_result:
                        safe_result = _convert_markdown(coding_result or "")
                        if safe_result:
                            labeled = f"<b>From coding-assistant:</b>\n{safe_result}"
                            await _send_long_message(msg, labeled)
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
            await msg.chat.send_action("upload_document")
            content = f["content"]
            if isinstance(content, str):
                content = content.encode("utf-8")
            from telegram import InputFile

            await msg.reply_document(document=InputFile(content, filename=f["filename"]))

    async def handle_file(self, update: Update, context: Any = None) -> None:
        msg = update.message
        if msg is None:
            return
        chat_id = msg.chat_id
        caption = (msg.caption or "").strip()

        assert msg.chat is not None

        try:
            from telegram import Document, PhotoSize

            attachment = msg.effective_attachment
            if isinstance(attachment, (Document, PhotoSize)):
                file = await attachment.get_file()
            elif isinstance(attachment, list) and attachment:
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

            result = read_file(file_path)
            if result.get("error"):
                await msg.reply_text(f"Error reading file: {result['error']}")
                return

            label = get_type_label(result)
            file_info = f"[Uploaded via Telegram — {label}: {result['name']} ({result.get('size', 0)} bytes)]\n\n"
            file_content = result.get("content", "")
            if len(file_content) > 50000:
                file_content = file_content[:50000] + "\n\n[...truncated]"

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
        while not (_shutting_down and _shutting_down.is_set()):
            try:
                from src.agents.tasks.scheduler import get_overdue_tasks, mark_task_run

                overdue = get_overdue_tasks()
                for item in overdue:
                    agent_id = item["agent_id"]
                    task = item["task"]
                    task_type = task.get("type", "once")
                    desc = task.get("description", "")
                    logger.info("[SCHEDULER] Running task '%s' for %s", desc, agent_id)
                    try:
                        if task_type == "monitor":
                            check_prompt = task.get("query", desc)
                            response = await self.dispatcher.dispatch(agent_id, f"[MONITOR] {check_prompt}")
                            mark_task_run(agent_id, task["id"])
                            resp_upper = (response or "").upper()
                            if any(kw in resp_upper for kw in ("CONDITION_MET", "ALERT", "YES", "CONDITION MET")):
                                chat_id = task.get("chat_id")
                                if chat_id and self._app:
                                    safe = _convert_markdown(f"[MONITOR] Triggered: {desc}\n\n{response[:500]}")
                                    await self._app.bot.send_message(chat_id=chat_id, text=safe, parse_mode="HTML")
                        else:
                            response = await self.dispatcher.dispatch(agent_id, f"[REMINDER] {desc}")
                            mark_task_run(agent_id, task["id"])
                            chat_id = task.get("chat_id")
                            if chat_id and self._app:
                                safe = _convert_markdown(response or "")
                                await self._app.bot.send_message(chat_id=chat_id, text=safe, parse_mode="HTML")
                    except Exception as e:
                        logger.warning("[SCHEDULER] Task '%s' failed: %s", task.get("id"), e)
                        mark_task_run(agent_id, task["id"])
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
