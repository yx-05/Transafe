"""One-shot readiness check for the demo environment.

Everything here answers a question you would otherwise discover the answer to
in front of an audience: is the database reachable, is the v2 migration
applied, is a core skill published, does the model actually return text, does
the MCP server still boot with its full tool surface.

Two rules shape the design:

**Nothing raises.** A readiness check that throws is worse than no check — the
operator learns nothing and the console shows a stack trace instead of a
verdict. Every check catches its own exception and reports it as a failure
with the message.

**A check reports what it observed, not just pass/fail.** "Core v11" and
"8 tools" are the facts that make a green tick believable; a bare boolean is
something the operator has to take on faith.

The model check is the one worth explaining. ``deepseek-chat`` is served as
``deepseek-flash`` in *non-thinking* mode and answers in a handful of tokens.
Asking for ``deepseek-flash`` by name enables thinking, which can spend the
entire ``max_tokens`` budget on reasoning tokens and return an **empty string**
with ``finish_reason: "length"``. A model name that looks like a harmless
modernisation therefore produces blank answers everywhere at once, so the
check asserts non-empty content rather than a 200 status.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Tables the v2 upgrade adds. A missing one means the migration was not
#: applied, which is the single most common cause of a console full of zeroes.
V2_TABLES: tuple[str, ...] = (
    "campaigns",
    "campaign_cases",
    "artifacts",
    "mcp_access_log",
    "eval_runs",
    "ns_events",
)

#: Tools the MCP server must expose for Act 5 to work.
EXPECTED_MCP_TOOLS: int = 8


def _ensure_env() -> None:
    """Load ``backend/.env`` before checking anything that needs credentials.

    ``main.py`` does this at import for the API process. Doing it here too
    means the result does not depend on which check happened to import a module
    that loads dotenv first — an ordering that made the very first Supabase
    check fail while later Supabase-backed checks passed.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dotenv is a runtime dependency
        return
    # .../backend/src/enterprise/preflight.py -> .../backend/.env
    backend_root = Path(__file__).resolve().parents[2]
    load_dotenv(backend_root / ".env", override=False)


def _result(
    name: str,
    status: str,
    detail: str,
    **extra: Any,
) -> dict[str, Any]:
    """Build one check result.

    Args:
        name: Stable identifier, used by the console for the label.
        status: ``pass`` | ``warn`` | ``fail`` | ``info``.
        detail: One line a human can act on.
        **extra: Observed facts worth showing next to the verdict.

    Returns:
        The check result dict.
    """
    return {"name": name, "status": status, "detail": detail, **extra}


def _check_supabase(client: Any | None = None) -> dict[str, Any]:
    """Can we read from Supabase at all?"""
    try:
        from src.db.vector_store import get_supabase_client

        supabase = client if client is not None else get_supabase_client()
        supabase.table("ns_events").select("*").limit(1).execute()
        return _result("supabase", "pass", "Connected — able to read ns_events")
    except Exception as exc:
        return _result("supabase", "fail", f"Cannot reach Supabase: {exc}")


def _check_v2_schema(client: Any | None = None) -> dict[str, Any]:
    """Is the v2 migration applied?

    Probed table by table so a partial migration names the table it stopped at,
    rather than reporting "schema missing" and leaving the operator to guess.

    ``select("*")`` rather than ``select("id")``: ``campaign_cases`` is a join
    table keyed on (campaign_id, case_id) with no ``id`` column at all, so
    asking for one reports a missing table that is present and working — a
    false alarm, which is the one thing a readiness check must never raise.
    """
    missing: list[str] = []
    try:
        from src.db.vector_store import get_supabase_client

        supabase = client if client is not None else get_supabase_client()
        for table in V2_TABLES:
            try:
                supabase.table(table).select("*").limit(1).execute()
            except Exception:
                missing.append(table)
    except Exception as exc:
        return _result("v2_schema", "fail", f"Cannot check schema: {exc}")

    if missing:
        return _result(
            "v2_schema",
            "fail",
            f"Missing tables: {', '.join(missing)} — apply migrations/v2_enterprise.sql",
            missing=missing,
        )
    return _result("v2_schema", "pass", f"All {len(V2_TABLES)} v2 tables present")


def _check_core_artifact(client: Any | None = None) -> dict[str, Any]:
    """Is a phone-agent core skill published, and at what version?"""
    try:
        from src.enterprise import registry
        from src.enterprise.evaluation import CORE_ARTIFACT_NAME

        artifact = registry.get_artifact(CORE_ARTIFACT_NAME, client=client)
    except Exception as exc:
        return _result("core_artifact", "fail", f"Lookup failed: {exc}")

    if not artifact:
        return _result(
            "core_artifact",
            "warn",
            "No core skill published yet — run PREPARE, then approve a candidate",
        )
    return _result(
        "core_artifact",
        "pass",
        f"{CORE_ARTIFACT_NAME} v{artifact.get('version')} published",
        version=artifact.get("version"),
    )


def _check_campaigns(client: Any | None = None) -> dict[str, Any]:
    """How many campaigns are active — context for the operator, not a verdict.

    Deliberately ``info``: zero campaigns is a perfectly valid *starting* state,
    and flagging it as a problem would train the operator to ignore warnings.
    """
    try:
        from src.db.vector_store import get_supabase_client

        supabase = client if client is not None else get_supabase_client()
        rows = supabase.table("campaigns").select("code,status").execute().data or []
        active = [r for r in rows if str(r.get("status", "")).upper() in {"APPROVED", "ACTIVE"}]
        codes = ", ".join(str(r.get("code")) for r in active) or "none"
        return _result(
            "campaigns",
            "info",
            f"{len(active)} active campaign(s): {codes}",
            active=len(active),
        )
    except Exception as exc:
        return _result("campaigns", "warn", f"Could not count campaigns: {exc}")


async def _check_llm() -> dict[str, Any]:
    """Is the configured model reachable, answering, and *not* a thinking model?

    Talks to the API directly rather than through the LangChain wrapper, because
    the three facts that matter all live in the raw response and none of them is
    reliably surfaced by the wrapper:

    * ``model`` — the name that actually served the request. ``deepseek-chat``
      is served as ``deepseek-flash``, so the configured name is not the answer.
    * content — a thinking model given a small ``max_tokens`` returns HTTP 200
      with ``finish_reason: "length"`` and an **empty string**, and every
      surface that renders model output then looks broken at once.
    * ``reasoning_tokens`` — thinking mode spends the budget on internal
      reasoning before it writes anything. That is a *warning*, not a failure:
      it still answers when the budget is adequate, just several times slower,
      and ``ask_transafe`` makes two or three calls so it compounds.
    """
    model = os.getenv("DEEPSEEK_MODEL_PRIMARY", "deepseek-chat")
    base = (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")

    try:
        import httpx

        from src.agents.llm import get_deepseek_api_keys

        keys = get_deepseek_api_keys()
        if not keys:
            return _result("llm", "fail", "No DEEPSEEK_API_KEY configured")

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
            "max_tokens": 64,
            "stream": False,
        }

        def _call() -> dict[str, Any]:
            response = httpx.post(
                f"{base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {keys[0]}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=45,
            )
            response.raise_for_status()
            return response.json()

        data = await asyncio.to_thread(_call)
        served = str(data.get("model") or model)
        choice = (data.get("choices") or [{}])[0]
        content = str((choice.get("message") or {}).get("content") or "").strip()
        usage = data.get("usage") or {}
        reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0

        if not content:
            return _result(
                "llm",
                "fail",
                (
                    f"{model} (served as {served}) returned an EMPTY answer with "
                    f"finish_reason={choice.get('finish_reason')!r}. It is spending "
                    "the token budget on reasoning. Use deepseek-chat, not deepseek-flash."
                ),
                model=model,
                served_as=served,
            )
        if reasoning:
            return _result(
                "llm",
                "warn",
                (
                    f"{model} (served as {served}) is running in THINKING mode — "
                    f"{reasoning} reasoning tokens for a one-word reply. Slower per "
                    "call, and it returns an empty answer if max_tokens is too small. "
                    "deepseek-chat runs the same model without thinking."
                ),
                model=model,
                served_as=served,
                reasoning_tokens=reasoning,
            )
        return _result(
            "llm",
            "pass",
            f"{model} (served as {served}) answered, no reasoning tokens",
            model=model,
            served_as=served,
        )
    except Exception as exc:
        return _result("llm", "fail", f"{model} call failed: {exc}", model=model)


def _check_mcp_server() -> dict[str, Any]:
    """Does the MCP server still import, and with its full tool surface?

    Import-only on purpose: booting the stdio loop here would block on stdin.
    A broken import is the failure that matters, and the tool count catches an
    accidental removal of one.
    """
    try:
        from mcp.server import TOOL_DEFINITIONS

        count = len(TOOL_DEFINITIONS)
        if count < EXPECTED_MCP_TOOLS:
            return _result(
                "mcp_server",
                "fail",
                f"Only {count} MCP tools defined, expected {EXPECTED_MCP_TOOLS}",
                tools=count,
            )
        return _result(
            "mcp_server",
            "pass",
            f"{count} MCP tools, server imports cleanly",
            tools=count,
        )
    except Exception as exc:
        return _result("mcp_server", "fail", f"MCP server will not import: {exc}")


async def run_preflight(client: Any | None = None) -> dict[str, Any]:
    """Run every readiness check and summarise the verdict.

    Args:
        client: Optional injected Supabase client, for tests.

    Returns:
        ``{"ok": bool, "summary": str, "checks": [...]}``. ``ok`` is True when
        no check returned ``fail``; ``warn`` and ``info`` do not block a demo.
    """
    _ensure_env()
    checks: list[dict[str, Any]] = [
        _check_supabase(client),
        _check_v2_schema(client),
        _check_core_artifact(client),
        _check_campaigns(client),
        _check_mcp_server(),
        await _check_llm(),
    ]

    failures = [c["name"] for c in checks if c["status"] == "fail"]
    warnings = [c["name"] for c in checks if c["status"] == "warn"]

    if failures:
        summary = f"NOT READY — {len(failures)} failed: {', '.join(failures)}"
    elif warnings:
        summary = f"Ready, with {len(warnings)} warning(s): {', '.join(warnings)}"
    else:
        summary = "Ready"

    return {"ok": not failures, "summary": summary, "checks": checks}
