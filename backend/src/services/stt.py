"""Speech-to-Text service using Groq Whisper (whisper-large-v3)."""

import os

from groq import Groq

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY", "gsk_dummy"))


async def transcribe_audio_chunk(audio_bytes: bytes, language: str = "en") -> str:
    """Transcribe an audio chunk using Groq Whisper (whisper-large-v3)."""
    if not audio_bytes:
        return ""

    audio_file = ("chunk.wav", audio_bytes)
    transcription = groq_client.audio.transcriptions.create(
        file=audio_file,
        model="whisper-large-v3",
        language=language,
    )

    if hasattr(transcription, "text"):
        return str(transcription.text)
    return str(transcription)
