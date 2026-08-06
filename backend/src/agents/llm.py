"""Central Groq LLM Key Rotation & Model Fallback Manager."""

import logging
import os
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_groq import ChatGroq
from pydantic import SecretStr

from dotenv import load_dotenv

import json

logger = logging.getLogger(__name__)


def extract_json_object(content: Any) -> dict[str, Any] | None:
    """Extract and parse first valid JSON object from LLM response content, ignoring preambles/markdown text."""
    if not content:
        return None

    text = str(content).strip()

    # 1. Check markdown fenced code block
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    # 2. Extract first '{' and last '}' substring
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        json_str = text[start : end + 1]
        try:
            res = json.loads(json_str)
            if isinstance(res, dict):
                return res
        except Exception:
            pass

    # 3. Direct JSON load attempt
    try:
        res = json.loads(text)
        if isinstance(res, dict):
            return res
    except Exception:
        return None

    return None


def get_groq_api_keys() -> list[str]:
    """Gather all available Groq API keys dynamically from environment & .env files."""
    # Ensure dotenv is loaded
    load_dotenv()

    keys: list[str] = []

    # 1. Check explicit environment variables
    for var in (
        "GROQ_API_KEY",
        "GROQ_API_KEY_1",
        "GROQ_API_KEY_2",
        "GROQ_API_KEY_3",
        "GROQ_API_KEY_4",
        "GROQ_API_KEY_5",
        "GROQ_API_KEYS",
    ):
        val = os.getenv(var)
        if val and val.strip():
            # Handle comma-separated keys if present
            for k in val.split(","):
                k_clean = k.strip()
                if k_clean and k_clean not in keys and k_clean.startswith("gsk_"):
                    keys.append(k_clean)

    # 2. Dynamic scan of os.environ for any GROQ_API_KEY*
    for env_k, env_v in os.environ.items():
        if env_k.startswith("GROQ_API_KEY") and env_v and env_v.strip():
            for k in env_v.split(","):
                k_clean = k.strip()
                if k_clean and k_clean not in keys and k_clean.startswith("gsk_"):
                    keys.append(k_clean)

    if not keys:
        keys.append("gsk_placeholder_key_for_initialization")

    return keys


def invoke_groq_with_key_rotation(
    messages: list[BaseMessage] | list[Any],
    tools: list[Any] | None = None,
    preferred_model: str = "llama-3.3-70b-versatile",
    fallback_model: str = "llama-3.1-8b-instant",
) -> Any:
    """Invoke Groq LLM with multi-key rotation fallback on 429 errors.

    Execution Flow:
    1. Try `preferred_model` (llama-3.3-70b-versatile) across ALL available API keys (GROQ_API_KEY, _1, _2, _3).
    2. If ALL 70b keys hit 429 rate limit, fallback to `fallback_model` (llama-3.1-8b-instant) across available keys.
    """
    keys = get_groq_api_keys()

    # Tier 1: Try preferred model (70b) across all API keys
    for idx, key in enumerate(keys):
        try:
            llm_inst = ChatGroq(model=preferred_model, temperature=0.0, api_key=SecretStr(key))
            if tools:
                llm_inst = llm_inst.bind_tools(tools)
            return llm_inst.invoke(messages)
        except Exception as err:
            err_str = str(err).lower()
            if "429" in err_str or "rate_limit" in err_str:
                logger.warning(
                    f"Groq API key #{idx+1} hit 429 rate limit on {preferred_model}. Rotating to next API key..."
                )
                continue
            raise

    # Tier 2: All 70b keys exhausted -> Fallback to 8b instant model
    logger.warning(
        f"All Groq API keys exhausted on {preferred_model}. Falling back to {fallback_model}..."
    )
    for idx, key in enumerate(keys):
        try:
            llm_inst = ChatGroq(model=fallback_model, temperature=0.0, api_key=SecretStr(key))
            if tools:
                llm_inst = llm_inst.bind_tools(tools)
            return llm_inst.invoke(messages)
        except Exception as err:
            err_str = str(err).lower()
            if "429" in err_str or "rate_limit" in err_str:
                continue
            raise

    raise RuntimeError("All Groq API keys and fallback models exceeded rate limits!")
