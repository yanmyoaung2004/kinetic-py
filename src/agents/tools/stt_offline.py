"""Offline STT via faster-whisper — runs on CPU, no internet needed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_model = None


def _load_model() -> Any:
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _model


async def transcribe(wav_path: Path) -> str:
    """Transcribe audio file using faster-whisper. Returns text or empty string."""
    import asyncio

    model = _load_model()
    loop = asyncio.get_event_loop()

    def _run() -> str:
        segments, _ = model.transcribe(str(wav_path), language="en", beam_size=1)
        texts = [seg.text.strip() for seg in segments]
        return " ".join(texts)

    try:
        text = await loop.run_in_executor(None, _run)
        return text.strip()
    except Exception:
        return ""
