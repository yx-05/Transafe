"""Vision service using Groq multimodal models for OCR + phishing image analysis.

- ``extract_text_from_image`` — OCR via Groq llama-3.2-11b-vision-preview.
- ``analyze_image`` — qwen3.6-27b extracts the text AND describes visual
  phishing indicators (fake branding, urgency banners, lookalike login forms,
  QR codes). Falls back to llama-3.2-11b-vision-preview, then to plain OCR.
"""

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from groq import Groq

from src.agents.llm import extract_json_object

logger = logging.getLogger(__name__)


def _get_groq_client() -> Groq:
    """Build the Groq client lazily so the API key is read AFTER dotenv loads.

    main.py imports this module before calling ``load_dotenv()``, so a
    module-level client would be constructed with a missing/"gsk_dummy" key
    and every multimodal call would fail with HTTP 401.
    """
    load_dotenv()
    return Groq(api_key=os.getenv("GROQ_API_KEY") or "gsk_dummy")

# Primary multimodal model for image analysis; llama vision is the fallback.
QWEN_IMAGE_MODEL = "qwen/qwen3.6-27b"
FALLBACK_IMAGE_MODEL = "llama-3.2-11b-vision-preview"

_IMAGE_ANALYSIS_PROMPT = (
    "Analyze this screenshot for phishing indicators. "
    'Respond with STRICT JSON only, no markdown, in this exact shape: '
    '{"extracted_text": "<all visible text, verbatim>", '
    '"description": "<2-3 sentence summary of visual phishing indicators: fake '
    'branding, urgency/threat banners, lookalike login forms, suspicious QR '
    'codes, sender spoofing, etc. Use empty string if the image looks benign."}'
)


def _normalize_image_url(base64_image: str) -> str:
    """Return a data-URL for Groq multimodal input (adds the jpeg prefix if missing)."""
    if base64_image.startswith("data:"):
        return base64_image
    return f"data:image/jpeg;base64,{base64_image}"


def _call_multimodal(model: str, prompt: str, image_url: str) -> str:
    """Run a single multimodal chat completion and return the text content."""
    response = _get_groq_client().chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    },
                ],
            }
        ],
        temperature=0.0,
    )
    if response.choices and len(response.choices) > 0:
        return response.choices[0].message.content or ""
    return ""


def extract_text_from_image(base64_image: str) -> str:
    """Extract text from base64 screenshot data using Groq Vision (llama-3.2-11b-vision-preview)."""
    if not base64_image:
        return ""

    image_url = _normalize_image_url(base64_image)
    return _call_multimodal(
        FALLBACK_IMAGE_MODEL,
        "Extract all text from this image exactly as shown. Return only the extracted text.",
        image_url,
    )


def analyze_image(base64_image: str) -> dict[str, str]:
    """Analyze a base64 screenshot for phishing.

    Returns ``{"extracted_text": ..., "description": ...}`` where ``description``
    summarizes visual phishing indicators. Uses qwen3.6-27b (Groq) with a
    llama-3.2-11b-vision-preview fallback. Never raises — on total failure an
    empty result dict is returned so callers can fall back to raw content.
    """
    if not base64_image:
        return {"extracted_text": "", "description": ""}

    image_url = _normalize_image_url(base64_image)
    for model in (QWEN_IMAGE_MODEL, FALLBACK_IMAGE_MODEL):
        try:
            content = _call_multimodal(model, _IMAGE_ANALYSIS_PROMPT, image_url)
        except Exception as err:  # noqa: BLE001
            logger.warning(f"Multimodal model {model} failed for image analysis: {err}")
            continue

        if not content:
            continue

        parsed = extract_json_object(content)
        if isinstance(parsed, dict):
            return {
                "extracted_text": str(parsed.get("extracted_text") or ""),
                "description": str(parsed.get("description") or ""),
            }

        # Non-JSON output: treat the raw response as the extracted text.
        return {"extracted_text": content.strip(), "description": ""}

    return {"extracted_text": "", "description": ""}
