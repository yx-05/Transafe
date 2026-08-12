"""Text-to-Speech service: ElevenLabs primary with edge-tts (Microsoft neural) fallback."""

import asyncio
import logging
import os
from typing import Any

import edge_tts
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Fallback voice for edge-tts (Microsoft neural) — matches the AUTO_TALK voice
DEFAULT_EDGE_VOICE = "ms-MY-YasminNeural"

# Ensure .env is loaded BEFORE reading the voice env vars below. main.py calls
# load_dotenv() after importing this module, so without this the voice IDs would
# silently fall back to defaults (and the paid voice would never be used).
load_dotenv()

# ElevenLabs defaults; overridable via env vars.
# - ELEVENLABS_VOICE_ID: premade "Daniel" (onwK4e9ZLuTAKqWW03F9) — verified working
#   on the free plan. Used as the FALLBACK voice.
# - ELEVENLABS_VOICE_ID_PAID: a library/paid voice (e.g. O8ykjWKd0RjX6e5EyDuE).
#   Synthesis tries this FIRST; if the active key cannot access it (HTTP 402
#   paid_plan_required / 401 / 403 / 404) it falls back to the free voice.
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")
ELEVENLABS_VOICE_ID_PAID = os.getenv("ELEVENLABS_VOICE_ID_PAID", ELEVENLABS_VOICE_ID)
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")
ELEVENLABS_OUTPUT_FORMAT = os.getenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")


def get_elevenlabs_api_keys() -> list[str]:
    """Gather all available ElevenLabs API keys dynamically from environment & .env files.

    Mirrors the Groq/Deepgram/Tavily rotation pools: reads ``ELEVENLAB_API_KEY``,
    ``ELEVENLAB_API_KEY_1..N`` and comma-separated ``ELEVENLAB_API_KEYS``.
    """
    # Ensure dotenv is loaded
    load_dotenv()

    keys: list[str] = []

    # 1. Check explicit environment variables
    for var in (
        "ELEVENLAB_API_KEY",
        "ELEVENLAB_API_KEY_1",
        "ELEVENLAB_API_KEY_2",
        "ELEVENLAB_API_KEY_3",
        "ELEVENLAB_API_KEY_4",
        "ELEVENLAB_API_KEY_5",
        "ELEVENLAB_API_KEYS",
    ):
        val = os.getenv(var)
        if val and val.strip():
            # Handle comma-separated keys if present
            for k in val.split(","):
                k_clean = k.strip()
                if k_clean and k_clean not in keys and k_clean.startswith("sk_"):
                    keys.append(k_clean)

    # 2. Dynamic scan of os.environ for any ELEVENLAB_API_KEY*
    for env_k, env_v in os.environ.items():
        if env_k.startswith("ELEVENLAB_API_KEY") and env_v and env_v.strip():
            for k in env_v.split(","):
                k_clean = k.strip()
                if k_clean and k_clean not in keys and k_clean.startswith("sk_"):
                    keys.append(k_clean)

    return keys


async def synthesize_text_to_audio_elevenlabs(
    text: str,
    voice_id: str | None = None,
    model_id: str | None = None,
    output_format: str | None = None,
) -> bytes:
    """Synthesize speech with ElevenLabs, rotating through the API key pool.

    Returns raw audio bytes (MP3). Raises the last error if ALL keys fail so the
    caller can fall back to edge-tts (Microsoft neural).
    """
    if not text:
        return b""

    # Lazy import so edge-tts fallback still works even if the SDK is missing
    from elevenlabs.client import ElevenLabs  # type: ignore[import-untyped]

    keys = get_elevenlabs_api_keys()
    if not keys:
        raise RuntimeError("No ELEVENLAB_API_KEY environment variable found.")

    # Explicit voice override wins; otherwise try the PAID voice first and fall
    # back to the free/premade voice when the active key cannot access it.
    if voice_id:
        voice_candidates = [voice_id]
    else:
        voice_candidates = list(
            dict.fromkeys([ELEVENLABS_VOICE_ID_PAID, ELEVENLABS_VOICE_ID])
        )

    last_error: Exception | None = None
    for idx, api_key in enumerate(keys):
        try:
            client = ElevenLabs(api_key=api_key)
            audio_bytes: bytes | None = None
            for candidate in voice_candidates:
                try:
                    audio_stream = client.text_to_speech.convert(
                        text=text,
                        voice_id=candidate,
                        model_id=model_id or ELEVENLABS_MODEL_ID,
                        output_format=output_format or ELEVENLABS_OUTPUT_FORMAT,
                    )
                    # convert() returns an iterator of bytes; join in a thread
                    # to avoid blocking the event loop during the HTTP stream.
                    candidate_bytes = await asyncio.to_thread(
                        lambda: b"".join(audio_stream)
                    )
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    logger.warning(
                        "ElevenLabs TTS voice '%s' failed with key #%d: %s",
                        candidate, idx + 1, exc,
                    )
                    continue
                if candidate_bytes:
                    audio_bytes = candidate_bytes
                    break
            if audio_bytes:
                logger.info(
                    "ElevenLabs TTS ok with key #%d (%d bytes)",
                    idx + 1,
                    len(audio_bytes),
                )
                return audio_bytes
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning(
                "ElevenLabs TTS failed with key #%d: %s", idx + 1, exc
            )
            continue

    raise RuntimeError(f"All ElevenLabs API keys failed: {last_error}")


async def synthesize_agent_speech(
    text: str,
    voice: str = DEFAULT_EDGE_VOICE,
    use_elevenlabs: bool = True,
) -> bytes:
    """Synthesize agent speech: ElevenLabs primary, Microsoft edge-tts fallback.

    Falls back to edge-tts (e.g. ``ms-MY-YasminNeural``) automatically when
    ElevenLabs is unreachable or all keys are out of credits.
    """
    if not text:
        return b""

    if use_elevenlabs:
        try:
            return await synthesize_text_to_audio_elevenlabs(text)
        except Exception as err:  # noqa: BLE001
            logger.warning(
                "ElevenLabs unavailable (%s) — falling back to Microsoft edge-tts.",
                err,
            )

    return await synthesize_text_to_audio(text, voice=voice)


async def synthesize_text_to_audio(
    text: str, voice: str = "en-SG-LunaNeural"
) -> bytes:
    """Synthesize neural text-to-speech audio using edge-tts (Microsoft).

    Supports voices such as 'en-SG-LunaNeural' and 'ms-MY-YasminNeural'.
    """
    if not text:
        return b""

    communicate = edge_tts.Communicate(text, voice)
    audio_data = bytearray()
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            data = chunk.get("data")
            if isinstance(data, (bytes, bytearray)):
                audio_data.extend(data)

    return bytes(audio_data)
