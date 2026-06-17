"""Browser automation tools using Playwright."""

from __future__ import annotations

import base64
import logging
from typing import Any

from playwright.async_api import async_playwright

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

logger = logging.getLogger("kinetic.tools.browser")

# Per-agent browser sessions (keyed by agent_id or conversation context)
_browser_sessions: dict[str, dict[str, Any]] = {}


def _session_key(agent_id: str, ctx: ToolContext | None) -> str:
    return f"{agent_id}_{ctx.chat_id if ctx else 'default'}"


async def _get_page(agent_id: str, ctx: ToolContext | None) -> Any:
    key = _session_key(agent_id, ctx)
    session = _browser_sessions.get(key)
    if session and session.get("page") and not session["page"].is_closed():
        return session["page"]
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()
    _browser_sessions[key] = {"playwright": pw, "browser": browser, "page": page}
    return page


async def close_browser(agent_id: str, ctx: ToolContext | None = None) -> str:
    key = _session_key(agent_id, ctx)
    session = _browser_sessions.pop(key, None)
    if session:
        try:
            await session["page"].close()
        except Exception:
            pass
        try:
            await session["browser"].close()
        except Exception:
            pass
        try:
            await session["playwright"].stop()
        except Exception:
            pass
        return "Browser closed."
    return "No browser session found."


async def _browser_navigate(args: dict[str, Any], ctx: ToolContext | None) -> str:
    url = args.get("url", "")
    if not url:
        return "ERROR: 'url' parameter is required."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    agent_id = getattr(ctx, "_agent_id", "main") if ctx else "main"
    page = await _get_page(agent_id, ctx)
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        title = await page.title()
        status = response.status if response else "?"
        return f"Navigated to {url}\nTitle: {title}\nStatus: {status}\nURL: {page.url}"
    except Exception as e:
        return f"ERROR navigating to {url}: {e}"


async def _browser_click(args: dict[str, Any], ctx: ToolContext | None) -> str:
    selector = args.get("selector", "")
    if not selector:
        return "ERROR: 'selector' parameter is required."
    agent_id = getattr(ctx, "_agent_id", "main") if ctx else "main"
    page = await _get_page(agent_id, ctx)
    try:
        await page.click(selector, timeout=5000)
        return f"Clicked '{selector}'"
    except Exception as e:
        return f"ERROR clicking '{selector}': {e}"


async def _browser_fill(args: dict[str, Any], ctx: ToolContext | None) -> str:
    selector = args.get("selector", "")
    value = args.get("value", "")
    if not selector:
        return "ERROR: 'selector' parameter is required."
    agent_id = getattr(ctx, "_agent_id", "main") if ctx else "main"
    page = await _get_page(agent_id, ctx)
    try:
        await page.fill(selector, value, timeout=5000)
        return f"Filled '{selector}' with '{value[:100]}'"
    except Exception as e:
        return f"ERROR filling '{selector}': {e}"


async def _browser_extract(args: dict[str, Any], ctx: ToolContext | None) -> str:
    selector = args.get("selector", "")
    agent_id = getattr(ctx, "_agent_id", "main") if ctx else "main"
    page = await _get_page(agent_id, ctx)
    if selector:
        try:
            elements = await page.query_selector_all(selector)
            if not elements:
                return f"No elements found for '{selector}'"
            texts = [await el.inner_text() for el in elements[:20]]
            return "\n".join(texts) if texts else "(empty)"
        except Exception as e:
            return f"ERROR extracting '{selector}': {e}"
    try:
        text = await page.inner_text("body")
        return text[:10000]
    except Exception as e:
        return f"ERROR extracting body: {e}"


async def _browser_html(args: dict[str, Any], ctx: ToolContext | None) -> str:
    agent_id = getattr(ctx, "_agent_id", "main") if ctx else "main"
    page = await _get_page(agent_id, ctx)
    try:
        html = await page.content()
        return html[:10000]
    except Exception as e:
        return f"ERROR getting HTML: {e}"


async def _browser_screenshot(args: dict[str, Any], ctx: ToolContext | None) -> str:
    agent_id = getattr(ctx, "_agent_id", "main") if ctx else "main"
    page = await _get_page(agent_id, ctx)
    try:
        buf = await page.screenshot(full_page=True)
        b64 = base64.b64encode(buf).decode()
        return f"[Screenshot data:image/png;base64,{b64[:100]}... ({len(buf)} bytes)]"
    except Exception as e:
        return f"ERROR taking screenshot: {e}"


async def _browser_close(args: dict[str, Any], ctx: ToolContext | None) -> str:
    agent_id = getattr(ctx, "_agent_id", "main") if ctx else "main"
    return await close_browser(agent_id, ctx)


# ── Tool factories ──


def create_browser_navigate_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "browser_navigate",
                "description": "Navigate to a URL in the browser. Opens a new browser if none exists.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to navigate to (e.g., 'https://example.com')",
                        },
                    },
                    "required": ["url"],
                },
            },
        ),
        execute=_browser_navigate,
    )


def create_browser_click_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "browser_click",
                "description": "Click an element on the page by CSS selector.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector (e.g., '#submit', '.btn', 'a[href*=\"login\"]')",
                        },
                    },
                    "required": ["selector"],
                },
            },
        ),
        execute=_browser_click,
    )


def create_browser_fill_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "browser_fill",
                "description": "Fill an input field on the page by CSS selector.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector for the input element"},
                        "value": {"type": "string", "description": "The text to type into the field"},
                    },
                    "required": ["selector", "value"],
                },
            },
        ),
        execute=_browser_fill,
    )


def create_browser_extract_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "browser_extract",
                "description": (
                    "Extract text from the page. Provide a CSS selector "
                    "to extract specific elements, or omit to get all body text."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "Optional CSS selector (omit to get full page text)",
                        },
                    },
                },
            },
        ),
        execute=_browser_extract,
    )


def create_browser_screenshot_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "browser_screenshot",
                "description": "Take a screenshot of the current page. Returns the image as a base64 string.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        ),
        execute=_browser_screenshot,
    )


def create_browser_html_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "browser_html",
                "description": "Get the full HTML of the current page (up to 10000 chars).",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        ),
        execute=_browser_html,
    )


def create_browser_close_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "browser_close",
                "description": "Close the browser session. Call this when done browsing.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        ),
        execute=_browser_close,
    )
