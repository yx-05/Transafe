"""Unit tests for propagation (L5).

Implements the cases specified in doc/transafe_v2/03_artifact_registry.md §9.5.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.enterprise.propagation import (
    SUBSCRIPTION_MAP,
    propagate_artifact,
    propagate_campaign_artifacts,
    publish_and_propagate_core,
    subscribers_for,
)


def _published_calls(mock_emit: AsyncMock) -> list[Any]:
    """Return the ``artifact_published`` emissions recorded on an emit mock."""
    return [c for c in mock_emit.await_args_list if c.kwargs["event_type"] == "artifact_published"]


def test_subscription_map_covers_pack_types() -> None:
    """Every pack type has a subscription; MCP-only types have none."""
    assert "phone_worker" in SUBSCRIPTION_MAP["campaign_pack"]
    assert "phishing_worker" in SUBSCRIPTION_MAP["phishing_playbook_patch"]
    assert "financial_worker" in SUBSCRIPTION_MAP["txn_rule"]
    assert SUBSCRIPTION_MAP["cs_advisory"] == []
    assert SUBSCRIPTION_MAP["compliance_brief"] == []


def test_subscribers_for_unknown_type() -> None:
    """An unknown artifact type has no subscribers."""
    assert subscribers_for("not_a_type") == []


@pytest.mark.asyncio
async def test_propagate_artifact_emits_events() -> None:
    """Propagation emits two events per agent and records a receipt."""
    artifact = {
        "id": "art-1",
        "name": "SCAM-027",
        "artifact_type": "campaign_pack",
        "version": 1,
    }
    with (
        patch("src.enterprise.propagation.emit_event", new_callable=AsyncMock) as mock_emit,
        patch("src.enterprise.propagation.record_consumption") as mock_record,
    ):
        results = await propagate_artifact(artifact)

    assert len(results) == 1
    assert results[0]["agent_name"] == "phone_worker"
    assert results[0]["status"] == "acknowledged"
    # Two events per agent: propagation_event + propagation_acknowledged.
    assert mock_emit.call_count == 2
    mock_record.assert_called_once_with("art-1", "phone_worker")


@pytest.mark.asyncio
async def test_propagate_artifact_no_subscribers() -> None:
    """Artifacts consumed externally (cs_advisory) produce no results."""
    artifact = {
        "id": "art-2",
        "name": "SCAM-027_cs_advisory",
        "artifact_type": "cs_advisory",
        "version": 1,
    }
    with (
        patch("src.enterprise.propagation.emit_event", new_callable=AsyncMock),
        patch("src.enterprise.propagation.record_consumption"),
    ):
        results = await propagate_artifact(artifact)
    assert results == []


@pytest.mark.asyncio
async def test_propagate_artifact_survives_receipt_failure() -> None:
    """A failed notification degrades that agent only, and never raises."""
    artifact = {
        "id": "art-3",
        "name": "SCAM-027",
        "artifact_type": "campaign_pack",
        "version": 2,
    }
    with (
        patch("src.enterprise.propagation.emit_event", new_callable=AsyncMock),
        patch(
            "src.enterprise.propagation.record_consumption",
            side_effect=RuntimeError("table missing"),
        ),
    ):
        results = await propagate_artifact(artifact)

    assert len(results) == 1
    assert results[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_propagate_campaign_artifacts_publishes_all() -> None:
    """All five pack-tier artifacts are published and propagated."""
    compiled = {
        "campaign_pack": {"campaign": "SCAM-027"},
        "phishing_playbook_patch": {"campaign": "SCAM-027"},
        "txn_rule": {"campaign": "SCAM-027"},
        "compliance_brief": "# Brief",
        "cs_advisory": "# Advisory",
    }
    with (
        patch("src.enterprise.propagation.emit_event", new_callable=AsyncMock),
        patch("src.enterprise.propagation.publish_artifact") as mock_publish,
        patch(
            "src.enterprise.propagation.propagate_artifact", new_callable=AsyncMock
        ) as mock_prop,
    ):
        mock_publish.return_value = {
            "id": "art-x",
            "name": "test",
            "version": 1,
            "artifact_type": "campaign_pack",
        }
        mock_prop.return_value = [{"agent_name": "phone_worker", "status": "acknowledged"}]
        results = await propagate_campaign_artifacts("camp-1", compiled, {"code": "SCAM-027"})

    assert mock_publish.call_count == 5
    assert len(results) == 5


@pytest.mark.asyncio
async def test_propagate_campaign_artifacts_survives_publish_failure() -> None:
    """A failed publish drops that artifact instead of failing the batch."""
    compiled = {"campaign_pack": {"campaign": "SCAM-027"}, "txn_rule": {"campaign": "SCAM-027"}}
    with (
        patch("src.enterprise.propagation.publish_artifact", return_value=None) as mock_publish,
        patch("src.enterprise.propagation.propagate_artifact", new_callable=AsyncMock) as mock_prop,
    ):
        results = await propagate_campaign_artifacts("camp-1", compiled, {"code": "SCAM-027"})

    assert mock_publish.call_count == 2
    assert results == {}
    mock_prop.assert_not_called()


@pytest.mark.asyncio
async def test_propagate_campaign_artifacts_names_pack_by_code() -> None:
    """The campaign pack is named by the campaign code the agents retrieve."""
    compiled = {"campaign_pack": {"campaign": "SCAM-027"}}
    with (
        patch("src.enterprise.propagation.emit_event", new_callable=AsyncMock),
        patch("src.enterprise.propagation.publish_artifact") as mock_publish,
        patch("src.enterprise.propagation.propagate_artifact", new_callable=AsyncMock),
    ):
        mock_publish.return_value = {"id": "a", "name": "SCAM-027", "version": 1}
        await propagate_campaign_artifacts("camp-1", compiled, {"code": "SCAM-027"})

    assert mock_publish.call_args.kwargs["name"] == "SCAM-027"
    assert mock_publish.call_args.kwargs["tier"] == "pack"


@pytest.mark.asyncio
async def test_propagate_campaign_artifacts_emits_artifact_published() -> None:
    """Every published version announces itself with registry/artifact_published.

    The console does not poll: without this event a new artifact version is
    invisible until the operator reloads the page.
    """
    compiled = {"campaign_pack": {"campaign": "SCAM-027"}}
    with (
        patch("src.enterprise.propagation.emit_event", new_callable=AsyncMock) as mock_emit,
        patch("src.enterprise.propagation.publish_artifact") as mock_publish,
        patch("src.enterprise.propagation.propagate_artifact", new_callable=AsyncMock),
    ):
        mock_publish.return_value = {
            "id": "art-x",
            "name": "SCAM-027",
            "artifact_type": "campaign_pack",
            "tier": "pack",
            "version": 3,
        }
        await propagate_campaign_artifacts("camp-1", compiled, {"code": "SCAM-027"})

    published = _published_calls(mock_emit)
    assert len(published) == 1
    assert published[0].kwargs["layer"] == "registry"
    assert published[0].kwargs["payload"]["version"] == 3
    assert published[0].kwargs["payload"]["artifact_name"] == "SCAM-027"


@pytest.mark.asyncio
async def test_publish_and_propagate_core_emits_artifact_published() -> None:
    """A core-tier publish emits registry/artifact_published too."""
    with (
        patch("src.enterprise.propagation.emit_event", new_callable=AsyncMock) as mock_emit,
        patch("src.enterprise.propagation.publish_artifact") as mock_publish,
        patch("src.enterprise.propagation.propagate_artifact", new_callable=AsyncMock),
    ):
        mock_publish.return_value = {
            "id": "art-core",
            "name": "phone_agent_core",
            "artifact_type": "phone_agent_core",
            "tier": "core",
            "version": 7,
        }
        artifact, _ = await publish_and_propagate_core("# core", {"rule_id": "R-1"})

    assert artifact is not None
    published = _published_calls(mock_emit)
    assert len(published) == 1
    assert published[0].kwargs["payload"]["tier"] == "core"


@pytest.mark.asyncio
async def test_publish_and_propagate_core_failure_emits_nothing() -> None:
    """A failed core publish announces no version."""
    with (
        patch("src.enterprise.propagation.emit_event", new_callable=AsyncMock) as mock_emit,
        patch("src.enterprise.propagation.publish_artifact", return_value=None),
        patch("src.enterprise.propagation.propagate_artifact", new_callable=AsyncMock),
    ):
        artifact, results = await publish_and_propagate_core("# core", {"rule_id": "R-1"})

    assert artifact is None
    assert results == []
    mock_emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_propagate_phone_agent_core_reaches_phone_worker() -> None:
    """A core-skill publish reaches the phone worker."""
    artifact = {
        "id": "art-core",
        "name": "phone_agent_core",
        "artifact_type": "phone_agent_core",
        "version": 7,
    }
    with (
        patch("src.enterprise.propagation.emit_event", new_callable=AsyncMock),
        patch("src.enterprise.propagation.record_consumption"),
    ):
        results = await propagate_artifact(artifact)
    assert len(results) == 1
    assert results[0]["agent_name"] == "phone_worker"
