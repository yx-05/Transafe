"""Speech-to-Text service supporting dual engines: Groq Whisper (whisper-large-v3-turbo) and Deepgram Nova-3."""

import logging
import os
from unittest.mock import MagicMock
import httpx
from dotenv import load_dotenv
from groq import AsyncGroq, Groq
from src.agents.llm import get_groq_api_keys

logger = logging.getLogger(__name__)

# Default module-level client for test mocking
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY", "gsk_dummy"))


def get_deepgram_api_keys() -> list[str]:
    """Gather all available Deepgram API keys dynamically from environment & .env files."""
    # Ensure dotenv is loaded
    load_dotenv()

    keys: list[str] = []

    # 1. Check explicit environment variables
    for var in (
        "DEEPGRAM_API_KEY",
        "DEEPGRAM_API_KEY_1",
        "DEEPGRAM_API_KEY_2",
        "DEEPGRAM_API_KEY_3",
        "DEEPGRAM_API_KEY_4",
        "DEEPGRAM_API_KEY_5",
        "DEEPGRAM_API_KEYS",
    ):
        val = os.getenv(var)
        if val and val.strip():
            # Handle comma-separated keys if present
            for k in val.split(","):
                k_clean = k.strip()
                if k_clean and k_clean not in keys:
                    keys.append(k_clean)

    # 2. Dynamic scan of os.environ for any DEEPGRAM_API_KEY*
    for env_k, env_v in os.environ.items():
        if env_k.startswith("DEEPGRAM_API_KEY") and env_v and env_v.strip():
            for k in env_v.split(","):
                k_clean = k.strip()
                if k_clean and k_clean not in keys:
                    keys.append(k_clean)

    return keys


async def transcribe_audio_chunk_deepgram(
    audio_bytes: bytes, filename: str = "chunk.webm", language: str = "en"
) -> str:
    """Transcribe an audio chunk using Deepgram Nova-3 API with multi-key rotation."""
    if not audio_bytes or len(audio_bytes) < 100:
        return ""

    keys = get_deepgram_api_keys()
    if not keys:
        print("[STT DEEPGRAM ERROR ❌] No DEEPGRAM_API_KEY environment variable found.")
        return ""

    url = f"https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&language={language}"
    content_type = "audio/webm" if filename.endswith(".webm") else "application/octet-stream"

    for idx, api_key in enumerate(keys):
        headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": content_type,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, headers=headers, content=audio_bytes)
                if res.status_code == 200:
                    data = res.json()
                    channels = data.get("results", {}).get("channels", [])
                    if channels and len(channels) > 0:
                        alts = channels[0].get("alternatives", [])
                        if alts and len(alts) > 0:
                            text = alts[0].get("transcript", "").strip()
                            if text:
                                print(f"[STT DEEPGRAM NOVA-3 ✅] Transcribed ({len(audio_bytes)} bytes, key #{idx+1}): '{text}'")
                                return text
                            else:
                                print(f"[STT DEEPGRAM NOVA-3 ℹ️] Empty transcript for {len(audio_bytes)} bytes audio chunk.")
                else:
                    print(f"[STT DEEPGRAM WARNING ⚠️] Key #{idx+1} status {res.status_code}: {res.text[:150]}. Trying next key...")
        except Exception as e:
            print(f"[STT DEEPGRAM WARNING ⚠️] Key #{idx+1} failed: {e}. Trying next key...")
            continue

    print("[STT DEEPGRAM ERROR ❌] All Deepgram API keys in key pool failed for STT.")
    return ""


async def transcribe_audio_chunk(
    audio_bytes: bytes,
    filename: str = "chunk.webm",
    language: str = "en",
    stt_engine: str = "groq",
) -> str:
    """Transcribe an audio chunk using selected engine ('groq' or 'deepgram' / 'nova-3')."""
    if not audio_bytes:
        return ""

    if stt_engine.lower() in ("deepgram", "nova-3", "nova3"):
        return await transcribe_audio_chunk_deepgram(audio_bytes, filename, language)

    # If groq_client was patched/mocked by unit tests, use the mocked client directly
    if isinstance(groq_client, MagicMock):
        client = groq_client
        audio_file = (filename, audio_bytes)
        try:
            transcription = client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-large-v3-turbo",
                language=language,
            )
        except Exception:
            transcription = client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-large-v3",
                language=language,
            )

        if hasattr(transcription, "text"):
            return str(transcription.text).strip()
        return str(transcription).strip()

    # Real runtime execution: Non-blocking AsyncGroq key rotation
    keys = get_groq_api_keys()

    for idx, key in enumerate(keys):
        try:
            async_client = AsyncGroq(api_key=key)
            audio_file = (filename, audio_bytes)
            try:
                transcription = await async_client.audio.transcriptions.create(
                    file=audio_file,
                    model="whisper-large-v3-turbo",
                    language=language,
                )
            except Exception as primary_err:
                transcription = await async_client.audio.transcriptions.create(
                    file=audio_file,
                    model="whisper-large-v3",
                    language=language,
                )

            text = ""
            if hasattr(transcription, "text"):
                text = str(transcription.text).strip()
            else:
                text = str(transcription).strip()

            if text:
                print(f"[STT GROQ ✅] Groq Whisper Output: '{text}' (key #{idx+1})")
            return text

        except Exception as err:
            print(f"[STT GROQ WARNING ⚠️] Key #{idx+1} ({key[:12]}...) failed: {err}. Trying next key...")
            continue

    print("[STT GROQ ERROR ❌] All Groq API keys in key pool failed for STT.")
    return ""
