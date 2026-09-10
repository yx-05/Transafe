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


# ── Shared published-artifact reader ────────────────────────────────────────
#
# A receipt claims an agent *read* an artifact, so it is written here — by the
# reader — and never by the propagator. ``propagate_artifact`` used to write
# one for every subscriber before that subscriber had read anything, which made
# ``artifact_consumption`` assert consumption that had not happened for three of
# the four in-process rows. A receipt nobody earned is worse than no receipt: it
# is the console reporting a closed loop that is still open.
#
# Agent names must match the subscriber names in ``propagation.SUBSCRIPTION_MAP``
# or the receipt lands under an agent that was never notified.

PHISHING_AGENT_NAME = "phishing_worker"
FINANCIAL_AGENT_NAME = "financial_worker"

#: Hard cap on keywords folded in from published patches. The two-tier model
#: exists so that campaign knowledge scales in *memory* rather than in a prompt;
#: an uncapped merge would reintroduce the unbounded-prompt problem §7.0 rejects.
PATCH_MAX_KEYWORDS = 60


def _published_of_type(
    artifact_type: str,
    tier: str | None = None,
    client: Any | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Return ``(artifact, content_json)`` for published artifacts of one type.

    Args:
        artifact_type: The ``artifacts.artifact_type`` to keep.
        tier: Optional ``core``/``pack`` filter.
        client: Optional injected Supabase client.

    Returns:
        Pairs, newest-first. Empty when the registry is unreachable or holds
        nothing of this type.
    """
    try:
        from src.enterprise.registry import list_artifacts
    except Exception as err:  # noqa: BLE001 - the worker must stay importable
        logger.debug("artifact_feed: registry import skipped: %s", err)
        return []

    try:
        artifacts = list_artifacts(tier=tier, client=client)
    except Exception as err:  # noqa: BLE001
        logger.debug("artifact_feed: artifact list skipped: %s", err)
        return []

    return [
        (artifact, _content_json(artifact))
        for artifact in artifacts
        if str(artifact.get("artifact_type") or "") == artifact_type
    ]


def _write_receipt(artifact: dict[str, Any], agent_name: str, client: Any | None) -> None:
    """Record that ``agent_name`` read ``artifact``, and announce it. Never raises.

    This is the only place a receipt is written. The propagator used to write
    one for every subscriber before the subscriber had read anything, which
    made ``artifact_consumption`` — the table the console renders as
    ``consumed_by`` — assert consumption that had not happened.

    The ``propagation_acknowledged`` event is emitted here for the same reason:
    an acknowledgement should come from the agent that acknowledged. It is
    emitted on a cache miss only, so a caller in the live call path pays this
    once per TTL window rather than once per utterance.
    """
    artifact_id = artifact.get("id")
    if not artifact_id:
        return
    try:
        from src.enterprise.registry import record_consumption

        record_consumption(str(artifact_id), agent_name, client=client)
    except Exception as err:  # noqa: BLE001
        logger.debug("artifact_feed: receipt skipped for %s: %s", artifact.get("name"), err)
        return

    try:
        from src.enterprise.events import emit_event_sync

        emit_event_sync(
            layer="propagation",
            event_type="propagation_acknowledged",
            payload={
                "artifact_id": str(artifact_id),
                "artifact_name": artifact.get("name"),
                "artifact_type": artifact.get("artifact_type"),
                "tier": artifact.get("tier"),
                "version": artifact.get("version"),
                "agent_name": agent_name,
                "acknowledged_by": "consumer",
            },
        )
    except Exception as err:  # noqa: BLE001 - telemetry must not break a call
        logger.debug("artifact_feed: ack event skipped for %s: %s", artifact.get("name"), err)


def _cached(cache: Any, ts: float, force: bool) -> bool:
    """True when a TTL cache entry is still fresh and re-use is not forced."""
    return cache is not None and not force and (time.monotonic() - ts) < LEARNED_PHRASE_TTL_SECONDS


# ── Core tier: phone_agent_core ─────────────────────────────────────────────
#: Last successful ``phone_agent_core`` body. ``""`` means "read, found none".
_CORE_CACHE: str | None = None
_CORE_CACHE_TS: float = 0.0


def load_core_guide(
    agent_name: str = PHONE_AGENT_NAME,
    client: Any | None = None,
    record_receipt: bool = True,
    force: bool = False,
) -> str:
    """Load the published ``phone_agent_core`` body, or ``""`` when there is none.

    The core skill is the campaign-agnostic half of the two-tier model: a
    procedural rule generalised across campaigns, as opposed to the campaign
    packs that carry instance knowledge. The phone worker prefers this body over
    the checked-in ``skills/phone_dialogue_guide.md`` and falls back to the file,
    which is exactly the pre-artifact behaviour.

    Args:
        agent_name: Consuming agent; must match the ``phone_agent_core``
            subscriber in ``SUBSCRIPTION_MAP``.
        client: Optional injected Supabase client.
        record_receipt: Write a consumption receipt for the version read.
        force: Bypass the TTL cache.

    Returns:
        The published core body, or ``""`` when nothing is published or the
        registry is unreachable.
    """
    global _CORE_CACHE, _CORE_CACHE_TS

    if _cached(_CORE_CACHE, _CORE_CACHE_TS, force):
        return _CORE_CACHE or ""

    pairs = _published_of_type("phone_agent_core", tier="core", client=client)
    if not pairs:
        _CORE_CACHE = ""
        _CORE_CACHE_TS = time.monotonic()
        return ""

    artifact, content = pairs[0]
    body = str(artifact.get("content") or content.get("content") or "")
    _CORE_CACHE = body
    _CORE_CACHE_TS = time.monotonic()
    if record_receipt:
        _write_receipt(artifact, agent_name, client)
    logger.info(
        "artifact_feed: core guide %s v%s loaded (%d chars)",
        artifact.get("name"),
        artifact.get("version"),
        len(body),
    )
    return body


# ── Pack tier: phishing playbook patch ──────────────────────────────────────
_PATCH_CACHE: dict[str, list[str]] | None = None
_PATCH_CACHE_TS: float = 0.0


def load_phishing_patch(
    agent_name: str = PHISHING_AGENT_NAME,
    client: Any | None = None,
    record_receipt: bool = True,
    force: bool = False,
) -> dict[str, list[str]]:
    """Load keywords and URL patterns taught by published playbook patches.

    Merges every published ``phishing_playbook_patch``. A patch teaches keywords
    for *one* campaign, so the union across campaigns is what the phishing
    worker should scan with — the same relationship ``campaign_pack`` has to
    ``phone_worker``.

    Args:
        agent_name: Consuming agent; must match the ``phishing_playbook_patch``
            subscriber in ``SUBSCRIPTION_MAP``.
        client: Optional injected Supabase client.
        record_receipt: Write a receipt for each patch actually merged.
        force: Bypass the TTL cache.

    Returns:
        ``{"heavy": [...], "light": [...], "url_patterns": [...]}``, each
        capped at :data:`PATCH_MAX_KEYWORDS`. Empty lists when nothing is
        published.
    """
    global _PATCH_CACHE, _PATCH_CACHE_TS

    if _cached(_PATCH_CACHE, _PATCH_CACHE_TS, force):
        return {
            "heavy": list((_PATCH_CACHE or {}).get("heavy") or []),
            "light": list((_PATCH_CACHE or {}).get("light") or []),
            "url_patterns": list((_PATCH_CACHE or {}).get("url_patterns") or []),
        }

    heavy: set[str] = set()
    light: set[str] = set()
    patterns: set[str] = set()

    for artifact, content in _published_of_type("phishing_playbook_patch", client=client):
        learned_here = False
        for key, bucket in (("heavy_keywords", heavy), ("light_keywords", light)):
            for value in content.get(key) or []:
                text = str(value or "").strip().lower()
                # A one-or-two character keyword substring-matches almost any
                # message and would fire on every submission.
                if len(text) >= 3:
                    bucket.add(text)
                    learned_here = True
        for value in content.get("url_patterns") or []:
            text = str(value or "").strip().lower()
            if text:
                patterns.add(text)
                learned_here = True
        if learned_here and record_receipt:
            _write_receipt(artifact, agent_name, client)

    merged = {
        "heavy": sorted(heavy)[:PATCH_MAX_KEYWORDS],
        "light": sorted(light)[:PATCH_MAX_KEYWORDS],
        "url_patterns": sorted(patterns)[:PATCH_MAX_KEYWORDS],
    }
    _PATCH_CACHE = merged
    _PATCH_CACHE_TS = time.monotonic()
    if heavy or light or patterns:
        logger.info(
            "artifact_feed: phishing patch loaded %d heavy / %d light / %d url pattern(s)",
            len(merged["heavy"]),
            len(merged["light"]),
            len(merged["url_patterns"]),
        )
    return {k: list(v) for k, v in merged.items()}


# ── Pack tier: transaction rules ────────────────────────────────────────────
_TXN_CACHE: list[dict[str, Any]] | None = None
_TXN_CACHE_TS: float = 0.0

#: Account values folded into the deterministic hard-block set.
TXN_BLOCK_ACTION = "BLOCK"
TXN_STEP_UP_ACTION = "STEP_UP"


def load_txn_rules(
    agent_name: str = FINANCIAL_AGENT_NAME,
    client: Any | None = None,
    record_receipt: bool = True,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Load transaction rules taught by published ``txn_rule`` artifacts.

    Args:
        agent_name: Consuming agent; must match the ``txn_rule`` subscriber in
            ``SUBSCRIPTION_MAP``.
        client: Optional injected Supabase client.
        record_receipt: Write a receipt for each rule set actually merged.
        force: Bypass the TTL cache.

    Returns:
        Flat list of ``{campaign, action, condition, reason}`` dicts. Empty when
        nothing is published.
    """
    global _TXN_CACHE, _TXN_CACHE_TS

    if _cached(_TXN_CACHE, _TXN_CACHE_TS, force):
        return [dict(rule) for rule in (_TXN_CACHE or [])]

    rules: list[dict[str, Any]] = []
    for artifact, content in _published_of_type("txn_rule", client=client):
        campaign = str(content.get("campaign") or artifact.get("name") or "unknown")
        batch = content.get("rules") or []
        if not batch:
            continue
        for rule in batch:
            if not isinstance(rule, dict):
                continue
            rules.append(
                {
                    "campaign": campaign,
                    "action": str(rule.get("action") or "").upper(),
                    "condition": rule.get("condition") or {},
                    "reason": str(rule.get("reason") or ""),
                }
            )
        if record_receipt:
            _write_receipt(artifact, agent_name, client)

    _TXN_CACHE = rules
    _TXN_CACHE_TS = time.monotonic()
    if rules:
        logger.info("artifact_feed: %d transaction rule(s) loaded", len(rules))
    return [dict(rule) for rule in rules]


def blocked_recipient_accounts(
    agent_name: str = FINANCIAL_AGENT_NAME,
    client: Any | None = None,
    force: bool = False,
) -> set[str]:
    """Return recipient accounts a published ``txn_rule`` says to hard-block.

    Only ``BLOCK`` rules with an ``in`` condition on ``recipient_account``
    contribute: this is the deterministic half that must not depend on an LLM
    reading anything.

    Args:
        agent_name: Consuming agent, for the receipt.
        client: Optional injected Supabase client.
        force: Bypass the TTL cache.

    Returns:
        Normalised (digit-only) account values.
    """
    blocked: set[str] = set()
    for rule in load_txn_rules(agent_name=agent_name, client=client, force=force):
        if rule.get("action") != TXN_BLOCK_ACTION:
            continue
        condition = rule.get("condition") or {}
        if str(condition.get("field") or "") != "recipient_account":
            continue
        for value in condition.get("values") or []:
            digits = "".join(ch for ch in str(value) if ch.isdigit())
            if digits:
                blocked.add(digits)
    return blocked


def reset_artifact_cache() -> None:
    """Drop every cached artifact (core, patch, txn, phrases). Test seam."""
    global _CORE_CACHE, _CORE_CACHE_TS
    global _PATCH_CACHE, _PATCH_CACHE_TS
    global _TXN_CACHE, _TXN_CACHE_TS
    _CORE_CACHE, _CORE_CACHE_TS = None, 0.0
    _PATCH_CACHE, _PATCH_CACHE_TS = None, 0.0
    _TXN_CACHE, _TXN_CACHE_TS = None, 0.0
    reset_learned_phrase_cache()


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
