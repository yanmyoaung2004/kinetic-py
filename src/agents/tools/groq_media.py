"""Groq multimodal — vision (image analysis) and voice (speech-to-text)."""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx

GROQ_BASE = "https://api.groq.com/openai/v1"
VISION_MODEL = os.environ.get("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")


def _groq_key() -> str:
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        raise ValueError("GROQ_API_KEY not set in .env")
    return key


async def analyze_image(image_path: str | Path, prompt: str = "What's in this image?") -> str:
    """Send an image to Groq's vision model and get a description."""
    path = Path(image_path)
    if not path.exists():
        return f"ERROR: Image not found: {image_path}"

    with open(path, "rb") as f:
        img_bytes = f.read()

    b64 = base64.b64encode(img_bytes).decode("utf-8")
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    data_url = f"data:{mime};base64,{b64}"

    headers = {
        "Authorization": f"Bearer {_groq_key()}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0.5,
        "max_tokens": 512,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GROQ_BASE}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"ERROR analyzing image: {e}"


async def transcribe_audio(audio_path: str | Path) -> str:
    """Transcribe audio file using Groq's Whisper API."""
    path = Path(audio_path)
    if not path.exists():
        return f"ERROR: Audio file not found: {audio_path}"

    headers = {"Authorization": f"Bearer {_groq_key()}"}

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            with open(path, "rb") as f:
                files = {"file": (path.name, f, "audio/ogg")}
                data = {"model": "whisper-large-v3-turbo", "response_format": "json"}
                resp = await client.post(
                    f"{GROQ_BASE}/audio/transcriptions",
                    headers=headers,
                    data=data,
                    files=files,
                )
                resp.raise_for_status()
                result = resp.json()
                return result.get("text", "").strip()
    except Exception as e:
        return f"ERROR transcribing audio: {e}"
