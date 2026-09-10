"""Row → console-JSON mappers for the Enterprise API.

The console's TypeScript types are the contract (see
``frontend/enterprise/src/types/{events,campaign,api}.ts``). Several fields it
needs do not exist in the v1 schema and are *derived* here rather than by
changing v1 tables. Each derivation is documented at its function, because a
derived field that silently drifts is worse than a missing one.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Console's EntityType union. Anything else is coerced to OTHER so an unexpected
# value can never break rendering.
VALID_ENTITY_TYPES: frozenset[str] = frozenset(
    {"PHONE", "ACCOUNT", "URL", "DOMAIN", "NAME", "OTHER"}
)

# risk_label is a v2 presentation concept. v1's fraud_cases.risk_tier has a DB
# CHECK allowing only LOW/MEDIUM/HIGH, so CRITICAL can never come from v1 and is
# derived from the score. tier (raw v1 value) and risk_label may legitimately
# disagree; tier is v1 truth, risk_label is v2 presentation.
CRITICAL_SCORE = 85
HIGH_SCORE = 70
MEDIUM_SCORE = 40


def risk_label(risk_score: Any) -> str:
    """Derive the console's four-level risk label from a 0-100 score."""
    try:
        score = int(risk_score)
    except (TypeError, ValueError):
        return "LOW"
    if score >= CRITICAL_SCORE:
        return "CRITICAL"
    if score >= HIGH_SCORE:
        return "HIGH"
    if score >= MEDIUM_SCORE:
        return "MEDIUM"
    return "LOW"


def coerce_entity_type(value: Any) -> str:
    """Map an entity type onto the console's union, defaulting to OTHER."""
    etype = str(value or "").upper()
    return etype if etype in VALID_ENTITY_TYPES else "OTHER"


def format_mmss(seconds: Any) -> str | None:
    """Format a second offset as ``mm:ss``. Returns None when not a number."""
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return None
    if total < 0:
        return None
    return f"{total // 60:02d}:{total % 60:02d}"


def _parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating a trailing ``Z``."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def scam_type(fingerprint: dict[str, Any] | None, trigger_type: Any) -> str:
    """Best-available scam type for a case.

    v1 has no ``scam_type`` column. The MO fingerprint is the real source; cases
    whose MO has not been extracted yet fall back to v1's ``trigger_type``, so
    early-demo cases show a trigger where later ones show a behavioural label.
    """
    if fingerprint:
        for key in ("pretext", "impersonated_entity"):
            value = fingerprint.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(trigger_type or "UNKNOWN")


def case_summary(
    case: dict[str, Any],
    *,
    ordinal: int,
    discovery_state: str,
    campaign_id: str | None,
    campaign_name: str | None,
    fingerprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map a ``fraud_cases`` row onto the console's ``CaseSummary``.

    Args:
        case: Raw ``fraud_cases`` row.
        ordinal: Derived display-only case number (see ``case_ordinals``).
        discovery_state: NORMAL | OBSERVED | CLUSTERED.
        campaign_id: Owning campaign id, if any.
        campaign_name: Owning campaign name, if any.
        fingerprint: Parsed ``case_mo.fingerprint``, used for ``scam_type``.

    Returns:
        A ``CaseSummary``-shaped dict.
    """
    return {
        "id": str(case.get("id")),
        "case_number": ordinal,
        "tier": case.get("risk_tier") or "LOW",
        "scam_type": scam_type(fingerprint, case.get("trigger_type")),
        "risk_score": case.get("risk_score") or 0,
        "risk_label": risk_label(case.get("risk_score")),
        "created_at": case.get("created_at"),
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "discovery_state": discovery_state,
    }


def mo_fingerprint(fingerprint: dict[str, Any] | None) -> dict[str, Any] | None:
    """Map the raw extractor fingerprint onto the console's ``MoFingerprint``.

    The extractor's vocabulary differs from the console's:
    ``impersonated_entity``→``impersonates``, ``script_phases``→``phases``,
    ``time_to_money_ask_sec``→``money_ask_at`` (rendered ``mm:ss`` because the
    console types it as a string), ``languages[0]``→``language``.
    """
    if not fingerprint:
        return None
    languages = fingerprint.get("languages")
    language = languages[0] if isinstance(languages, list) and languages else None
    phases = fingerprint.get("script_phases")
    return {
        "impersonates": fingerprint.get("impersonated_entity"),
        "pretext": fingerprint.get("pretext"),
        "phases": [str(p) for p in phases] if isinstance(phases, list) else [],
        "money_ask_at": format_mmss(fingerprint.get("time_to_money_ask_sec")),
        "channel": fingerprint.get("channel"),
        "language": language,
    }


def novel_phrases_by_line(
    fingerprint: dict[str, Any] | None,
) -> dict[int, list[str]]:
    """Group the MO extractor's novel phrases by transcript utterance index.

    The extractor grounds each phrase in a specific utterance, which is what
    lets the console highlight in place.
    """
    grouped: dict[int, list[str]] = {}
    if not fingerprint:
        return grouped
    for phrase in fingerprint.get("novel_phrases") or []:
        if not isinstance(phrase, dict):
            continue
        text = phrase.get("text")
        idx = phrase.get("utterance_idx")
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            idx_int = int(idx)
        except (TypeError, ValueError):
            continue
        grouped.setdefault(idx_int, []).append(text)
    return grouped


def transcript_lines(
    rows: list[dict[str, Any]],
    fingerprint: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Map ``call_transcripts`` rows onto the console's ``TranscriptLine[]``.

    ``t`` is derived as the mm:ss offset from the first utterance, since v1
    stores absolute timestamps only. Novel phrases are attached to the exact
    line they were said on.

    A phrase that is not a verbatim (case-insensitive) substring of its line is
    dropped: the console highlights by substring match, so a non-matching phrase
    would render nothing while still counting as present. Dropping keeps the
    highlight count honest.
    """
    if not rows:
        return []

    grouped = novel_phrases_by_line(fingerprint)
    base = _parse_ts(rows[0].get("created_at"))
    lines: list[dict[str, Any]] = []

    for idx, row in enumerate(rows):
        text = row.get("utterance") or ""
        offset = 0
        current = _parse_ts(row.get("created_at"))
        if base and current:
            offset = max(0, int((current - base).total_seconds()))

        haystack = text.casefold()
        phrases = [p for p in grouped.get(idx, []) if p.casefold() in haystack]
        dropped = len(grouped.get(idx, [])) - len(phrases)
        if dropped:
            logger.info(
                "transcript line %d: dropped %d novel phrase(s) not verbatim in the utterance",
                idx,
                dropped,
            )

        line: dict[str, Any] = {
            "t": format_mmss(offset) or "00:00",
            "speaker": row.get("speaker") or "SYSTEM",
            "text": text,
            "score": row.get("risk_score"),
        }
        if phrases:
            line["novel_phrases"] = phrases
        lines.append(line)

    return lines


def case_ordinals(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Map case id → stable 1-based display number.

    v1's ``fraud_cases`` has no human-facing case number — the primary key is a
    UUID — but the console renders "Case #7" and :func:`link_reason` cites
    "cases #7,#19". The ordinal is therefore *derived*, and the derivation has
    to be stable across every endpoint or the same case appears under two
    different numbers on two screens.

    Stability comes from ordering the whole table by ``created_at`` ascending
    and numbering from 1: a case's ordinal changes only if a case older than it
    is inserted, which for an append-only incident log does not happen. The
    caller must pass **all** cases in that order, not a page of them, otherwise
    the numbering restarts at each page boundary.

    Args:
        rows: Every ``fraud_cases`` row, oldest first.

    Returns:
        ``{case_id: ordinal}``, 1-based.
    """
    return {str(row["id"]): idx for idx, row in enumerate(rows, start=1) if row.get("id")}


def span_minutes(first_seen: Any, last_seen: Any) -> int | None:
    """Whole minutes between two ISO-8601 timestamps, or None if unparseable."""
    start, end = _parse_ts(first_seen), _parse_ts(last_seen)
    if not start or not end:
        return None
    return max(0, int((end - start).total_seconds() // 60))


def _median(values: list[float]) -> float:
    """Median of a non-empty list. Median, not mean: one case that sat in the
    backlog over a weekend must not become the number on the wall."""
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def time_to_discovery_metric(
    campaign_created_at: dict[str, Any],
    memberships: list[dict[str, Any]],
    case_created_at: dict[str, Any],
) -> dict[str, Any] | None:
    """Measure how long a case waits between ingest and joining a campaign.

    This is the console's headline ``OverviewMetric``. Every number in it is a
    subtraction of two stored timestamps — ``campaign_cases.joined_at`` minus
    ``fraud_cases.created_at`` — so it can be recomputed from the rows by
    anyone who doubts it.

    **What the two halves mean.** The bar's ``before``/``after`` are the two
    cohorts of a campaign's member cases, split on whether the case existed
    before the system had named the pattern:

    ``before``
        Cases already ingested when their campaign was created. They waited for
        the pattern to be *discovered* — for enough sibling cases to accumulate
        to clear the promotion gate.
    ``after``
        Cases ingested once the campaign already existed. They only had to be
        *recognised* against a pattern the system already held.

    That is a real before/after of the same measured quantity, and it is the
    only one this database supports. It is **not** the "before TranSafe"
    industry baseline the frontend spec's mock implies: nothing in this system
    records how long a human analyst would have taken, and a constant lifted
    from a report is exactly the fabricated metric this function exists to
    avoid.

    Returns ``None`` — meaning "omit this metric" — whenever either cohort is
    empty. A one-sided comparison rendered as a two-sided bar would show a
    ``0`` for the missing half, and a zero here reads as "discovered
    instantly", which is the strongest claim on the screen and the one least
    supported by data.

    Args:
        campaign_created_at: Campaign id → the campaign's ``created_at``, i.e.
            the moment the pattern was named. Campaigns absent from this map
            contribute nothing.
        memberships: ``campaign_cases`` rows with ``campaign_id``, ``case_id``
            and ``joined_at``.
        case_created_at: Case id → the case's ``created_at`` (ingest).

    Returns:
        An ``OverviewMetric``-shaped dict, or ``None`` when it cannot be
        measured on both sides.
    """
    before: list[float] = []
    after: list[float] = []

    for row in memberships or []:
        named = _parse_ts(campaign_created_at.get(str(row.get("campaign_id") or "")))
        ingested = _parse_ts(case_created_at.get(str(row.get("case_id") or "")))
        clustered = _parse_ts(row.get("joined_at"))
        if not (named and ingested and clustered):
            continue
        waited_min = (clustered - ingested).total_seconds() / 60.0
        if waited_min < 0:
            # Joined before it was ingested: clock skew or a hand-edited row.
            # A negative latency is not a fast one, so it is dropped rather
            # than averaged in where it would drag the median down.
            continue
        (after if ingested >= named else before).append(waited_min)

    if not before or not after:
        return None

    return {
        "label": "TIME TO DISCOVERY",
        "before_value": round(_median(before), 1),
        "after_value": round(_median(after), 1),
        "unit": "min",
        "lower_is_better": True,
        # Diagnostics. The console ignores unknown keys; these are here so the
        # number can be challenged — a median over two samples is not the same
        # claim as a median over forty.
        "basis": (
            "median minutes from fraud_cases.created_at to campaign_cases.joined_at; "
            "before = cases ingested before their campaign existed, "
            "after = cases ingested once it did"
        ),
        "before_sample": len(before),
        "after_sample": len(after),
    }


def trace_steps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map a case's ``ns_events`` onto the console's ``TraceStep[]``.

    These are the **v2 ingest pipeline** stages actually recorded for the case
    (``case_ingested`` → ``mo_extracted`` → ``entity_linked``), not v1 LangGraph
    node latencies — nothing persists those, so they are not available to show.
    Step names are left as the raw event types precisely so the distinction is
    visible on screen rather than blurred into a generic "step 1/2/3".

    ``duration_ms`` is measured from the next event's timestamp, which is a real
    elapsed interval. The final step has nothing to measure against and reports
    0 rather than a guess.

    Args:
        events: ``ns_events`` rows for one case, oldest first.

    Returns:
        List of ``{name, duration_ms, detail}``.
    """

    # ns_events timestamps its rows `ts`; `created_at` is accepted only so a
    # caller passing a differently-shaped row does not silently yield no steps.
    def _when(event: dict[str, Any]) -> Any:
        return event.get("ts") or event.get("created_at")

    ordered = [e for e in events if _when(e)]
    if not ordered:
        return []

    steps: list[dict[str, Any]] = []
    for idx, event in enumerate(ordered):
        start = _parse_ts(_when(event))
        duration = 0
        if idx + 1 < len(ordered) and start:
            nxt = _parse_ts(_when(ordered[idx + 1]))
            if nxt:
                duration = max(0, int((nxt - start).total_seconds() * 1000))

        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        detail: str | None = None
        if payload:
            extras = [
                f"{k}={v}"
                for k, v in payload.items()
                if k != "case_id" and not isinstance(v, list | dict)
            ]
            detail = ", ".join(extras) if extras else None

        steps.append(
            {
                "name": str(event.get("event_type") or "step"),
                "duration_ms": duration,
                "detail": detail,
            }
        )
    return steps


# ── Graph builders ───────────────────────────────────────────────────────────
# Screen C (/graph) and Screen D's mini_graph (/campaigns/{id}) MUST agree, so
# both are built from these. The console types links as GraphLink, whose `kind`
# union is "case-case" | "case-entity" | "campaign-case" — hyphens, not the
# underscored names the tables use. `/graph` is normalised by an adapter that
# would coerce a wrong value silently, but `mini_graph` is consumed raw, so the
# wire value has to be correct here rather than corrected downstream.


def case_node(
    case: dict[str, Any],
    *,
    ordinal: int | None = None,
    state: str = "NORMAL",
    campaign_id: str | None = None,
) -> dict[str, Any]:
    """Build a ``GraphNode`` of kind ``case``.

    Labelled ``#<ordinal>`` rather than a UUID prefix so the node agrees with
    the "cases #7,#19" produced by :func:`link_reason`; a node reading
    ``3f2a1b9c`` beside a hover citing ``#7`` is the same case under two names.
    ``campaign_id`` is what the console groups campaign hulls by.
    """
    case_id = str(case.get("id"))
    return {
        "id": case_id,
        "kind": "case",
        "label": f"#{ordinal}" if ordinal is not None else case_id[:8],
        "risk_score": case.get("risk_score") or 0,
        "risk_tier": case.get("risk_tier"),
        "state": state,
        "campaign_id": campaign_id,
        "created_at": case.get("created_at"),
    }


def entity_node(entity: dict[str, Any]) -> dict[str, Any]:
    """Build a ``GraphNode`` of kind ``entity``."""
    return {
        "id": str(entity.get("id")),
        "kind": "entity",
        "label": entity.get("value_norm") or entity.get("value_raw") or "",
        "entity_type": coerce_entity_type(entity.get("entity_type")),
        "case_count": entity.get("case_count") or 0,
    }


def case_link_edge(
    link: dict[str, Any],
    *,
    ordinals: dict[str, int] | None = None,
    entity_type_by_value: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a case↔case ``GraphLink``, with the hover reason attached.

    ``signals`` is emitted as the raw JSONB **object**, not as a list of its
    key names: the console does ``Object.entries(signals)`` to render the
    detail, which on a list yields array indices ("0", "1") instead of signal
    names. ``weight`` is supplied alongside ``score`` because ``mini_graph`` is
    read without an adapter and the type calls it ``weight``.
    """
    ordinals = ordinals or {}
    case_a, case_b = str(link.get("case_a")), str(link.get("case_b"))
    signals = link.get("signals") if isinstance(link.get("signals"), dict) else {}
    try:
        weight = float(link.get("score") or 0.0)
    except (TypeError, ValueError):
        weight = 0.0

    return {
        "source": case_a,
        "target": case_b,
        "kind": "case-case",
        "score": link.get("score"),
        "weight": weight,
        "signals": signals,
        "case_refs": [case_a, case_b],
        "reason": link_reason(
            signals,
            link.get("score"),
            ordinal_a=ordinals.get(case_a),
            ordinal_b=ordinals.get(case_b),
            entity_type_by_value=entity_type_by_value,
        ),
    }


def mention_edge(case_id: Any, entity_id: Any, *, label: str | None = None) -> dict[str, Any]:
    """Build a case→entity ``GraphLink``.

    A mention is an observation, not an inference, so its reason says exactly
    that rather than borrowing the language of a scored link.
    """
    return {
        "source": str(case_id),
        "target": str(entity_id),
        "kind": "case-entity",
        "score": 1.0,
        "weight": 1.0,
        "signals": {},
        "case_refs": [str(case_id)],
        "reason": f"case mentions {label}" if label else "case mentions this identifier",
    }


def campaign_hulls(
    campaigns: list[dict[str, Any]],
    node_ids_by_campaign: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Build ``CampaignHull[]`` from campaign rows and their member node ids.

    Supplied explicitly rather than left to the console's fallback, which has
    only the campaign UUID to label the hull with and would print it raw.
    """
    by_id = {str(c.get("id")): c for c in campaigns if c.get("id")}
    hulls: list[dict[str, Any]] = []
    for campaign_id, node_ids in sorted(node_ids_by_campaign.items()):
        if not node_ids:
            continue
        row = by_id.get(campaign_id, {})
        hulls.append(
            {
                "campaign_id": campaign_id,
                "code": str(row.get("code") or campaign_id),
                "name": str(row.get("name") or row.get("code") or campaign_id),
                "node_ids": node_ids,
            }
        )
    return hulls


# ── Campaign detail (Screen D) ───────────────────────────────────────────────


def campaign_evidence(
    campaign: dict[str, Any],
    gates: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build the console's deterministic ``EvidenceItem[]`` for a campaign.

    Screen D puts COMPUTED evidence beside the LLM HYPOTHESIS precisely so an
    approver can tell them apart, which only works if everything on the left is
    genuinely computed. So each line is either a real promotion-gate result
    (recorded in the ``campaign_proposed`` ns_event when discovery promoted the
    cluster) or a plain column off the campaign row — never a plausible-looking
    number assembled here.

    ``passed`` reflects the gate's own verdict, evaluated against the
    thresholds in :mod:`src.enterprise.clustering`. When the gates were not
    recorded the row-derived fallback re-checks those same constants rather
    than inventing its own, so the two paths cannot disagree.

    Args:
        campaign: ``campaigns`` row.
        gates: ``gates`` block from the ``campaign_proposed`` event, if found.

    Returns:
        List of ``{label, value, passed}``.
    """
    from src.enterprise.clustering import (
        MAX_TIME_SPAN_DAYS,
        MIN_CASE_COUNT,
        MIN_DISTINCT_CUSTOMERS,
        MIN_STRONG_EDGE,
        NOVELTY_THRESHOLD,
    )

    def _num(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    if gates:
        items: list[dict[str, Any]] = []
        case_gate = gates.get("case_count") or {}
        cust_gate = gates.get("distinct_customers") or {}
        edge_gate = gates.get("strong_edge") or {}
        span_gate = gates.get("time_span") or {}
        novel_gate = gates.get("novelty") or {}

        if case_gate:
            items.append(
                {
                    "label": "cases",
                    "value": f"{int(_num(case_gate.get('value')))} "
                    f"(min {int(_num(case_gate.get('min'), MIN_CASE_COUNT))})",
                    "passed": bool(case_gate.get("pass")),
                }
            )
        if cust_gate:
            items.append(
                {
                    "label": "distinct customers",
                    "value": f"{int(_num(cust_gate.get('value')))} "
                    f"(min {int(_num(cust_gate.get('min'), MIN_DISTINCT_CUSTOMERS))})",
                    "passed": bool(cust_gate.get("pass")),
                }
            )
        if edge_gate:
            items.append(
                {
                    "label": "strongest link",
                    "value": f"{_num(edge_gate.get('value')):.2f} "
                    f"(min {_num(edge_gate.get('min'), MIN_STRONG_EDGE):.2f})",
                    "passed": bool(edge_gate.get("pass")),
                }
            )
        if span_gate:
            items.append(
                {
                    "label": "span",
                    "value": f"{int(_num(span_gate.get('value')))} d "
                    f"(max {int(_num(span_gate.get('max'), MAX_TIME_SPAN_DAYS))} d)",
                    "passed": bool(span_gate.get("pass")),
                }
            )
        if novel_gate:
            items.append(
                {
                    "label": "novelty",
                    "value": f"cosine {_num(novel_gate.get('best_cosine')):.2f} "
                    f"(merge at {_num(novel_gate.get('threshold'), NOVELTY_THRESHOLD):.2f})",
                    "passed": bool(novel_gate.get("pass")),
                }
            )
        if items:
            return items

    # Fallback: no recorded gates. Every line below is a column off the row,
    # re-checked against the same clustering constants.
    case_count = int(_num(campaign.get("case_count")))
    customer_count = int(_num(campaign.get("customer_count")))
    confidence = _num(campaign.get("confidence"))
    indicators = campaign.get("indicators")
    indicator_count = len(indicators) if isinstance(indicators, list) else 0
    span = span_minutes(campaign.get("first_seen"), campaign.get("last_seen"))

    evidence = [
        {
            "label": "cases / distinct customers",
            "value": f"{case_count} cases, {customer_count} customers",
            "passed": case_count >= MIN_CASE_COUNT and customer_count >= MIN_DISTINCT_CUSTOMERS,
        },
        {
            "label": "confidence",
            "value": f"{confidence:.2f}",
            "passed": confidence > 0,
        },
        {
            "label": "indicators",
            "value": f"{indicator_count} recorded",
            "passed": indicator_count > 0,
        },
    ]
    if span is not None:
        evidence.append(
            {
                "label": "span",
                "value": f"{span} min (max {MAX_TIME_SPAN_DAYS} d)",
                "passed": span <= MAX_TIME_SPAN_DAYS * 24 * 60,
            }
        )
    return evidence


def campaign_hypothesis(campaign: dict[str, Any]) -> dict[str, Any]:
    """Map a campaign row onto the console's ``CampaignHypothesis``.

    ``mo_summary`` is returned **exactly as stored** and is never synthesised:
    an operator deciding whether to approve must not be shown generated prose
    that no evidence backs. A campaign with no recorded summary yields an empty
    string, which Screen D renders as a blank MO field — visibly nothing, which
    is the honest answer.

    The container is always an object even when empty, because the console
    reads ``hypothesis.name`` and ``hypothesis.mo_summary`` unguarded while
    initialising its edit form; a null here is a blank screen, not a blank
    field.
    """
    indicators = campaign.get("indicators")
    novel: list[str] = []
    if isinstance(indicators, list):
        for item in indicators:
            if isinstance(item, str) and item.strip():
                novel.append(item.strip())
            elif isinstance(item, dict):
                value = item.get("value") or item.get("indicator") or item.get("text")
                if isinstance(value, str) and value.strip():
                    novel.append(value.strip())

    return {
        "name": str(campaign.get("name") or campaign.get("code") or ""),
        "mo_summary": str(campaign.get("mo_summary") or ""),
        "novel_indicators": novel,
    }


def proposed_artifact(row: dict[str, Any]) -> dict[str, Any]:
    """Map an ``artifacts`` row onto the console's ``ProposedArtifact``."""
    sources = row.get("source_campaigns")
    return {
        "name": str(row.get("name") or ""),
        "tier": "core" if str(row.get("tier")) == "core" else "pack",
        "target_agent": str(row.get("target_agent") or ""),
        "version": int(row.get("version") or 0),
        "note": row.get("artifact_type"),
        "source_campaigns": [str(s) for s in sources] if isinstance(sources, list) else [],
    }


def link_reason(
    signals: Any,
    score: Any,
    *,
    ordinal_a: int | None = None,
    ordinal_b: int | None = None,
    entity_type_by_value: dict[str, str] | None = None,
) -> str:
    """Compose the hover text for a case↔case graph link.

    The console requires a non-empty ``reason`` on every link. Built from the
    strongest available signal so the string explains *why* the edge exists,
    e.g. ``shared ACCOUNT 1592… · w 0.95 · cases #7,#19``.
    """
    types = entity_type_by_value or {}
    parts: list[str] = []

    if isinstance(signals, dict):
        for key in ("shared_identifier", "shared_domain"):
            signal = signals.get(key)
            if not isinstance(signal, dict) or not signal.get("matched"):
                continue
            values = [str(v) for v in (signal.get("shared_values") or [])]
            if not values:
                continue
            first = values[0]
            label = types.get(first, "DOMAIN" if key == "shared_domain" else "identifier")
            shown = first if len(first) <= 12 else f"{first[:10]}…"
            extra = f" +{len(values) - 1}" if len(values) > 1 else ""
            parts.append(f"shared {label} {shown}{extra}")
            break

        if not parts:
            # Only a cosine that actually earned weight explains an edge. A
            # sub-gate cosine contributed nothing to the score, so rendering it
            # replaces the real justification with a near-zero number on the one
            # screen where an operator is asked to trust the scoring.
            #
            # Tests the weight's *value*, not the presence of a marker and not
            # the presence of a field. Both weaker forms admit a sub-gate cosine
            # through some future emitter: ``not below_gate`` if the marker is
            # ever omitted, ``weight is not None`` if a non-contributing signal
            # is ever recorded as ``{"cosine": -0.01, "weight": 0.0}`` — which is
            # a natural thing to write. ``> 0`` is the property the hover claims.
            #
            # ``float()`` under suppress rather than ``isinstance``: a weight
            # arriving as a JSON string still counts as contribution, and a
            # missing or unparseable one stays silent instead of raising.
            narrative = signals.get("narrative")
            narrative_weight: float | None = None
            if isinstance(narrative, dict):
                with contextlib.suppress(TypeError, ValueError):
                    narrative_weight = float(narrative.get("weight"))  # type: ignore[arg-type]
            if (
                isinstance(narrative, dict)
                and narrative.get("cosine") is not None
                and narrative_weight is not None
                and narrative_weight > 0
            ):
                parts.append(f"narrative cosine {float(narrative['cosine']):.2f}")

        if not parts and isinstance(signals.get("mo_overlap"), dict):
            parts.append("shared MO phases")

    if not parts:
        parts.append("linked")

    with contextlib.suppress(TypeError, ValueError):
        parts.append(f"w {float(score):.2f}")

    # Two edges can carry an identical strongest signal and still differ in
    # score, purely because one earned the temporal-proximity boost. Live data
    # has pairs reading "shared DOMAIN bnm-verify…" at both 0.90 and 1.00;
    # without naming the multiplier the hover asserts the same justification
    # for two different numbers and the operator cannot tell them apart.
    if isinstance(signals, dict):
        temporal = signals.get("temporal")
        if isinstance(temporal, dict) and temporal.get("applied"):
            with contextlib.suppress(TypeError, ValueError):
                multiplier = float(temporal.get("multiplier"))
                if multiplier != 1.0:
                    parts.append(f"temporal ×{multiplier:.2f}")

    if ordinal_a is not None and ordinal_b is not None:
        # case_links stores the pair ordered by UUID, which surfaces as
        # "cases #119,#111"; operators read these as case numbers, so order
        # them as numbers.
        low, high = sorted((ordinal_a, ordinal_b))
        parts.append(f"cases #{low},#{high}")

    return " · ".join(parts)
