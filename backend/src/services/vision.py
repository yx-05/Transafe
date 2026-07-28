"""Vision service using Groq Llama-3.2-11b-vision-preview for OCR text extraction."""

import os

from groq import Groq

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY", "gsk_dummy"))


async def extract_text_from_image(base64_image: str) -> str:
    """Extract text from base64 screenshot data using Groq Vision (llama-3.2-11b-vision-preview)."""
    if not base64_image:
        return ""

    image_url = (
        base64_image
        if base64_image.startswith("data:")
        else f"data:image/jpeg;base64,{base64_image}"
    )

    response = groq_client.chat.completions.create(
        model="llama-3.2-11b-vision-preview",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Extract all text from this image exactly as shown. Return only the extracted text.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url,
                        },
                    },
                ],
            }
        ],
        temperature=0.0,
    )

    if response.choices and len(response.choices) > 0:
        content = response.choices[0].message.content
        return content or ""
    return ""
