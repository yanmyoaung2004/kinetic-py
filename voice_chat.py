"""Voice chat — push-to-talk with Windows built-in STT, bot API, and edge-tts.
Press Ctrl+Shift+V → speak → release → hear the bot."""

import asyncio
import os
import tempfile
import time
import wave
from pathlib import Path

import edge_tts
import httpx
import keyboard
import pyaudio

# ── Config ─────────────────────────────────────────────
API_URL = "http://localhost:18789/api/chat"
PUSH_TO_TALK_KEY = "ctrl+shift+v"
VOICE = os.environ.get("TTS_VOICE", "en-GB-RyanNeural")
SPEED = os.environ.get("TTS_SPEED", "+20%")

RECORD_FORMAT = pyaudio.paInt16
RECORD_CHANNELS = 1
RECORD_RATE = 16000
RECORD_CHUNK = 1024

# ── Audio helpers ──────────────────────────────────────

def _record_to_wav() -> Path | None:
    """Record mic while hotkey is held. Returns path to WAV file or None."""
    p = pyaudio.PyAudio()
    stream = p.open(
        format=RECORD_FORMAT,
        channels=RECORD_CHANNELS,
        rate=RECORD_RATE,
        input=True,
        frames_per_buffer=RECORD_CHUNK,
    )

    sample_width = p.get_sample_size(RECORD_FORMAT)

    print(f"\n[MIC] Press {PUSH_TO_TALK_KEY} to speak...", end="", flush=True)
    keyboard.wait(PUSH_TO_TALK_KEY)

    frames: list[bytes] = []

    print("\r[MIC] Recording... (release to stop)  ", flush=True)

    while keyboard.is_pressed(PUSH_TO_TALK_KEY):
        data = stream.read(RECORD_CHUNK, exception_on_overflow=False)
        frames.append(data)

    stream.stop_stream()
    stream.close()
    p.terminate()

    if len(frames) < 5:
        print("   (too short, ignored)")
        return None

    dur = len(frames) * RECORD_CHUNK / RECORD_RATE
    print(f"   Recorded {dur:.1f}s of audio")

    path = Path(tempfile.gettempdir()) / f"voice_{int(time.time())}.wav"
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(RECORD_CHANNELS)
        wf.setsampwidth(sample_width)
        wf.setframerate(RECORD_RATE)
        wf.writeframes(b"".join(frames))

    return path


async def _stt(wav_path: Path) -> str:
    """Speech-to-text via Windows built-in System.Speech (PowerShell)."""
    ps = (
        'Add-Type -AssemblyName System.Speech;'
        f'$e = New-Object System.Speech.Recognition.SpeechRecognitionEngine;'
        f'$e.SetInputToWaveFile("{wav_path}");'
        '$e.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar));'
        '$r = $e.Recognize();'
        'if ($r) { Write-Output $r.Text }'
    )
    proc = await asyncio.create_subprocess_exec(
        "powershell", "-NoProfile", "-Command", ps,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    text = stdout.decode("utf-8", errors="replace").strip()
    return text


async def _query_bot(text: str) -> str:
    """Send text to bot API, get response."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(API_URL, json={"message": text})
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")


async def _speak(text: str) -> None:
    """Text-to-speech via edge-tts, play through speakers."""
    if not text:
        return

    # Collect MP3 audio
    audio = bytearray()
    comm = edge_tts.Communicate(text, VOICE, rate=SPEED)
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])

    if not audio:
        return

    # Decode MP3 to PCM via ffmpeg
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

    # Play
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=24000, output=True)
    chunk = 4096
    for i in range(0, len(pcm), chunk):
        stream.write(pcm[i:i + chunk])
    stream.stop_stream()
    stream.close()
    p.terminate()


# ── Main ───────────────────────────────────────────────

async def main():
    print("=" * 50)
    print("  K.I.N.E.T.I.C. Voice Chat")
    print("=" * 50)
    print(f"  Hotkey: {PUSH_TO_TALK_KEY}")
    print(f"  Voice:  {VOICE}")
    print(f"  Speed:  {SPEED}")
    print(f"  API:    {API_URL}")
    print("=" * 50)
    print()

    while True:
        wav = _record_to_wav()
        if wav is None:
            continue

        print("   Transcribing...", end=" ", flush=True)
        text = await _stt(wav)
        wav.unlink(missing_ok=True)

        if not text:
            print("(could not recognize)")
            continue

        print(f"\n   You: {text}")

        print("   Thinking...", end=" ", flush=True)
        reply = await _query_bot(text)

        print(f"\n   Bot: {reply[:150]}..." if len(reply) > 150 else f"\n   Bot: {reply}")

        print("   Speaking...", flush=True)
        await _speak(reply)
        print("   Done.\n")


if __name__ == "__main__":
    asyncio.run(main())
