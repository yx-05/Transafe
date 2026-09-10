"""Artifact registry — L4.

Append-only, versioned, attributed store for **both** artifact tiers
(``core`` and ``pack``). The diff view is the same for both.

Properties (01_upgrade_plan.md §7.2, 03_artifact_registry.md §6):

* **Immutable versions** — once a row is written it is never updated or
  deleted. Rollback republishes an old body as a *new* version.
* **Diffable** — every version can be diffed against its predecessor.
* **Attributed** — every version traces to the campaign(s) that justified it.
* **Consumption receipts** — ``artifact_consumption`` proves an agent loaded it.
* **Effectiveness record** — written back by the evaluation harness (§11).

Every read is failure-tolerant: the v2 migration may not be applied yet, so a
missing table renders as ``[]`` / ``None``, never an exception.
"""

from __future__ import annotations

import difflib
import logging
from datetime import UTC, datetime
from typing import Any

from src.db.vector_store import get_supabase_client

logger = logging.getLogger(__name__)

ARTIFACTS_TABLE = "artifacts"
CONSUMPTION_TABLE = "artifact_consumption"

VALID_TIERS: frozenset[str] = frozenset({"core", "pack"})
VALID_STATUSES: frozenset[str] = frozenset({"DRAFT", "PUBLISHED", "ROLLED_BACK"})
VALID_ARTIFACT_TYPES: frozenset[str] = frozenset(
    {
        "campaign_pack",
        "phishing_playbook_patch",
        "txn_rule",
        "cs_advisory",
        "compliance_brief",
        "phone_agent_core",
    }
)


def _resolve_client(client: Any | None = None) -> Any:
    """Return the injected Supabase client, or the process-wide one."""
    return client if client is not None else get_supabase_client()


def _data(result: Any) -> list[dict[str, Any]]:
    """Extract rows from a Supabase response, tolerating ``None``."""
    return [dict(row) for row in (getattr(result, "data", None) or [])]


# ── Write path ───────────────────────────────────────────────────────────────
def next_version(name: str, client: Any | None = None) -> int:
    """Return the next version number for ``name`` (1 when nothing exists).

    Args:
        name: Artifact name.
        client: Optional injected Supabase client.

    Returns:
        The next integer version. Falls back to ``1`` on any query failure.
    """
    try:
        supabase = _resolve_client(client)
        result = (
            supabase.table(ARTIFACTS_TABLE)
            .select("version")
            .eq("name", name)
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
        rows = _data(result)
    except Exception:
        logger.exception("registry: version lookup failed for %s", name)
        return 1

    if not rows:
        return 1
    try:
        return int(rows[0]["version"]) + 1
    except (KeyError, TypeError, ValueError):
        return 1


def publish_artifact(
    name: str,
    tier: str,
    artifact_type: str,
    target_agent: str,
    content: str,
    content_json: dict[str, Any] | None = None,
    campaign_id: str | None = None,
    source_campaigns: list[str] | None = None,
    created_by: str = "compiler",
    approved_by: str = "fraud_ops",
    status: str = "PUBLISHED",
    client: Any | None = None,
) -> dict[str, Any] | None:
    """Publish a new, immutable version of an artifact.

    Args:
        name: Artifact name (e.g. ``phone_agent_core``, ``SCAM-027``).
        tier: ``core`` or ``pack``.
        artifact_type: One of :data:`VALID_ARTIFACT_TYPES`.
        target_agent: Agent that consumes this artifact.
        content: Text content (Markdown for core, JSON string for pack).
        content_json: Optional structured JSON body.
        campaign_id: Campaign UUID (``None`` for core tier).
        source_campaigns: Campaign codes that justified a core generalisation.
        created_by: ``compiler`` | ``generaliser`` | ``human``.
        approved_by: Name of the human approver.
        status: ``DRAFT`` | ``PUBLISHED`` | ``ROLLED_BACK``.
        client: Optional injected Supabase client.

    Returns:
        The stored artifact row, or ``None`` on failure.
    """
    if tier not in VALID_TIERS:
        logger.warning("registry: unknown tier %r for artifact %s", tier, name)
    if status not in VALID_STATUSES:
        logger.warning("registry: unknown status %r — coercing to PUBLISHED", status)
        status = "PUBLISHED"

    supabase = _resolve_client(client)
    version = next_version(name, client=supabase)

    row = {
        "name": name,
        "tier": tier,
        "artifact_type": artifact_type,
        "target_agent": target_agent,
        "version": version,
        "content": content,
        "content_json": content_json,
        "campaign_id": campaign_id,
        "source_campaigns": source_campaigns or [],
        "status": status,
        "created_by": created_by,
        "approved_by": approved_by,
    }

    try:
        result = supabase.table(ARTIFACTS_TABLE).insert(row).execute()
    except Exception:
        logger.exception("registry: failed to publish %s v%d", name, version)
        return None

    rows = _data(result)
    if not rows:
        logger.error("registry: insert of %s v%d returned no row", name, version)
        return None
    return rows[0]


def rollback_artifact(
    name: str,
    to_version: int,
    approved_by: str = "fraud_ops",
    client: Any | None = None,
) -> dict[str, Any] | None:
    """Roll back by **republishing** an earlier body as a new version.

    Append-only: the historical rows are never mutated or deleted. Rolling
    ``v7`` back to ``v5`` publishes ``v8`` whose content equals ``v5``.

    Args:
        name: Artifact name.
        to_version: The version whose body should be republished.
        approved_by: Name of the human approver.
        client: Optional injected Supabase client.

    Returns:
        The newly published artifact row, or ``None`` when the target version
        does not exist or the insert fails.
    """
    supabase = _resolve_client(client)
    target = get_artifact(name, to_version, client=supabase)
    if not target:
        logger.warning("registry: rollback target %s v%s not found", name, to_version)
        return None

    return publish_artifact(
        name=name,
        tier=target.get("tier", "pack"),
        artifact_type=target.get("artifact_type", "campaign_pack"),
        target_agent=target.get("target_agent", "phone_worker"),
        content=target.get("content", ""),
        content_json=target.get("content_json"),
        campaign_id=target.get("campaign_id"),
        source_campaigns=target.get("source_campaigns") or [],
        created_by="human",
        approved_by=approved_by,
        client=supabase,
    )


# ── Read path ────────────────────────────────────────────────────────────────
def get_artifact(
    name: str,
    version: int | None = None,
    client: Any | None = None,
) -> dict[str, Any] | None:
    """Return one published artifact version (latest when ``version`` is None).

    Args:
        name: Artifact name.
        version: Specific version, or ``None`` for the latest published one.
        client: Optional injected Supabase client.

    Returns:
        The artifact row, or ``None`` when absent / on failure.
    """
    try:
        supabase = _resolve_client(client)
        query = (
            supabase.table(ARTIFACTS_TABLE).select("*").eq("name", name).eq("status", "PUBLISHED")
        )
        if version is not None:
            query = query.eq("version", version)
        else:
            query = query.order("version", desc=True).limit(1)
        rows = _data(query.execute())
    except Exception:
        logger.exception("registry: get_artifact failed for %s v%s", name, version)
        return None

    return rows[0] if rows else None


def list_artifact_versions(name: str, client: Any | None = None) -> list[dict[str, Any]]:
    """Return every stored version of ``name``, newest first.

    Args:
        name: Artifact name.
        client: Optional injected Supabase client.

    Returns:
        List of artifact rows; empty on failure.
    """
    try:
        supabase = _resolve_client(client)
        result = (
            supabase.table(ARTIFACTS_TABLE)
            .select("*")
            .eq("name", name)
            .order("version", desc=True)
            .execute()
        )
        return _data(result)
    except Exception:
        logger.exception("registry: version history failed for %s", name)
        return []


def list_artifacts(
    tier: str | None = None,
    campaign_id: str | None = None,
    name: str | None = None,
    client: Any | None = None,
) -> list[dict[str, Any]]:
    """List published artifacts (latest version per name).

    Args:
        tier: Filter by ``core`` or ``pack``.
        campaign_id: Filter by originating campaign.
        name: Filter by exact artifact name.
        client: Optional injected Supabase client.

    Returns:
        One row per artifact name — the highest version. Empty on failure.
    """
    try:
        supabase = _resolve_client(client)
        query = supabase.table(ARTIFACTS_TABLE).select("*").eq("status", "PUBLISHED")
        if tier:
            query = query.eq("tier", tier)
        if campaign_id:
            query = query.eq("campaign_id", campaign_id)
        if name:
            query = query.eq("name", name)
        rows = _data(query.order("created_at", desc=True).execute())
    except Exception:
        logger.exception("registry: list_artifacts failed")
        return []

    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("name", ""))
        current = latest.get(key)
        if current is None or int(row.get("version", 0)) > int(current.get("version", 0)):
            latest[key] = row
    return [*latest.values()]


def get_artifact_diff(
    name: str,
    version: int,
    client: Any | None = None,
) -> dict[str, Any] | None:
    """Return an artifact version together with its diff against ``version - 1``.

    The diff intentionally reads *all* rows, not only ``PUBLISHED`` ones, so a
    rolled-back predecessor still renders in the registry timeline.

    Args:
        name: Artifact name.
        version: Version to display.
        client: Optional injected Supabase client.

    Returns:
        ``{"current", "previous", "diff"}``, or ``None`` when the version is
        unknown.
    """
    supabase = _resolve_client(client)

    try:
        current_rows = _data(
            supabase.table(ARTIFACTS_TABLE)
            .select("*")
            .eq("name", name)
            .eq("version", version)
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception("registry: diff lookup failed for %s v%s", name, version)
        return None

    if not current_rows:
        return None
    current = current_rows[0]

    previous: dict[str, Any] | None = None
    if version > 1:
        try:
            previous_rows = _data(
                supabase.table(ARTIFACTS_TABLE)
                .select("*")
                .eq("name", name)
                .eq("version", version - 1)
                .execute()
            )
            previous = previous_rows[0] if previous_rows else None
        except Exception:
            logger.exception("registry: previous-version lookup failed for %s", name)

    return {
        "current": current,
        "previous": previous,
        "diff": _compute_diff(
            (previous or {}).get("content") or "",
            current.get("content") or "",
        ),
    }


# ── Receipts and effectiveness ───────────────────────────────────────────────
def record_consumption(
    artifact_id: str,
    agent_name: str,
    client: Any | None = None,
) -> bool:
    """Record a consumption receipt proving an agent loaded an artifact.

    Args:
        artifact_id: UUID of the artifact.
        agent_name: Consuming agent.
        client: Optional injected Supabase client.

    Returns:
        ``True`` when the receipt was written, ``False`` on failure.
    """
    try:
        supabase = _resolve_client(client)
        supabase.table(CONSUMPTION_TABLE).upsert(
            {
                "artifact_id": artifact_id,
                "agent_name": agent_name,
                "consumed_at": datetime.now(UTC).isoformat(),
            }
        ).execute()
        return True
    except Exception:
        logger.exception(
            "registry: failed to record consumption of %s by %s", artifact_id, agent_name
        )
        return False


def get_consumption(artifact_id: str, client: Any | None = None) -> list[dict[str, Any]]:
    """Return the consumption receipts for one artifact.

    Args:
        artifact_id: UUID of the artifact.
        client: Optional injected Supabase client.

    Returns:
        List of receipt rows; empty on failure.
    """
    try:
        supabase = _resolve_client(client)
        result = (
            supabase.table(CONSUMPTION_TABLE)
            .select("*")
            .eq("artifact_id", artifact_id)
            .execute()
        )
        return _data(result)
    except Exception:
        logger.exception("registry: consumption lookup failed for %s", artifact_id)
        return []


def update_effectiveness(
    artifact_id: str,
    effectiveness: dict[str, Any],
    client: Any | None = None,
) -> bool:
    """Write an evaluation result back onto an artifact.

    ``effectiveness`` is metadata *about* a version, not the version body, so
    writing it does not violate append-only immutability of ``content``.

    Args:
        artifact_id: UUID of the artifact.
        effectiveness: ``{eval_run_id, detected, total, fp, fp_total, measured_at}``.
        client: Optional injected Supabase client.

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    try:
        supabase = _resolve_client(client)
        supabase.table(ARTIFACTS_TABLE).update({"effectiveness": effectiveness}).eq(
            "id", artifact_id
        ).execute()
        return True
    except Exception:
        logger.exception("registry: failed to write effectiveness for %s", artifact_id)
        return False


# ── Diffing ──────────────────────────────────────────────────────────────────
def _compute_diff(old: str, new: str) -> list[dict[str, str]]:
    """Compute a line-level unified diff between two bodies.

    Args:
        old: Previous content.
        new: Current content.

    Returns:
        List of ``{"type": "added"|"removed"|"context", "line": str}``.
    """
    old_lines = old.splitlines()
    new_lines = new.splitlines()

    diff: list[dict[str, str]] = []
    for index, line in enumerate(difflib.unified_diff(old_lines, new_lines, lineterm="", n=3)):
        # The first two emitted lines are the ``---``/``+++`` file headers.
        if index < 2 or line.startswith("@@"):
            continue
        if line.startswith("+"):
            diff.append({"type": "added", "line": line[1:]})
        elif line.startswith("-"):
            diff.append({"type": "removed", "line": line[1:]})
        elif line.startswith(" "):
            diff.append({"type": "context", "line": line[1:]})
    return diff


# ── Short aliases (registry.publish / registry.get / …) ──────────────────────
publish = publish_artifact
get = get_artifact
diff = get_artifact_diff
rollback = rollback_artifact
write_effectiveness = update_effectiveness
