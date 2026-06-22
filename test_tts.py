"""Real-time TTS via edge-tts + PyAudio — plays through your speakers."""

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

import edge_tts
import pyaudio


async def main():
    # Parse args: text and optional voice
    args = sys.argv[1:]
    voice = "en-GB-RyanNeural"
    text_parts = []
    for a in args:
        if a.startswith("--voice="):
            voice = a.split("=", 1)[1]
        else:
            text_parts.append(a)
    text = " ".join(text_parts) or "Hello, I am your personal assistant."

    print(f"Voice: {voice}")
    print(f"Text: {len(text)} chars")

    print(f"Generating speech for {len(text)} chars...")

    # Collect all MP3 audio data
    audio_data = bytearray()
    communicate = edge_tts.Communicate(text, voice, rate="+20%")
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])

    if not audio_data:
        print("No audio generated.")
        return

    # Decode MP3 to raw PCM via ffmpeg (no WAV header)
    tmp_dir = Path(tempfile.gettempdir())
    mp3_path = tmp_dir / "tts_input.mp3"
    pcm_path = tmp_dir / "tts_output.raw"
    mp3_path.write_bytes(audio_data)

    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3_path), "-f", "s16le", "-ar", "24000",
         "-ac", "1", str(pcm_path)],
        capture_output=True, check=True,
    )

    pcm_data = pcm_path.read_bytes()
    mp3_path.unlink(missing_ok=True)
    pcm_path.unlink(missing_ok=True)

    # Play through speakers
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=24000, output=True)
    chunk_size = 4096
    for i in range(0, len(pcm_data), chunk_size):
        stream.write(pcm_data[i:i + chunk_size])
    stream.stop_stream()
    stream.close()
    p.terminate()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())

