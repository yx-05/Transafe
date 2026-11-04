"""Central DeepSeek LLM Key Rotation & Model Fallback Manager.

Uses DeepSeek's OpenAI-compatible API (https://api.deepseek.com).
All Groq references have been replaced with DeepSeek for China demo accessibility.
"""

import logging
import os
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from dotenv import load_dotenv

import json

logger = logging.getLogger(__name__)

# DeepSeek API configuration
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


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


def get_deepseek_api_keys() -> list[str]:
    """Gather all available DeepSeek API keys dynamically from environment & .env files."""
    # Ensure dotenv is loaded
    load_dotenv()

    keys: list[str] = []

    # 1. Check explicit environment variables
    for var in (
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_KEY_1",
        "DEEPSEEK_API_KEY_2",
        "DEEPSEEK_API_KEY_3",
        "DEEPSEEK_API_KEY_4",
        "DEEPSEEK_API_KEY_5",
        "DEEPSEEK_API_KEYS",
    ):
        val = os.getenv(var)
        if val and val.strip():
            # Handle comma-separated keys if present
            for k in val.split(","):
                k_clean = k.strip()
                if k_clean and k_clean not in keys and k_clean.startswith("sk-"):
                    keys.append(k_clean)

    # 2. Dynamic scan of os.environ for any DEEPSEEK_API_KEY*
    for env_k, env_v in os.environ.items():
        if env_k.startswith("DEEPSEEK_API_KEY") and env_v and env_v.strip():
            for k in env_v.split(","):
                k_clean = k.strip()
                if k_clean and k_clean not in keys and k_clean.startswith("sk-"):
                    keys.append(k_clean)

    if not keys:
        keys.append("sk-placeholder_key_for_initialization")

    return keys


# Backward-compatible alias
get_groq_api_keys = get_deepseek_api_keys


DEPRECATED_MODEL_MAP = {
    # Old Groq model names → DeepSeek equivalents
    "openai/gpt-oss-120b": "deepseek-chat",
    "qwen/qwen3.8-27b": "deepseek-chat",
    "llama-3.3-70b-versatile": "deepseek-chat",
    "llama-3.1-8b-instant": "deepseek-chat",
    "llama-3.1-70b-versatile": "deepseek-reasoner",
    # Also map our own provisional names to the real API model names
    "deepseek-v4-flash": "deepseek-chat",
    "deepseek-v4-pro": "deepseek-reasoner",
}


def _resolve_model(model_name: str | None, default_env: str, fallback_default: str) -> str:
    """Resolve model name, translating deprecated Groq model names to DeepSeek equivalents."""
    target = model_name or os.getenv(default_env, fallback_default)
    if target in DEPRECATED_MODEL_MAP:
        env_override = os.getenv(default_env)
        return env_override or DEPRECATED_MODEL_MAP[target]
    return target


def invoke_deepseek_with_key_rotation(
    messages: list[BaseMessage] | list[Any],
    tools: list[Any] | None = None,
    preferred_model: str = "deepseek-chat",
    fallback_model: str = "deepseek-reasoner",
) -> Any:
    """Invoke DeepSeek LLM with multi-key rotation fallback on 429 errors or model unavailability.

    Execution Flow:
    1. Try `preferred_model` (deepseek-chat) across ALL available API keys.
    2. If ALL primary keys hit 429 rate limit or model is unavailable, fallback to
       `fallback_model` (deepseek-reasoner) across available keys.
    """
    preferred_model = _resolve_model(preferred_model, "DEEPSEEK_MODEL_PRIMARY", "deepseek-chat")
    fallback_model = _resolve_model(fallback_model, "DEEPSEEK_MODEL_FALLBACK", "deepseek-reasoner")
    keys = get_deepseek_api_keys()

    # Tier 1: Try preferred model across all API keys
    last_err: Exception | None = None
    for idx, key in enumerate(keys):
        try:
            llm_inst = ChatOpenAI(
                model=preferred_model,
                temperature=0.0,
                api_key=SecretStr(key),
                base_url=DEEPSEEK_BASE_URL,
            )
            if tools:
                llm_inst = llm_inst.bind_tools(tools)
            return llm_inst.invoke(messages)
        except Exception as err:
            last_err = err
            err_str = str(err).lower()
            if "429" in err_str or "rate_limit" in err_str:
                logger.warning(
                    f"DeepSeek API key #{idx+1} hit 429 rate limit on {preferred_model}. Rotating to next API key..."
                )
                continue
            if "404" in err_str or "model_not_found" in err_str:
                logger.warning(
                    f"Model {preferred_model} not found/accessible on DeepSeek key #{idx+1}. Breaking to fallback model..."
                )
                break
            raise

    # Tier 2: Primary keys exhausted or unavailable -> Fallback to pro model
    logger.warning(
        f"DeepSeek keys exhausted on {preferred_model}. Falling back to {fallback_model}..."
    )
    for idx, key in enumerate(keys):
        try:
            llm_inst = ChatOpenAI(
                model=fallback_model,
                temperature=0.0,
                api_key=SecretStr(key),
                base_url=DEEPSEEK_BASE_URL,
            )
            if tools:
                llm_inst = llm_inst.bind_tools(tools)
            return llm_inst.invoke(messages)
        except Exception as err:
            err_str = str(err).lower()
            if "429" in err_str or "rate_limit" in err_str:
                continue
            raise

    raise RuntimeError(f"All DeepSeek API keys and fallback models exhausted. Last error: {last_err}")


# Backward-compatible alias for existing callers
invoke_groq_with_key_rotation = invoke_deepseek_with_key_rotation
