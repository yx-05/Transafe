"""Role-based redaction — L6.

Redaction is **server-side and structural**. It runs on the retrieved payload
*before* the Liaison Agent is given anything to reason over, so the model is
incapable of reading a field the caller is not entitled to. It is not a prompt
instruction, and it therefore cannot be prompt-injected away.

Three properties matter here and each is tested:

* **Recursive** — nested dicts, lists of dicts and lists of scalars are all
  walked. A secret one level deeper than the walker is a leak.
* **Deny-by-default** — an unknown role collapses to :data:`DEFAULT_VISIBILITY`
  (aggregate statistics only), never to "everything".
* **Total for the public role** — ``public`` / ``external_researcher`` see no
  PII, no transcript text, no account numbers, no phone numbers, no victim
  names, no case ids and no indicators.

Free-text and the limits of key matching
----------------------------------------
:func:`redact_by_role` matches *key names*. That is the right tool for
structured records and the wrong tool for payloads whose sensitivity depends on
what a human or a model wrote rather than on the key it landed under. Two such
payloads exist in the v2 read paths and each is handled explicitly rather than
left to the walker:

* ``case_mo.narrative`` — prose written *from* the transcript, so it carries
  whatever the transcript carried. Listed under the ``transcripts`` category,
  not ``mo_fingerprint``.
* ``mcp_access_log.params`` / ``.citations`` — the previous caller's own
  arguments and results. Handled by :func:`project_log_entry`, a whitelist,
  because the keys involved (``value``, ``question``) are far too generic to
  blank globally yet are exactly where an account number ends up.

Role vocabulary
---------------
``01_upgrade_plan.md`` §9.3 and ``04_mcp_gateway.md`` §5.1 define six roles
(``fraud_ops``, ``compliance``, ``customer_service``, ``legal``,
``partner_bank``, ``external_researcher``); the B6 task brief names
``auditor``/``public`` instead of ``legal``/``external_researcher``; and the
shipped console (Screen G) offers ``analyst``/``public``. Rather than silently
pick a winner, this module defines the **union** — every name from every source
resolves to an explicit, least-privilege policy, and anything unrecognised
falls through to :data:`DEFAULT_VISIBILITY`.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)

REDACTION_MARKER = "[REDACTED]"

#: Everything ``fraud_ops`` can see — also the vocabulary of resource names
#: understood by :func:`can_access`.
ALL_RESOURCES: frozenset[str] = frozenset(
    {
        "campaign",
        "cases",
        "case_ids",
        "entities",
        "transcripts",
        "mo_fingerprint",
        "artifacts",
        "compliance_brief",
        "cs_advisory",
        "indicators",
        "aggregate",
        "pii",
        "account_numbers",
        "phone_numbers",
    }
)

#: Resource categories each role is entitled to see.
ROLE_VISIBILITY: dict[str, set[str]] = {
    # Internal fraud operations — the only role with no restriction.
    "fraud_ops": set(ALL_RESOURCES),
    # Campaign + aggregate + case ids + compliance_brief. Never transcripts/PII.
    "compliance": {
        "campaign",
        "cases",
        "case_ids",
        "compliance_brief",
        "mo_fingerprint",
        "indicators",
        "artifacts",
        "aggregate",
    },
    # Campaign pack + cs_advisory. Never transcripts, PII, compliance briefs.
    "customer_service": {
        "campaign",
        "cs_advisory",
        "indicators",
        "artifacts",
        "aggregate",
    },
    # Campaign narrative, citations, counts. Never account numbers or identity.
    "legal": {
        "campaign",
        "case_ids",
        "mo_fingerprint",
        "artifacts",
        "aggregate",
    },
    # Governance/audit trail: who approved what, when. Never customer data.
    "auditor": {
        "campaign",
        "cases",
        "case_ids",
        "mo_fingerprint",
        "compliance_brief",
        "cs_advisory",
        "artifacts",
        "aggregate",
    },
    # Console "analyst" role: structural intelligence, no customer data.
    "analyst": {
        "campaign",
        "case_ids",
        "mo_fingerprint",
        "indicators",
        "artifacts",
        "aggregate",
    },
    # Indicators + MO only. No customer data, no case ids, no campaign identity.
    "partner_bank": {
        "indicators",
        "mo_fingerprint",
        "aggregate",
    },
    # Aggregate statistics only.
    "external_researcher": {"aggregate"},
    "public": {"aggregate"},
}

#: Applied to any role not present in :data:`ROLE_VISIBILITY`. Deny by default.
DEFAULT_VISIBILITY: frozenset[str] = frozenset({"aggregate"})

#: Sensitive value categories → the concrete field names that carry them.
#: Deliberately generous: a false-positive redaction is a cosmetic bug, a
#: false-negative is a data breach.
REDACTED_FIELDS: dict[str, list[str]] = {
    "transcripts": [
        "utterance",
        "utterances",
        "speaker",
        "transcript",
        "transcripts",
        "transcript_text",
        "raw_transcript",
        "dialogue",
        # ``case_mo.narrative`` is free-text prose the MO extractor wrote *from*
        # the transcript, so it carries whatever the transcript carried —
        # victim names, account numbers, quoted speech. It belongs to the
        # transcripts category, not to ``mo_fingerprint`` (which is structured
        # JSONB and safe to share). Roles denied transcripts are denied this.
        "narrative",
        "mo_narrative",
        "case_narrative",
    ],
    "pii": [
        "user_id",
        "customer_id",
        "customer_name",
        "customer_ic",
        "customer_phone",
        "victim_name",
        "victim_names",
        "nric",
        "ic_number",
        "email",
        "address",
        "date_of_birth",
    ],
    "account_numbers": [
        "recipient_account",
        "sender_account",
        "account_number",
        "account_no",
        "iban",
        "card_number",
    ],
    "phone_numbers": [
        "phone",
        "phones",
        "phone_number",
        "caller_phone",
        "msisdn",
    ],
}

#: Structural categories → field names removed wholesale when not entitled.
STRUCTURAL_FIELDS: dict[str, list[str]] = {
    "compliance_brief": ["compliance_brief"],
    "cs_advisory": ["cs_advisory"],
    "case_ids": ["case_ids", "cited_cases", "case_id"],
    "entities": ["entities"],
    "cases": ["cases", "case_evidence"],
    "indicators": ["indicators"],
    "mo_fingerprint": ["mo_fingerprint", "fingerprint"],
    "campaign": ["campaign", "campaigns", "campaign_id", "linked_campaigns"],
    "artifacts": ["artifacts", "content", "content_json"],
}

#: Every category the redactor knows how to withhold.
ALL_CATEGORIES: tuple[str, ...] = tuple(
    sorted({*REDACTED_FIELDS.keys(), *STRUCTURAL_FIELDS.keys()})
)


def visibility_for(role: str) -> set[str]:
    """Return the resource categories ``role`` is entitled to see.

    Matching is **exact and case-sensitive**. ``FRAUD_OPS`` is not
    ``fraud_ops``; it is an unknown role and collapses to least privilege.
    That is the safe direction — a mistyped role can only ever yield *less*
    data — and it is left case-sensitive on purpose: normalising case here
    would mean an access-control decision widening on the strength of a
    string transform. The cost is that an operator who upper-cases
    ``?as_role=`` gets the public lens rather than an error; the fallback is
    logged below, so the surprise is at least diagnosable server-side.

    Args:
        role: Caller role name.

    Returns:
        Set of resource category names. Unknown roles get
        :data:`DEFAULT_VISIBILITY` — deny by default, never allow by default.
    """
    visible = ROLE_VISIBILITY.get(role)
    if visible is None:
        logger.warning("redaction: unknown role %r — falling back to least privilege", role)
        return set(DEFAULT_VISIBILITY)
    return set(visible)


def redacted_categories_for(role: str) -> list[str]:
    """Return the sorted categories withheld from ``role``.

    Used by ``GET /enterprise/mcp/log`` so Screen G can label each row with
    what the caller did *not* receive.

    Args:
        role: Caller role name.

    Returns:
        Sorted list of withheld category names; ``[]`` for ``fraud_ops``.
    """
    visible = visibility_for(role)
    return [category for category in ALL_CATEGORIES if category not in visible]


def has_full_visibility(role: str) -> bool:
    """Return whether ``role`` is entitled to every resource category.

    Args:
        role: Caller role name.

    Returns:
        ``True`` only for roles holding the complete :data:`ALL_RESOURCES` set
        (in practice ``fraud_ops``).
    """
    return visibility_for(role) >= set(ALL_RESOURCES)


#: Audit-row keys that are pure access metadata and carry no case content.
#: Everything outside this whitelist is caller-supplied free-form data.
AUDIT_METADATA_FIELDS: tuple[str, ...] = (
    "id",
    "ts",
    "caller",
    "role",
    "tool",
    "latency_ms",
)


def project_log_entry(entry: dict[str, Any], role: str) -> dict[str, Any]:
    """Project one ``mcp_access_log`` row down to what ``role`` may see.

    This is a **whitelist**, not a field-name redaction, and the distinction is
    the whole point. An audit row's ``params`` holds whatever the *original*
    caller typed — a free-text ``question``, an ``ACCOUNT`` indicator value, a
    case id — and its ``citations`` hold campaign codes. Those are content, not
    metadata, and their sensitivity depends on what a human wrote rather than
    on the key it was written under. :func:`redact_by_role` matches key names,
    so it cannot and must not be relied on here: ``value`` and ``question`` are
    generic keys that would be catastrophic to blank globally, yet they are
    exactly where an account number or a victim's name ends up in this table.

    Without this projection the audit log is a bypass: any role could read what
    a ``fraud_ops`` caller asked and what came back, and so obtain by proxy the
    data the primary path denies it.

    Args:
        entry: One raw ``mcp_access_log`` row.
        role: Role the *reader* holds — not the role the logged call ran under.

    Returns:
        A new dict with access metadata, ``outcome``, ``redacted_fields`` and
        ``citation_count`` always present; ``params`` and ``citations`` in full
        only when ``role`` has full visibility, otherwise withheld.
    """
    params = entry.get("params")
    params = params if isinstance(params, dict) else {}
    citations = entry.get("citations")
    citation_count = len(citations) if isinstance(citations, list) else 0

    projected: dict[str, Any] = {key: entry.get(key) for key in AUDIT_METADATA_FIELDS}
    projected["outcome"] = params.get("outcome")
    # The reader's own withheld categories, so a console can label the row.
    projected["redacted_fields"] = redacted_categories_for(role)
    projected["citation_count"] = citation_count

    if has_full_visibility(role):
        projected["params"] = dict(params)
        projected["citations"] = citations
    else:
        # Outcome is metadata and survives; the arguments themselves do not.
        projected["params"] = {"outcome": params.get("outcome")}
        projected["citations"] = None
    return projected


def redact_by_role(data: Any, role: str) -> Any:
    """Apply role-based redaction to a data payload.

    Server-side, before synthesis. The Liaison Agent never sees fields the
    caller is not entitled to, because they are gone by the time it is called.

    Args:
        data: The raw payload — a dict, a list, or any nested combination.
        role: Caller role. Unrecognised roles get least privilege.

    Returns:
        A **copy** of ``data`` with every forbidden field's value replaced by
        ``"[REDACTED]"``. The input is never mutated and the shape is
        preserved, so a caller can still see *that* a field existed.
    """
    visible = visibility_for(role)
    result = copy.deepcopy(data)

    # fraud_ops sees everything — short-circuit rather than iterate a full set,
    # so the "no restriction" case cannot drift as field lists grow.
    if visible >= set(ALL_RESOURCES):
        return result

    for category, fields in REDACTED_FIELDS.items():
        if category in visible:
            continue
        for field in fields:
            result = _redact_field(result, field)

    for category, fields in STRUCTURAL_FIELDS.items():
        if category in visible:
            continue
        for field in fields:
            result = _redact_field(result, field)

    return result


def _redact_field(data: Any, field_name: str) -> Any:
    """Recursively replace every occurrence of ``field_name`` with the marker.

    Walks dicts, lists of dicts, lists of scalars, and arbitrary nesting of the
    three. A matched key's value is replaced outright and not descended into.

    Args:
        data: Node to walk.
        field_name: Key whose value must be withheld.

    Returns:
        The rewritten node.
    """
    if isinstance(data, dict):
        for key in list(data.keys()):
            if key == field_name:
                data[key] = REDACTION_MARKER
            else:
                data[key] = _redact_field(data[key], field_name)
        return data
    if isinstance(data, list):
        return [_redact_field(item, field_name) for item in data]
    if isinstance(data, tuple):
        return tuple(_redact_field(item, field_name) for item in data)
    return data


def can_access(role: str, resource: str) -> bool:
    """Check whether a role may access a resource category.

    Args:
        role: Role name.
        resource: Resource category name, e.g. ``transcripts`` or ``aggregate``.

    Returns:
        ``True`` when entitled. Unknown roles and unknown resources are denied.
    """
    return resource in visibility_for(role)
