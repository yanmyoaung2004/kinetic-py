"""Email tools — IMAP read + SMTP send."""

from __future__ import annotations

import imaplib
import logging
import os
import smtplib
import time as time_module
from email.message import EmailMessage
from email.parser import BytesParser
from typing import Any

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

logger = logging.getLogger("kinetic.tools.email")

def _read_env(name: str, default: str = "") -> str:
    import dotenv
    dotenv.load_dotenv()
    return os.environ.get(name, default)


def _get_cfg():
    return {
        "imap_host": _read_env("EMAIL_IMAP_SERVER"),
        "imap_port": int(_read_env("EMAIL_IMAP_PORT", "993")),
        "smtp_host": _read_env("EMAIL_SMTP_SERVER"),
        "smtp_port": int(_read_env("EMAIL_SMTP_PORT", "587")),
        "addr": _read_env("EMAIL_ADDRESS"),
        "pass": _read_env("EMAIL_PASSWORD"),
    }


def _check_config() -> str | None:
    cfg = _get_cfg()
    if not cfg["addr"] or not cfg["pass"]:
        return "Email not configured. Set EMAIL_ADDRESS, EMAIL_PASSWORD, EMAIL_IMAP_SERVER in .env"
    return None


async def _read_emails(args: dict[str, Any], ctx: ToolContext | None) -> str:
    err = _check_config()
    if err:
        return f"ERROR: {err}"
    folder = args.get("folder", "INBOX")
    max_emails = min(args.get("max", 10), 50)
    since_days = args.get("since_days", 1)
    try:
        cfg = _get_cfg()
        mail = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"])
        mail.login(cfg["addr"], cfg["pass"])
        mail.select(folder)
        date_since = (time_module.strftime("%d-%b-%Y", time_module.gmtime(time_module.time() - since_days * 86400)))
        status, data = mail.search(None, f'(SINCE {date_since})')
        if status != "OK":
            mail.logout()
            return f"No emails found in {folder}"
        ids = data[0].split()[-max_emails:]
        results = []
        for eid in ids:
            status, msg_data = mail.fetch(eid, "(RFC822)")
            if status != "OK":
                continue
            msg = BytesParser().parsebytes(msg_data[0][1])
            results.append({
                "from": msg.get("From", ""),
                "subject": msg.get("Subject", ""),
                "date": msg.get("Date", ""),
            })
        mail.logout()
        if not results:
            return f"No emails found in {folder} since {date_since}"
        lines = [f"Recent emails from {folder}:"]
        for r in results:
            lines.append(f"  • From: {r['from']}")
            lines.append(f"    Subject: {r['subject']}")
            lines.append(f"    Date: {r['date']}")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR reading emails: {e}"


async def _send_email(args: dict[str, Any], ctx: ToolContext | None) -> str:
    err = _check_config()
    if err:
        return f"ERROR: {err}"
    to_addr = args.get("to", "")
    subject = args.get("subject", "")
    body = args.get("body", "")
    if not to_addr or not subject:
        return "ERROR: 'to' and 'subject' are required."
    try:
        cfg = _get_cfg()
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = cfg["addr"]
        msg["To"] = to_addr
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as s:
            s.starttls()
            s.login(cfg["addr"], cfg["pass"])
            s.send_message(msg)
        return f"Email sent to {to_addr}: {subject}"
    except Exception as e:
        return f"ERROR sending email: {e}"


def create_read_emails_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "read_emails",
                "description": "Read recent emails from the user's inbox. Email credentials are already configured in the environment. When the user asks to read emails, call this tool immediately without asking for credentials.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "folder": {"type": "string", "description": "Mail folder (default: INBOX)"},
                        "max": {"type": "number", "description": "Max emails to fetch (default: 10, max: 50)"},
                        "since_days": {"type": "number", "description": "Look back days (default: 1)"},
                    },
                },
            },
        ),
        execute=_read_emails,
    )


def create_send_email_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "send_email",
                "description": "Send an email to any address. Use this when the user asks to send an email.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Recipient email address"},
                        "subject": {"type": "string", "description": "Email subject"},
                        "body": {"type": "string", "description": "Email body text"},
                    },
                    "required": ["to", "subject"],
                },
            },
        ),
        execute=_send_email,
    )
