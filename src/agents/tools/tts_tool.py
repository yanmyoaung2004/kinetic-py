"""TTS tool — convert text to speech and send as audio via Telegram."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import edge_tts

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

SANDBOX = Path("agent_sandbox")
_pending: dict[int, list[dict[str, Any]]] = {}


def get_pending_audio(chat_id: int) -> list[dict[str, Any]]:
    return _pending.pop(chat_id, [])


async def _tts_speak(args: dict[str, Any], ctx: ToolContext | None) -> str:
    text = args.get("text", "").strip()
    if not text:
        return "ERROR: 'text' is required."
    voice = args.get("voice", "en-GB-RyanNeural")

    chat_id = ctx.chat_id if ctx else 0

    # Generate MP3 audio
    audio_data = bytearray()
    rate = os.environ.get("TTS_SPEED", "+0%")
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])

    if not audio_data:
        return "ERROR: No audio generated."

    # Save to sandbox
    SANDBOX.mkdir(parents=True, exist_ok=True)
    filename = f"tts_{int(time.time() * 1000)}.mp3"
    filepath = SANDBOX / filename
    filepath.write_bytes(audio_data)

    # Queue for sending
    if chat_id:
        _pending.setdefault(chat_id, []).append({
            "filename": filename,
            "content": bytes(audio_data),
        })

    duration = len(text) / 15
    return (
        f"Audio generated: {filename}\n"
        f"Voice: {voice}\n"
        f"Duration: ~{duration:.1f}s\n"
        f"Will be sent to you."
    )


def create_tts_speak_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "tts_speak",
                "description": (
                    "Convert text to speech using edge-tts and send the audio to the user. "
                    "Call this after generating a response to deliver it as a voice message."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The text to speak"},
                        "voice": {
                            "type": "string",
                            "description": "Voice to use (default: en-GB-RyanNeural). "
                                           "Common: en-GB-ThomasNeural, en-US-AriaNeural, en-US-AndrewNeural",
                        },
                    },
                    "required": ["text"],
                },
            },
        ),
        execute=_tts_speak,
    )
