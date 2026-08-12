"""Deepgram Nova-3 streaming STT client with real-time interim results.

Streams WebM/Opus chunks (as produced by the browser MediaRecorder) to
Deepgram's live listen endpoint and surfaces interim + final transcripts.
This avoids the malformed-WebM problem of the batch API: chunks are forwarded
in order with no header reconstruction, and interim results give a smooth,
real-time captioning experience.
"""

import json
import logging
import os

import websockets

from src.services.stt import get_deepgram_api_keys

logger = logging.getLogger(__name__)

DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"


def _build_query(model: str, language: str) -> str:
    params = {
        "model": model,
        "language": language,
        "smart_format": "true",
        "punctuate": "true",
        "interim_results": "true",
        "container": "webm",
        "encoding": "opus",
        "endpointing": "500",
    }
    return "&".join(f"{k}={v}" for k, v in params.items())


class DeepgramStreamingSession:
    """A single Deepgram streaming transcription session for one call role."""

    def __init__(self, language: str = "en", model: str = "nova-3", api_key: str | None = None):
        self.language = language
        self.model = model
        self.api_key = api_key  # optional explicit key override; defaults to the pooled keys
        self._ws = None
        self._closed = False

    async def connect(self) -> None:
        """Open the Deepgram streaming WebSocket, rotating through the API key pool.

        Raises RuntimeError if no keys are configured or every key fails to connect.
        """
        if self.api_key:
            keys = [self.api_key]
        else:
            keys = get_deepgram_api_keys()
        if not keys:
            raise RuntimeError("No DEEPGRAM_API_KEY environment variable found.")

        query = _build_query(self.model, self.language)
        url = f"{DEEPGRAM_WS_URL}?{query}"
        last_err: Exception | None = None

        for idx, key in enumerate(keys):
            try:
                self._ws = await websockets.connect(
                    url,
                    additional_headers={"Authorization": f"Token {key}"},
                )
                self._closed = False
                print(f"[STT DEEPGRAM STREAM 🔑] Connected with key #{idx+1} ({key[:8]}...)")
                return
            except Exception as err:  # noqa: BLE001
                last_err = err
                print(f"[STT DEEPGRAM STREAM WARNING ⚠️] Key #{idx+1} ({key[:8]}...) connect failed: {err}. Trying next key...")
                self._ws = None

        raise RuntimeError(f"All {len(keys)} Deepgram API keys failed to connect: {last_err}")

    async def send_audio(self, chunk: bytes) -> None:
        """Forward a raw WebM/Opus chunk to Deepgram as binary audio."""
        if self._ws and not self._closed:
            await self._ws.send(chunk)

    async def receive(self) -> dict:
        """Receive the next message from Deepgram, parsed as JSON (empty dict if binary)."""
        if not self._ws:
            return {}
        raw = await self._ws.recv()
        if isinstance(raw, (bytes, bytearray)):
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}

    async def close(self) -> None:
        """Gracefully close the Deepgram stream (idempotent)."""
        if not self._ws:
            return
        try:
            await self._ws.send(json.dumps({"type": "CloseStream"}))
        except Exception:  # noqa: BLE001
            pass
        try:
            await self._ws.close()
        except Exception:  # noqa: BLE001
            pass
        self._ws = None
        self._closed = True
