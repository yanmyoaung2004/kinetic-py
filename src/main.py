from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import dotenv
import structlog
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from src.agents.orchestrator import KinetiCDispatcher
from src.config.loader import load_model_config, validate_endpoints
from src.utils.file_reader import get_type_label, read_file
from src.agents.tools.send_file_tool import get_pending_files

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
    """Escape Telegram MarkdownV2 special chars, preserving code blocks."""
    import re

    # Protect code blocks
    blocks: list[str] = []
    def _save(m: re.Match) -> str:
        blocks.append(m.group(0))
        return f"\x00CODEBLOCK{len(blocks)-1}\x00"
    text = re.sub(r"```[\s\S]*?```|`[^`]+`", _save, text)

    # Escape remaining special chars
    text = re.sub(r"([_*[\]()~`>#+\-=|{}.!])", r"\\\1", text)

    # Restore code blocks
    for i, block in enumerate(blocks):
        text = text.replace(f"\x00CODEBLOCK{i}\x00", block)
    return text


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

    async def handle_command(self, update: Update, context: None = None) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else 0
        text = update.message.text if update.message else ""
        if not text:
            return

        parts = text.split()
        cmd = parts[0].lower()

        if cmd in ("/start", "/help"):
            await update.message.reply_text(COMMANDS_HELP)
            return

        if cmd == "/models" and len(parts) >= 4 and parts[1] == "set" and parts[2] == "think":
            provider = parts[3]
            model = " ".join(parts[4:]) if len(parts) > 4 else None
            result = self.dispatcher.set_stage_override("think", provider, model)
            await update.message.reply_text(result)
            return

        if cmd == "/models" and len(parts) >= 3 and parts[1] == "reset" and parts[2] == "think":
            result = self.dispatcher.clear_stage_override("think")
            await update.message.reply_text(result)
            return

        if cmd == "/models":
            config = self.dispatcher.get_active_config()
            await update.message.reply_text(f"Current stage configuration:\n{config}\n\nUse /models set think <provider> [model] to switch at runtime.")
            return

        if cmd == "/providers":
            await update.message.reply_text("Available providers:\n" + self.dispatcher.get_provider_list())
            return

        if cmd == "/status":
            await update.message.reply_text(
                f"Uptime: {self.dispatcher.get_uptime()}\n"
                f"Active agents: {self.dispatcher.get_agent_count()}\n"
                f"Dispatch target: {self._agent_target}"
            )
            return

        if cmd == "/profile":
            from src.agents.memory import AgentMemory
            import json as _json

            profile_path = Path("agents_workspace") / self._agent_target / "profile.json"
            if profile_path.exists():
                profile = _json.loads(profile_path.read_text("utf-8"))
                facts = "\n".join(f"• {f}" for f in profile.get("known_facts", [])) or "None yet"
                prefs = ", ".join(profile.get("preferences", [])) or "None yet"
                await update.message.reply_text(f"Known facts:\n{facts}\n\nPreferences: {prefs}")
            else:
                await update.message.reply_text("No profile extracted yet. Send me a few messages and I'll learn about you.")
            return

        if cmd == "/reset":
            from src.agents.memory import AgentMemory

            session_id = self.dispatcher.get_active_session()
            mem = AgentMemory(self._agent_target, "agents_workspace", session_id=session_id)
            mem.reset()
            await update.message.reply_text(f"✓ Session '{session_id}' cleared.")
            return

        if cmd == "/session" and len(parts) >= 3 and parts[1] == "new":
            name = "-".join(parts[2:])
            import re as _re
            name = _re.sub(r"[^a-zA-Z0-9_-]", "_", name)
            result = self.dispatcher.set_session(name)
            await update.message.reply_text(result)
            return

        if cmd == "/session" and len(parts) >= 2 and parts[1] == "list":
            from src.agents.memory import AgentMemory

            sessions = AgentMemory.list_sessions(self._agent_target, "agents_workspace")
            active = self.dispatcher.get_active_session()
            session_list = "\n".join(f"  {s}{' ← active' if s == active else ''}" for s in sessions) if sessions else "  (no additional sessions)"
            await update.message.reply_text(f"Sessions:\n{session_list}\n\nActive: {active}")
            return

        if cmd == "/session" and len(parts) >= 2:
            name = parts[1]
            from src.agents.memory import AgentMemory

            sessions = AgentMemory.list_sessions(self._agent_target, "agents_workspace")
            if name != "default" and name not in sessions:
                await update.message.reply_text(f"Session '{name}' not found. Use /session new {name} to create it.")
                return
            result = self.dispatcher.set_session(name)
            await update.message.reply_text(result)
            return

        if cmd == "/session":
            active = self.dispatcher.get_active_session()
            await update.message.reply_text(f"Active session: {active}\n\nUse /session new <name> to start a new one.")
            return

        if cmd == "/task" and len(parts) >= 2 and parts[1] == "list":
            from src.agents.tasks.scheduler import list_tasks

            tasks = list_tasks(self._agent_target)
            if not tasks:
                await update.message.reply_text("No scheduled tasks.")
                return
            lines = []
            for t in tasks:
                next_time = __import__("datetime").datetime.fromisoformat(t.next_run).strftime("%c") if t.next_run else "?"
                type_str = f"every {t.interval_ms // 60000}m" if t.interval_ms else "once"
                lines.append(f"  • {t.description} ({type_str}) — next: {next_time} — `{t.id}`")
            await update.message.reply_text("Scheduled tasks:\n" + "\n".join(lines))
            return

        if cmd == "/task" and len(parts) >= 3 and parts[1] == "remove":
            from src.agents.tasks.scheduler import remove_task

            ok = remove_task(self._agent_target, parts[2])
            await update.message.reply_text(f"{'✓ Task removed.' if ok else f'Task not found.'}")
            return

        if cmd == "/task":
            await update.message.reply_text("Usage: /task list | /task remove <id>")
            return

        if cmd == "/knowledge" and len(parts) >= 2 and parts[1] == "list":
            from src.agents.rag.vector_store import list_documents

            docs = await list_documents(self._agent_target)
            if not docs:
                await update.message.reply_text("No documents in knowledge base.")
                return
            lines = [f"  • {d.title} ({d.chunk_count} chunks) — `{d.id}`" for d in docs]
            await update.message.reply_text("Indexed documents:\n" + "\n".join(lines))
            return

        if cmd == "/knowledge" and len(parts) >= 3 and parts[1] == "remove":
            from src.agents.rag.vector_store import remove_document

            ok = await remove_document(self._agent_target, parts[2])
            await update.message.reply_text(f"{'✓ Removed.' if ok else 'Document not found.'}")
            return

        if cmd == "/knowledge":
            from src.agents.rag.vector_store import get_store_stats

            stats = await get_store_stats(self._agent_target)
            await update.message.reply_text(
                f"Knowledge base: {stats['doc_count']} documents, {stats['chunk_count']} chunks.\n\n"
                f"Index new content by asking the agent to save files or URLs."
            )
            return

    async def handle_message(self, update: Update, context: None = None) -> None:
        if not update.message or not update.message.text:
            return
        chat_id = update.effective_chat.id if update.effective_chat else 0
        user_id = update.effective_user.id if update.effective_user else 0

        # Authorization
        if ALLOWLIST and user_id not in ALLOWLIST:
            await update.message.reply_text("You do not have permission to use this bot.")
            return

        text = update.message.text

        # Handle commands
        if text.startswith("/"):
            await self.handle_command(update, context)
            return

        await update.effective_chat.send_action("typing")
        try:
            response = await self.dispatcher.dispatch(self._agent_target, text, 0, chat_id)
            safe = _convert_markdown(response)
            await update.message.reply_text(safe, parse_mode="MarkdownV2")
            await self._send_pending_files(chat_id, update)
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _send_pending_files(self, chat_id: int, update: Update) -> None:
        files = get_pending_files(chat_id)
        for f in files:
            await update.effective_chat.send_action("upload_document")
            content = f["content"]
            if isinstance(content, str):
                content = content.encode("utf-8")
            from telegram import InputFile
            await update.message.reply_document(document=InputFile(content, filename=f["filename"]))

    async def handle_file(self, update: Update, context: None = None) -> None:
        if not update.message:
            return
        chat_id = update.effective_chat.id if update.effective_chat else 0
        caption = (update.message.caption or "").strip()

        await update.effective_chat.send_action("typing")

        try:
            file = await (update.message.effective_attachment.get_file())
            filename = getattr(update.message.effective_attachment, "file_name", file.file_path.split("/")[-1] if file.file_path else "unknown.txt")

            from pathlib import Path
            sandbox = Path("agent_sandbox")
            sandbox.mkdir(exist_ok=True)
            file_path = sandbox / filename

            await file.download_to_drive(file_path)

            result = read_file(file_path)
            if result.get("error"):
                await update.message.reply_text(f"Error reading file: {result['error']}")
                return

            label = get_type_label(result)
            file_info = f"[Uploaded via Telegram — {label}: {result['name']} ({result.get('size', 0)} bytes)]\n\n"
            file_content = result.get("content", "")
            if len(file_content) > 50000:
                file_content = file_content[:50000] + "\n\n[...truncated]"

            full_message = f"{file_info}{file_content}"
            if caption:
                full_message += f"\n\nUser message: {caption}"

            response = await self.dispatcher.dispatch(self._agent_target, full_message, 0, chat_id)
            safe = _convert_markdown(response)
            await update.message.reply_text(safe, parse_mode="MarkdownV2")
            await self._send_pending_files(chat_id, update)
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def start(self) -> None:
        # Start background tasks first (don't depend on Telegram)
        asyncio.create_task(self._validate_coro)
        asyncio.create_task(self._scheduler_loop())
        asyncio.create_task(self._start_api())

        # Telegram bot (optional — doesn't block API server)
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if token:
            try:
                self._app = Application.builder().token(token).build()
                self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
                self._app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, self.handle_file))
                self._app.add_handler(CommandHandler(["start", "help", "models", "providers", "status", "profile", "reset", "session", "task", "knowledge"], self.handle_command))

                await self._app.initialize()
                await self._app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
                await self._app.start()
                logger.info("[MAIN] Telegram bot connected.")
            except Exception as e:
                self._app = None
                logger.warning("[MAIN] Telegram bot failed to start: %s. API server still running.", e)
        else:
            self._app = None
            logger.info("[MAIN] No TELEGRAM_BOT_TOKEN — running API-only mode.")

        logger.info("[MAIN] K.I.N.E.T.I.C. is running.")

        # Keep running until interrupted
        await asyncio.Event().wait()

    async def _scheduler_loop(self) -> None:
        while True:
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
                                    await self._app.bot.send_message(chat_id=chat_id, text=safe, parse_mode="MarkdownV2")
                        else:
                            response = await self.dispatcher.dispatch(agent_id, f"[REMINDER] {desc}")
                            mark_task_run(agent_id, task["id"])
                            chat_id = task.get("chat_id")
                            if chat_id and self._app:
                                safe = _convert_markdown(response or "")
                                await self._app.bot.send_message(chat_id=chat_id, text=safe, parse_mode="MarkdownV2")
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
        except SystemExit:
            logger.warning("[API] Port %d already in use.", API_PORT)


def main() -> None:
    bot = KinetiCBot()

    async def _shutdown(sig: str) -> None:
        logger.info("[SHUTDOWN] Received %s. Stopping...", sig)
        sys.exit(0)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in ("SIGINT", "SIGTERM"):
        try:
            loop.add_signal_handler(
                getattr(signal, sig),
                lambda: asyncio.create_task(_shutdown(sig)),
            )
        except (NotImplementedError, AttributeError):
            pass

    try:
        loop.run_until_complete(bot.start())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
