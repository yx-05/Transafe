"""Artifact propagation — L5.

Publishing an artifact emits a ``propagation_event`` per subscribed agent, and
each agent acknowledges by writing a **consumption receipt** into
``artifact_consumption`` (01_upgrade_plan.md §8, 03_artifact_registry.md §7).

Propagation is what makes the learning loop *visible*: a publish fans out to
its subscribers and the receipts come back, which is the observable difference
between "the system wrote a document" and "the system changed how it behaves".

Two artifact types have no in-process subscriber — ``cs_advisory`` and
``compliance_brief`` are consumed externally over MCP — so an empty result
list is a correct outcome, not a failure. Failing to notify one agent never
blocks the others and never fails the publish: receipts are an observability
guarantee, not a transaction.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from src.enterprise.events import emit_event
from src.enterprise.registry import publish_artifact, record_consumption

logger = logging.getLogger(__name__)

#: Strong references to fire-and-forget propagation tasks.
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()

#: Which in-process agents consume which artifact type.
SUBSCRIPTION_MAP: dict[str, list[str]] = {
    "campaign_pack": ["phone_worker"],
    "phishing_playbook_patch": ["phishing_worker"],
    "txn_rule": ["financial_worker"],
    "cs_advisory": [],  # consumed externally via MCP
    "compliance_brief": [],  # consumed externally via MCP
    "phone_agent_core": ["phone_worker"],
}

#: ``artifact_type -> (name_suffix, tier, target_agent)`` for campaign packs.
#: ``campaign_pack`` keeps the bare campaign code as its name because that is
#: the key the phone worker retrieves at runtime; the other types are suffixed
#: so that per-name versioning never collides between artifact types.
ARTIFACT_SPECS: dict[str, tuple[str, str, str]] = {
    "campaign_pack": ("", "pack", "phone_worker"),
    "phishing_playbook_patch": ("_phishing_playbook_patch", "pack", "phishing_worker"),
    "txn_rule": ("_txn_rule", "pack", "financial_worker"),
    "cs_advisory": ("_cs_advisory", "pack", "customer_service"),
    "compliance_brief": ("_compliance_brief", "pack", "compliance"),
}


async def emit_artifact_published(artifact: dict[str, Any]) -> None:
    """Emit the ``registry/artifact_published`` event for a new version.

    Publishing is a state mutation, so it must announce itself: the console
    does not poll, it re-fetches when a relevant ``ns_event`` arrives. This is
    emitted once per published version — the aggregate ``artifacts_published``
    the approval pipeline emits afterwards summarises a whole campaign batch
    and cannot tell a subscriber *which* version landed.

    Args:
        artifact: The published artifact row.
    """
    if not artifact:
        return
    await emit_event(
        layer="registry",
        event_type="artifact_published",
        payload={
            "artifact_id": artifact.get("id"),
            "artifact_name": artifact.get("name"),
            "artifact_type": artifact.get("artifact_type"),
            "tier": artifact.get("tier"),
            "version": artifact.get("version"),
            "campaign_id": artifact.get("campaign_id"),
            "source_campaigns": artifact.get("source_campaigns") or [],
        },
    )


def subscribers_for(artifact_type: str) -> list[str]:
    """Return the agents subscribed to an artifact type.

    Args:
        artifact_type: The artifact type.

    Returns:
        List of agent names; empty when the artifact is consumed externally.
    """
    return list(SUBSCRIPTION_MAP.get(artifact_type, []))


async def propagate_artifact(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """Propagate a published artifact to every subscribed agent.

    Args:
        artifact: Published artifact dict with ``id``, ``name``,
            ``artifact_type`` and ``version``.

    Returns:
        One ``{agent_name, artifact_id, artifact_name, version, status}`` dict
        per subscriber. Empty when nothing subscribes to the type.
    """
    if not artifact:
        return []

    artifact_type = str(artifact.get("artifact_type", ""))
    subscribed_agents = SUBSCRIPTION_MAP.get(artifact_type, [])
    if not subscribed_agents:
        logger.info("propagation: no in-process subscriber for %s", artifact_type)
        return []

    artifact_id = artifact.get("id")
    artifact_name = artifact.get("name")
    version = artifact.get("version")

    results: list[dict[str, Any]] = []
    for agent_name in subscribed_agents:
        payload = {
            "artifact_id": artifact_id,
            "artifact_name": artifact_name,
            "artifact_type": artifact_type,
            "tier": artifact.get("tier"),
            "version": version,
            "agent_name": agent_name,
        }

        status = "acknowledged"
        try:
            await emit_event(
                layer="propagation",
                event_type="propagation_event",
                payload=payload,
            )
            record_consumption(artifact_id, agent_name)
            await emit_event(
                layer="propagation",
                event_type="propagation_acknowledged",
                payload=payload,
            )
        except Exception:
            logger.exception("propagation: failed to notify %s", agent_name)
            status = "failed"

        results.append(
            {
                "agent_name": agent_name,
                "artifact_id": artifact_id,
                "artifact_name": artifact_name,
                "version": version,
                "status": status,
            }
        )

    return results


async def propagate_campaign_artifacts(
    campaign_id: str,
    compiled_artifacts: dict[str, Any],
    campaign_data: dict[str, Any],
    approved_by: str = "fraud_ops",
    client: Any | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Publish and propagate every compiled pack-tier artifact of a campaign.

    Args:
        campaign_id: UUID of the approved campaign.
        compiled_artifacts: Dict from ``compiler.compile_campaign``.
        campaign_data: Campaign dict with ``code`` and ``name``.
        approved_by: The human who approved the campaign.
        client: Optional injected Supabase client.

    Returns:
        ``artifact_type -> list of propagation results``.
    """
    code = campaign_data.get("code", "UNKNOWN")
    results: dict[str, list[dict[str, Any]]] = {}

    for art_type, content in (compiled_artifacts or {}).items():
        spec = ARTIFACT_SPECS.get(art_type)
        if spec is None:
            continue
        suffix, tier, target_agent = spec

        if isinstance(content, dict):
            content_str = json.dumps(content, indent=2, ensure_ascii=False)
            content_json = content
        else:
            content_str = str(content)
            content_json = None

        artifact = publish_artifact(
            name=f"{code}{suffix}",
            tier=tier,
            artifact_type=art_type,
            target_agent=target_agent,
            content=content_str,
            content_json=content_json,
            campaign_id=campaign_id,
            created_by="compiler",
            approved_by=approved_by,
            client=client,
        )

        if artifact:
            await emit_artifact_published(artifact)
            results[art_type] = await propagate_artifact(artifact)
        else:
            logger.error("propagation: publish failed for %s/%s", code, art_type)

    return results


async def publish_and_propagate_core(
    content: str,
    proposal: dict[str, Any],
    approved_by: str = "fraud_ops",
    client: Any | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Publish a generalised ``phone_agent_core`` version and propagate it.

    Args:
        content: The new core-skill body.
        proposal: The validated generaliser proposal (used for attribution).
        approved_by: The human who approved the change.
        client: Optional injected Supabase client.

    Returns:
        ``(artifact_row_or_None, propagation_results)``.
    """
    artifact = publish_artifact(
        name="phone_agent_core",
        tier="core",
        artifact_type="phone_agent_core",
        target_agent="phone_worker",
        content=content,
        content_json={
            "rule_id": proposal.get("rule_id"),
            "rule_text": proposal.get("rule_text"),
            "justification": proposal.get("justification"),
            "evidence_summary": proposal.get("evidence_summary"),
        },
        source_campaigns=proposal.get("source_campaigns") or [],
        created_by="generaliser",
        approved_by=approved_by,
        client=client,
    )
    if not artifact:
        return None, []
    await emit_artifact_published(artifact)
    return artifact, await propagate_artifact(artifact)


def propagate_artifact_sync(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """Synchronous wrapper around :func:`propagate_artifact`.

    When an event loop is already running the propagation is scheduled on it
    and an empty list is returned immediately.

    Args:
        artifact: The published artifact row.

    Returns:
        Propagation results, or ``[]`` when scheduled on a running loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(propagate_artifact(artifact))

    task = asyncio.ensure_future(propagate_artifact(artifact))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return []
