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
    from_addr = args.get("from", "")
    subject_filter = args.get("subject", "")
    try:
        cfg = _get_cfg()
        mail = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"])
        mail.login(cfg["addr"], cfg["pass"])
        mail.select(folder)

        # Build IMAP search criteria
        criteria = []
        if since_days:
            date_since = time_module.strftime("%d-%b-%Y", time_module.gmtime(time_module.time() - since_days * 86400))
            criteria.append(f"SINCE {date_since}")
        if from_addr:
            criteria.append(f'FROM "{from_addr}"')
        if subject_filter:
            criteria.append(f'SUBJECT "{subject_filter}"')

        search_cmd = f"({' '.join(criteria)})" if criteria else "ALL"
        status, data = mail.search(None, search_cmd)
        if status != "OK":
            mail.logout()
            return f"No emails found in {folder}"
        ids = data[0].split()[-max_emails:]
        results = []
        for eid in ids:
            status, msg_data = mail.fetch(eid, "(RFC822)")  # type: ignore[misc]
            if status != "OK" or not msg_data:
                continue
            msg_bytes = msg_data[0][1]  # type: ignore[index]
            if isinstance(msg_bytes, bytes):
                msg = BytesParser().parsebytes(msg_bytes)
                results.append(
                    {
                        "from": msg.get("From", ""),
                        "subject": msg.get("Subject", ""),
                        "date": msg.get("Date", ""),
                    }
                )
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


async def _read_email_body(args: dict[str, Any], ctx: ToolContext | None) -> str:
    err = _check_config()
    if err:
        return f"ERROR: {err}"
    query = args.get("query", "")
    if not query:
        return "ERROR: 'query' parameter is required to find the email."
    folder = args.get("folder", "INBOX")
    try:
        cfg = _get_cfg()
        mail = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"])
        mail.login(cfg["addr"], cfg["pass"])
        mail.select(folder)

        # Search by subject or from
        status, data = mail.search(None, f'(OR SUBJECT "{query}" FROM "{query}")')
        if status != "OK" or not data[0]:
            mail.logout()
            return f"No email found matching: {query}"

        ids = data[0].split()
        latest_id = ids[-1]
        status, msg_data = mail.fetch(latest_id, "(RFC822)")  # type: ignore[misc]
        if status != "OK" or not msg_data:
            mail.logout()
            return "Could not fetch email content."

        msg_bytes = msg_data[0][1]  # type: ignore[index]
        if not isinstance(msg_bytes, bytes):
            mail.logout()
            return "Could not parse email content."
        msg = BytesParser().parsebytes(msg_bytes)

        # Extract body
        def _decode_payload(payload: Any) -> str:
            if isinstance(payload, bytes):
                return payload.decode("utf-8", errors="replace")
            return str(payload or "")

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = _decode_payload(part.get_payload(decode=True))
                    break
                elif part.get_content_type() == "text/html":
                    import re

                    html = _decode_payload(part.get_payload(decode=True))
                    body = re.sub(r"<[^>]+>", "", html)
        else:
            body = _decode_payload(msg.get_payload(decode=True))

        body = body[:5000]
        mail.logout()

        result = (
            f"From: {msg.get('From', '')}\nSubject: {msg.get('Subject', '')}\nDate: {msg.get('Date', '')}\n---\n{body}"
        )
        return result
    except Exception as e:
        return f"ERROR reading email body: {e}"


def create_read_email_body_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "read_email_body",
                "description": (
                    "Read the full content of a specific email. "
                    "Search by sender or subject. "
                    "Use this when the user asks 'tell me more about this email' or 'show me the content'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search by sender email or subject keyword to find the email",
                        },
                        "folder": {"type": "string", "description": "Mail folder (default: INBOX)"},
                    },
                    "required": ["query"],
                },
            },
        ),
        execute=_read_email_body,
    )


async def _reply_email(args: dict[str, Any], ctx: ToolContext | None) -> str:
    err = _check_config()
    if err:
        return f"ERROR: {err}"
    query = args.get("query", "")
    body = args.get("body", "")
    if not query or not body:
        return "ERROR: 'query' and 'body' are required."
    folder = args.get("folder", "INBOX")
    try:
        cfg = _get_cfg()

        # Fetch original email to get its Message-ID
        mail = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"])
        mail.login(cfg["addr"], cfg["pass"])
        mail.select(folder)
        status, data = mail.search(None, f'(OR SUBJECT "{query}" FROM "{query}")')
        if status != "OK" or not data[0]:
            mail.logout()
            return f"No email found matching: {query}"
        latest_id = data[0].split()[-1]
        status, msg_data = mail.fetch(latest_id, "(RFC822)")  # type: ignore[misc]
        if not msg_data:
            mail.logout()
            return "Could not fetch email content."
        msg_bytes = msg_data[0][1]  # type: ignore[index]
        if not isinstance(msg_bytes, bytes):
            mail.logout()
            return "Could not parse email content."
        orig_msg = BytesParser().parsebytes(msg_bytes)
        orig_msg_id = orig_msg.get("Message-ID", "")
        orig_subject = orig_msg.get("Subject", "")
        orig_from = orig_msg.get("From", "")
        mail.logout()

        # Extract original From address for reply-to
        import re

        reply_to_match = re.search(r"<([^>]+)>", orig_from) if "<" in orig_from else None
        reply_to = reply_to_match.group(1) if reply_to_match else orig_from

        subject = orig_subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = cfg["addr"]
        msg["To"] = reply_to
        if orig_msg_id:
            msg["In-Reply-To"] = orig_msg_id
            msg["References"] = orig_msg_id

        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as s:
            s.starttls()
            s.login(cfg["addr"], cfg["pass"])
            s.send_message(msg)

        return f"Reply sent to {reply_to}: {subject}"
    except Exception as e:
        return f"ERROR replying: {e}"


def create_reply_email_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "reply_to_email",
                "description": (
                    "Reply to an email. Finds the original email by sender or subject "
                    "and sends a reply. Use this when the user says 'reply to' or 'respond to'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search by sender email or subject to find which email to reply to",
                        },
                        "body": {"type": "string", "description": "The reply message body"},
                        "folder": {"type": "string", "description": "Mail folder (default: INBOX)"},
                    },
                    "required": ["query", "body"],
                },
            },
        ),
        execute=_reply_email,
    )


def create_read_emails_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "read_emails",
                "description": (
                    "Read recent emails from the user's inbox. "
                    "Email credentials are already configured in the environment. "
                    "When the user asks to read emails, call this tool immediately "
                    "without asking for credentials."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "folder": {"type": "string", "description": "Mail folder (default: INBOX)"},
                        "max": {"type": "number", "description": "Max emails to fetch (default: 10, max: 50)"},
                        "since_days": {
                            "type": "number",
                            "description": (
                                "Look back days (default: 1). Use a larger number like 7 or 30 to go further back."
                            ),
                        },
                        "from": {
                            "type": "string",
                            "description": "Filter by sender email address (e.g., 'test@gmail.com')",
                        },
                        "subject": {"type": "string", "description": "Filter by subject line keyword"},
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
