"""Vision service using DeepSeek multimodal models for OCR + phishing image analysis.

- ``extract_text_from_image`` — OCR via DeepSeek flash-vision.
- ``analyze_image`` — flash-vision extracts the text AND describes visual
  phishing indicators (fake branding, urgency banners, lookalike login forms,
  QR codes). Falls back to plain OCR.
"""

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from src.agents.llm import extract_json_object

logger = logging.getLogger(__name__)


def _get_deepseek_client() -> OpenAI:
    """Build the DeepSeek client lazily so the API key is read AFTER dotenv loads."""
    load_dotenv()
    return OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY") or "sk-dummy",
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


# DeepSeek vision model for image analysis
PRIMARY_IMAGE_MODEL = "deepseek-chat"
FALLBACK_IMAGE_MODEL = "deepseek-chat"

_IMAGE_ANALYSIS_PROMPT = (
    "Analyze this screenshot for phishing indicators. "
    'Respond with STRICT JSON only, no markdown, in this exact shape: '
    '{"extracted_text": "<all visible text, verbatim>", '
    '"description": "<2-3 sentence summary of visual phishing indicators: fake '
    'branding, urgency/threat banners, lookalike login forms, suspicious QR '
    'codes, sender spoofing, etc. Use empty string if the image looks benign."}'
)


def _normalize_image_url(base64_image: str) -> str:
    """Return a data-URL for multimodal input (adds the jpeg prefix if missing)."""
    if base64_image.startswith("data:"):
        return base64_image
    return f"data:image/jpeg;base64,{base64_image}"


def _call_multimodal(model: str, prompt: str, image_url: str) -> str:
    """Run a single multimodal chat completion and return the text content."""
    response = _get_deepseek_client().chat.completions.create(
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
    """Extract text from base64 screenshot data using DeepSeek flash-vision OCR."""
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
    summarizes visual phishing indicators. Uses DeepSeek flash-vision.
    Never raises — on total failure an empty result dict is returned so callers
    can fall back to raw content.
    """
    if not base64_image:
        return {"extracted_text": "", "description": ""}

    image_url = _normalize_image_url(base64_image)
    for model in (PRIMARY_IMAGE_MODEL, FALLBACK_IMAGE_MODEL):
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
