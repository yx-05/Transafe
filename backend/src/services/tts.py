"""Text-to-Speech service using edge-tts neural voice synthesis."""

import edge_tts


async def synthesize_text_to_audio(
    text: str, voice: str = "en-SG-LunaNeural"
) -> bytes:
    """Synthesize neural text-to-speech audio using edge-tts.

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
