"""Worker-side consumption of published pack-tier artifacts.

Propagation (``src/enterprise/propagation.py``) notifies each subscribed agent
and writes a receipt on that agent's behalf. That receipt records an artifact
was *offered*, not that any behaviour changed — the phone worker shipped with a
hardcoded ``HIGH_RISK_PHRASES`` list that no published artifact could reach, so
a campaign pack could fan out, be acknowledged, and render as a closed loop on
the console while detection stayed byte-for-byte identical.

This module is the missing half: the worker reads the published pack and folds
its phrases into what it actually detects with, then records its own receipt
for the artifacts it genuinely read.

Fail-soft by construction. A registry that is unreachable degrades detection to
the built-in phrase list, which is exactly the pre-artifact behaviour. A live
scam call must never fail because a learning artifact could not load — so every
path here returns an empty mapping rather than raising, and the caller treats
"no learned phrases" as normal.

The TTL mirrors the ``learned_keywords`` merge in ``workers/phishing.py`` so
both learning paths take effect on the same timescale (~45s) and neither
re-queries per utterance.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

#: Seconds a loaded phrase set is reused before the registry is re-read.
#: Matches ``_LEARNED_MERGE_TTL_SECONDS`` in ``workers/phishing.py``.
LEARNED_PHRASE_TTL_SECONDS: float = 45.0

#: Agent name this module consumes on behalf of. Must match the subscriber
#: name in ``SUBSCRIPTION_MAP["campaign_pack"]`` or receipts land under an
#: agent the propagation layer never notified.
PHONE_AGENT_NAME = "phone_worker"

#: ``phrase -> campaign code`` from the last successful load.
_PHRASE_CACHE: dict[str, str] | None = None
_PHRASE_CACHE_TS: float = 0.0


def reset_learned_phrase_cache() -> None:
    """Drop the cached phrase set. Test seam and post-publish invalidation."""
    global _PHRASE_CACHE, _PHRASE_CACHE_TS
    _PHRASE_CACHE = None
    _PHRASE_CACHE_TS = 0.0


def _content_json(artifact: dict[str, Any]) -> dict[str, Any]:
    """Return an artifact's ``content_json`` as a dict.

    Supabase may hand back a JSON column already decoded or still as text
    depending on driver and column type, so both are accepted. Anything else
    yields an empty dict rather than raising — a malformed artifact must not
    take the phrase loader down with it.
    """
    raw = artifact.get("content_json")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            logger.debug("artifact_feed: unparseable content_json on %s", artifact.get("name"))
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def extract_pack_phrases(artifact: dict[str, Any]) -> list[str]:
    """Extract the high-risk phrases a campaign pack teaches.

    The compiler emits ``high_risk_phrases`` as ``[{"text", "lang",
    "case_count"}]`` (see the schema in ``enterprise/compiler.py``). Bare
    strings are tolerated too so a hand-written or older pack still loads.

    Args:
        artifact: A published artifact row.

    Returns:
        Lowercased, de-duplicated, non-empty phrases. Empty when the artifact
        teaches none.
    """
    content = _content_json(artifact)
    phrases: list[str] = []
    for entry in content.get("high_risk_phrases") or []:
        if isinstance(entry, dict):
            text = str(entry.get("text") or "")
        else:
            text = str(entry or "")
        text = text.strip().lower()
        # A one-or-two character "phrase" substring-matches almost any
        # transcript and would fire on every call.
        if len(text) >= 3:
            phrases.append(text)
    return sorted(set(phrases))


def load_learned_phrases(
    agent_name: str = PHONE_AGENT_NAME,
    client: Any | None = None,
    record_receipt: bool = True,
    force: bool = False,
) -> dict[str, str]:
    """Load high-risk phrases from every published campaign pack.

    Reading is what makes the receipt honest: a receipt is written here only
    for artifacts whose phrases were actually folded into the returned set.

    Args:
        agent_name: Consuming agent, recorded on each receipt.
        client: Optional injected Supabase client.
        record_receipt: Write consumption receipts. Disabled by callers that
            only want to inspect the phrase set.
        force: Bypass the TTL cache.

    Returns:
        ``phrase -> campaign code``. Empty when nothing is published or the
        registry is unreachable.
    """
    global _PHRASE_CACHE, _PHRASE_CACHE_TS

    fresh = (
        _PHRASE_CACHE is not None
        and (time.monotonic() - _PHRASE_CACHE_TS) < LEARNED_PHRASE_TTL_SECONDS
    )
    if fresh and not force:
        return dict(_PHRASE_CACHE or {})

    learned: dict[str, str] = {}
    try:
        # Imported lazily: the worker package must stay importable when the
        # enterprise stack (and its Supabase dependency) is not configured.
        from src.enterprise.registry import list_artifacts, record_consumption

        artifacts = list_artifacts(tier="pack", client=client)
        for artifact in artifacts:
            if str(artifact.get("artifact_type", "")) != "campaign_pack":
                continue
            phrases = extract_pack_phrases(artifact)
            if not phrases:
                continue
            code = str(
                _content_json(artifact).get("campaign") or artifact.get("name") or "unknown"
            )
            for phrase in phrases:
                # First campaign to teach a phrase keeps attribution; packs
                # arrive newest-first so this favours the original source.
                learned.setdefault(phrase, code)
            if record_receipt and artifact.get("id"):
                record_consumption(str(artifact["id"]), agent_name, client=client)
    except Exception as err:  # noqa: BLE001
        logger.debug("artifact_feed: learned phrase load skipped: %s", err)
        # Serve the last good set rather than going blind mid-incident.
        return dict(_PHRASE_CACHE or {})

    _PHRASE_CACHE = learned
    _PHRASE_CACHE_TS = time.monotonic()
    logger.info(
        "artifact_feed: %d learned phrase(s) loaded from published campaign packs",
        len(learned),
    )
    return dict(learned)
