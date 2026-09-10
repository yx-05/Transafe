"""Entity resolver — L2.

Normalises extracted entities so that ``+60 11-2345 6789``, ``011-23456789``
and ``60112345678`` collapse to one graph node. Linkage is worthless without
this step.

Both ``value_raw`` (display/audit) and ``value_norm`` (matching) are stored.
**Matching is only ever performed on ``value_norm``.**
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from src.db.vector_store import get_supabase_client

logger = logging.getLogger(__name__)

VALID_ENTITY_TYPES: frozenset[str] = frozenset(
    {"PHONE", "ACCOUNT", "URL", "DOMAIN", "NAME", "OTHER"}
)

# Hard identifiers — the precision anchors of the graph.
HARD_IDENTIFIER_TYPES: frozenset[str] = frozenset({"PHONE", "ACCOUNT"})

# Honorifics stripped from names, applied repeatedly (e.g. "Dato Sri Najib").
_HONORIFICS = re.compile(
    r"^(mr|mrs|ms|miss|dr|prof|sir|madam|datuk|dato'?|datin|tan\s+sri|sri|puan|encik|"
    r"tuan|haji|hajah)\.?\s+",
    re.IGNORECASE,
)


def normalise_entity(entity_type: str, value: str) -> str:
    """Normalise an entity value by type.

    Args:
        entity_type: One of PHONE, ACCOUNT, URL, DOMAIN, NAME, OTHER.
        value: Raw entity value as extracted from the transcript.

    Returns:
        Normalised value string suitable for deduplication; ``""`` for empty input.

    Raises:
        ValueError: If ``entity_type`` is unknown.
    """
    if not value or not value.strip():
        return ""

    raw = value.strip()
    etype = entity_type.upper()

    if etype == "PHONE":
        return _normalise_phone(raw)
    if etype == "ACCOUNT":
        return _normalise_account(raw)
    if etype == "URL":
        return _normalise_url(raw)
    if etype == "DOMAIN":
        return _normalise_domain(raw)
    if etype == "NAME":
        return _normalise_name(raw)
    if etype == "OTHER":
        return raw.lower().strip()
    raise ValueError(f"Unknown entity type: {entity_type}")


def _normalise_phone(raw: str) -> str:
    """Strip non-digits and coerce to E.164 with a Malaysian default."""
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if digits.startswith("0") and not digits.startswith("60"):
        digits = "60" + digits[1:]
    elif digits.startswith("11") and len(digits) <= 11:
        digits = "60" + digits
    return "+" + digits


def _normalise_account(raw: str) -> str:
    """Strip everything that is not a digit."""
    return re.sub(r"\D", "", raw)


def _normalise_url(raw: str) -> str:
    """Lowercase host, drop scheme / ``www.`` / trailing slash / query."""
    url = raw.lower().strip()
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").removeprefix("www.")
    path = parsed.path.rstrip("/")
    normalised = host + path
    return normalised or raw.lower().strip()


def _normalise_domain(raw: str) -> str:
    """Return the registrable domain (last two labels for common TLDs)."""
    url = raw.lower().strip()
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").removeprefix("www.")
    parts = [p for p in host.split(".") if p]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def _normalise_name(raw: str) -> str:
    """Casefold, collapse whitespace, strip honorifics (repeatedly)."""
    name = re.sub(r"\s+", " ", raw.strip())
    while True:
        stripped = _HONORIFICS.sub("", name)
        if stripped == name:
            break
        name = stripped.strip()
    return name.casefold().strip()


def extract_domain_entity(url_value: str) -> str | None:
    """Extract the registrable domain from a URL, for separate storage.

    Args:
        url_value: Raw URL string.

    Returns:
        Normalised domain string, or ``None`` if not a usable URL.
    """
    if not url_value or not url_value.strip():
        return None
    domain = _normalise_domain(url_value)
    return domain or None


def entities_from_identifiers(identifiers: dict[str, Any]) -> list[dict[str, str]]:
    """Convert regex-extracted identifiers into raw entity dicts.

    Every URL additionally yields a ``DOMAIN`` entity — hosting is reused
    across a campaign far more often than a full path is.

    Args:
        identifiers: Output of ``mo_extractor.extract_identifiers``.

    Returns:
        List of ``{"entity_type": ..., "value": ...}`` dicts.
    """
    raw_entities: list[dict[str, str]] = []
    for value in _values(identifiers.get("phones")):
        raw_entities.append({"entity_type": "PHONE", "value": value})
    for value in _values(identifiers.get("accounts")):
        raw_entities.append({"entity_type": "ACCOUNT", "value": value})
    for value in _values(identifiers.get("urls")):
        raw_entities.append({"entity_type": "URL", "value": value})
        domain = extract_domain_entity(value)
        if domain:
            raw_entities.append({"entity_type": "DOMAIN", "value": domain})
    return raw_entities


def _values(items: Any) -> list[str]:
    """Pull ``value`` strings out of an identifier list."""
    if not items:
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("value"):
            out.append(str(item["value"]))
        elif isinstance(item, str) and item:
            out.append(item)
    return out


def resolve_entities(
    case_id: str,
    raw_entities: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Resolve and upsert entities for a case, then link them to the case.

    Also refreshes each touched entity's ``case_count`` / ``last_seen``. Those
    two columns default to ``0``/insert-time and nothing else in v2 writes them,
    so without this step every node in the console's entity graph reports having
    been seen in zero cases.

    Args:
        case_id: UUID of the fraud case.
        raw_entities: List of ``{"entity_type": ..., "value": ...}`` dicts.

    Returns:
        List of resolved entity dicts with ``entity_id``, ``entity_type``,
        ``value_raw`` and ``value_norm``.
    """
    resolved: list[dict[str, Any]] = []

    try:
        client = get_supabase_client()
    except Exception:
        logger.exception("resolve_entities: Supabase unavailable for case %s", case_id)
        return resolved

    seen: set[tuple[str, str]] = set()

    for ent in raw_entities:
        etype = (ent.get("entity_type") or "OTHER").upper()
        raw_val = ent.get("value", "")

        try:
            norm_val = normalise_entity(etype, raw_val)
        except ValueError:
            logger.warning("resolve_entities: unknown entity type %r — skipped", etype)
            continue

        if not norm_val or (etype, norm_val) in seen:
            continue
        seen.add((etype, norm_val))

        try:
            result = (
                client.table("entities")
                .upsert(
                    {
                        "entity_type": etype,
                        "value_raw": raw_val,
                        "value_norm": norm_val,
                    },
                    on_conflict="entity_type,value_norm",
                )
                .execute()
            )
            data = getattr(result, "data", None)
            entity_id = data[0]["id"] if data else None
            if not entity_id:
                continue

            resolved.append(
                {
                    "entity_id": entity_id,
                    "entity_type": etype,
                    "value_raw": raw_val,
                    "value_norm": norm_val,
                }
            )

            client.table("case_entity_links").upsert(
                {
                    "case_id": case_id,
                    "entity_id": entity_id,
                    "source": ent.get("source", "regex"),
                },
                on_conflict="case_id,entity_id",
            ).execute()
        except Exception:
            logger.exception("Failed to resolve entity %s=%s", etype, raw_val)
            continue

        refresh_entity_stats(client, entity_id)

    return resolved


def refresh_entity_stats(client: Any, entity_id: str, last_seen: str | None = None) -> None:
    """Recompute ``entities.case_count`` / ``last_seen`` from the link table.

    Derived, not incremented, so re-ingesting the same case is idempotent: the
    count is however many distinct cases currently link to the entity, which a
    second run of the same case cannot change (``case_entity_links`` is keyed on
    ``(case_id, entity_id)``).

    Best-effort. The entity and its link are already written by the time this
    runs, so a failure here must not discard a successfully resolved entity —
    it only leaves a stale counter behind. It also never writes a ``0``: a
    count of zero means the link read failed or raced the write, and
    overwriting a correct count with zero would turn a transient read error
    into a permanently wrong number on the graph.

    Args:
        client: Supabase client.
        entity_id: Entity UUID to recompute.
        last_seen: Timestamp to record as the entity's ``last_seen``. Defaults
            to now, which is right for live ingest — the case is arriving as
            this runs. The demo seed must pass the corpus timestamp instead:
            its cases are dated historically, and stamping them with wall-clock
            now would silently rewrite the seeded graph's timeline to "all of
            this happened this second".
    """
    try:
        result = (
            client.table("case_entity_links")
            .select("case_id")
            .eq("entity_id", entity_id)
            .execute()
        )
        case_count = len(list(getattr(result, "data", None) or []))
        if not case_count:
            return
        client.table("entities").update(
            {
                "case_count": case_count,
                "last_seen": last_seen or datetime.now(UTC).isoformat(),
            }
        ).eq("id", entity_id).execute()
    except Exception:
        logger.exception("Failed to refresh case_count for entity %s", entity_id)


def fetch_case_entities(case_id: str) -> list[dict[str, Any]]:
    """Fetch resolved entities linked to a case.

    Args:
        case_id: UUID of the fraud case.

    Returns:
        List of ``{"entity_id", "entity_type", "value_norm", "value_raw"}`` dicts.
    """
    try:
        client = get_supabase_client()
        result = (
            client.table("case_entity_links")
            .select("entity_id, entities!inner(entity_type, value_norm, value_raw)")
            .eq("case_id", case_id)
            .execute()
        )
    except Exception:
        logger.exception("fetch_case_entities failed for case %s", case_id)
        return []

    entities: list[dict[str, Any]] = []
    for row in getattr(result, "data", None) or []:
        ent = row.get("entities")
        if not ent:
            continue
        entities.append(
            {
                "entity_id": row.get("entity_id"),
                "entity_type": ent.get("entity_type"),
                "value_norm": ent.get("value_norm"),
                "value_raw": ent.get("value_raw", ""),
            }
        )
    return entities
