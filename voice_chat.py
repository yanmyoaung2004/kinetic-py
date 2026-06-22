"""Voice chat — system tray app with push-to-talk.
Press Ctrl+Shift+V → speak → release → hear the bot.
System tray icon shows: idle, recording, processing, speaking."""

import asyncio
import ctypes
import os
import queue
import tempfile
import threading
import time
import wave
from pathlib import Path

import edge_tts
import httpx
import keyboard
import pyaudio
import pystray
import speech_recognition as sr
from PIL import Image, ImageDraw

# ── Config ─────────────────────────────────────────────
API_URL = os.environ.get("API_URL", "http://localhost:18789/api/chat")
PUSH_TO_TALK_KEY = os.environ.get("PTT_KEY", "alt+v")
# ── Usage ──
# Change hotkey by setting PTT_KEY env var, e.g.:
#   PTT_KEY=ctrl+shift+v   (default on many systems)
#   PTT_KEY=ctrl+`         (tilde key)
#   PTT_KEY=ctrl+alt+v     (safe alternative)
#   PTT_KEY=f1             (function key)
# ───────────

# Show active hotkey (useful for debugging when console is hidden)
_print_debug = os.environ.get("HIDE_CONSOLE", "1").lower() not in ("1", "true", "yes")
if _print_debug:
    print(f"Hotkey: {PUSH_TO_TALK_KEY}")
VOICE = os.environ.get("TTS_VOICE", "en-GB-RyanNeural")
SPEED = os.environ.get("TTS_SPEED", "+20%")

RECORD_FORMAT = pyaudio.paInt16
RECORD_CHANNELS = 1
RECORD_RATE = 16000
RECORD_CHUNK = 1024
HIDE_CONSOLE = os.environ.get("HIDE_CONSOLE", "1").lower() in ("1", "true", "yes")

# ── Status ─────────────────────────────────────────────
IDLE = 0
RECORDING = 1
PROCESSING = 2
SPEAKING = 3

_status_names = {IDLE: "Idle", RECORDING: "Recording", PROCESSING: "Processing", SPEAKING: "Speaking"}
_status_colors = {IDLE: "#ffffff", RECORDING: "#ff4444", PROCESSING: "#ffaa00", SPEAKING: "#44ff44"}
_status_queue: queue.Queue[int] = queue.Queue()
_tray_icon: pystray.Icon | None = None


_LOGO_PATH = Path(__file__).parent / "images" / "logo-white.png"
_LOGO_CACHE: Image.Image | None = None


def _make_icon(color_hex: str) -> Image.Image:
    global _LOGO_CACHE
    if _LOGO_CACHE is None and _LOGO_PATH.exists():
        _LOGO_CACHE = Image.open(str(_LOGO_PATH)).convert("RGBA").resize((64, 64), Image.LANCZOS)

    if _LOGO_CACHE:
        img = _LOGO_CACHE.copy()
    else:
        img = Image.new("RGBA", (64, 64), (30, 30, 30, 255))

    # Draw status dot (bottom-right corner)
    r, g, b = int(color_hex[1:3], 16), int(color_hex[3:5], 16), int(color_hex[5:7], 16)
    draw = ImageDraw.Draw(img)
    draw.ellipse([46, 46, 62, 62], fill=(r, g, b, 255))
    # Thin border around the dot
    draw.ellipse([46, 46, 62, 62], outline=(255, 255, 255, 200), width=1)
    return img


def _set_status(s: int) -> None:
    """Update tray icon from any thread."""
    _status_queue.put(s)


def _run_tray() -> None:
    global _tray_icon
    icon_img = _make_icon(_status_colors[IDLE])
    menu = pystray.Menu(pystray.MenuItem("Quit", _on_quit))
    icon = pystray.Icon("kinetic_voice", icon_img, "K.I.N.E.T.I.C. Voice", menu)
    _tray_icon = icon

    # Poll for status updates
    def _poll():
        while True:
            try:
                s = _status_queue.get(timeout=0.2)
                icon.icon = _make_icon(_status_colors.get(s, _status_colors[IDLE]))
                icon.title = f"K.I.N.E.T.I.C. Voice — {_status_names.get(s, '?')}"
            except queue.Empty:
                pass
            if not icon.visible:
                break

    threading.Thread(target=_poll, daemon=True).start()
    icon.run()


def _on_quit() -> None:
    os._exit(0)


# ── Audio helpers ──────────────────────────────────────

def _record_to_wav() -> Path | None:
    p = pyaudio.PyAudio()
    stream = p.open(
        format=RECORD_FORMAT, channels=RECORD_CHANNELS, rate=RECORD_RATE,
        input=True, frames_per_buffer=RECORD_CHUNK,
    )
    sample_width = p.get_sample_size(RECORD_FORMAT)

    keyboard.wait(PUSH_TO_TALK_KEY)
    _set_status(RECORDING)

    frames: list[bytes] = []
    while keyboard.is_pressed(PUSH_TO_TALK_KEY):
        frames.append(stream.read(RECORD_CHUNK, exception_on_overflow=False))

    stream.stop_stream()
    stream.close()
    p.terminate()

    if len(frames) < 5:
        _set_status(IDLE)
        return None

    path = Path(tempfile.gettempdir()) / f"voice_{int(time.time())}.wav"
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(RECORD_CHANNELS)
        wf.setsampwidth(sample_width)
        wf.setframerate(RECORD_RATE)
        wf.writeframes(b"".join(frames))

    return path


async def _stt(wav_path: Path) -> str:
    try:
        r = sr.Recognizer()
        with sr.AudioFile(str(wav_path)) as source:
            audio = r.record(source)
        text = await asyncio.get_event_loop().run_in_executor(None, r.recognize_google, audio)
        return text
    except sr.UnknownValueError:
        return ""
    except Exception as e:
        print(f"STT error: {e}")
        return ""


async def _query_bot(text: str) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(API_URL, json={"message": text, "voice": True})
        resp.raise_for_status()
        return resp.json().get("response", "")


async def _speak(text: str) -> None:
    if not text:
        return

    import re as _re
    text = _re.sub(r"\*{1,2}(.*?)\*{1,2}", r"\1", text)
    text = text.replace("*", "")

    audio = bytearray()
    comm = edge_tts.Communicate(text, VOICE, rate=SPEED)
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    if not audio:
        return

    tmp = Path(tempfile.gettempdir())
    mp3 = tmp / "vout.mp3"
    raw = tmp / "vout.raw"
    mp3.write_bytes(audio)

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", str(mp3), "-f", "s16le",
        "-ar", "24000", "-ac", "1", str(raw),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await proc.wait()
    mp3.unlink(missing_ok=True)

    pcm = raw.read_bytes()
    raw.unlink(missing_ok=True)

    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=24000, output=True)
    for i in range(0, len(pcm), 4096):
        stream.write(pcm[i:i + 4096])
    stream.stop_stream()
    stream.close()
    p.terminate()


# ── Main loop ──────────────────────────────────────────

async def _voice_loop() -> None:
    while True:
        wav = await asyncio.get_event_loop().run_in_executor(None, _record_to_wav)
        if wav is None:
            _set_status(IDLE)
            continue

        _set_status(PROCESSING)
        text = await _stt(wav)
        wav.unlink(missing_ok=True)

        if not text:
            _set_status(IDLE)
            continue

        reply = await _query_bot(text)

        if not reply:
            _set_status(IDLE)
            continue

        _set_status(SPEAKING)
        await _speak(reply)
        _set_status(IDLE)


def main() -> None:
    if HIDE_CONSOLE:
        ctypes.windll.user32.ShowWindow(
            ctypes.windll.kernel32.GetConsoleWindow(), 0
        )

    thread = threading.Thread(target=_run_tray, daemon=True)
    thread.start()

    asyncio.run(_voice_loop())


if __name__ == "__main__":
    main()
