"""Unit tests for the artifact registry (L4).

Implements the cases specified in doc/transafe_v2/03_artifact_registry.md §9.4.
Every Supabase call is mocked; no network and no API keys.
"""

from unittest.mock import MagicMock, patch

from src.enterprise.registry import (
    _compute_diff,
    get_artifact,
    get_artifact_diff,
    list_artifacts,
    publish_artifact,
    record_consumption,
    rollback_artifact,
    update_effectiveness,
)


@patch("src.enterprise.registry.get_supabase_client")
def test_publish_artifact_increments_version(mock_client: MagicMock) -> None:
    """A publish takes the highest existing version and adds one."""
    mock_table = MagicMock()
    chain = mock_table.select.return_value.eq.return_value.order.return_value
    chain.limit.return_value.execute.return_value.data = [{"version": 6}]
    mock_table.insert.return_value.execute.return_value.data = [
        {"id": "art-1", "version": 7}
    ]
    mock_client.return_value.table.return_value = mock_table

    result = publish_artifact(
        name="phone_agent_core",
        tier="core",
        artifact_type="phone_agent_core",
        target_agent="phone_worker",
        content="# Core skill v7",
    )
    assert result is not None
    assert result["version"] == 7


@patch("src.enterprise.registry.get_supabase_client")
def test_publish_artifact_first_version(mock_client: MagicMock) -> None:
    """The first version of an artifact is version 1."""
    mock_table = MagicMock()
    chain = mock_table.select.return_value.eq.return_value.order.return_value
    chain.limit.return_value.execute.return_value.data = []
    mock_table.insert.return_value.execute.return_value.data = [
        {"id": "art-1", "version": 1}
    ]
    mock_client.return_value.table.return_value = mock_table

    result = publish_artifact(
        "SCAM-027", "pack", "campaign_pack", "phone_worker", "{}"
    )
    assert result is not None
    assert result["version"] == 1


@patch("src.enterprise.registry.get_supabase_client")
def test_publish_artifact_survives_insert_failure(mock_client: MagicMock) -> None:
    """A missing artifacts table yields None, never an exception."""
    mock_table = MagicMock()
    chain = mock_table.select.return_value.eq.return_value.order.return_value
    chain.limit.return_value.execute.side_effect = RuntimeError(
        "relation does not exist"
    )
    mock_table.insert.return_value.execute.side_effect = RuntimeError(
        "relation does not exist"
    )
    mock_client.return_value.table.return_value = mock_table

    assert (
        publish_artifact(
            "SCAM-027", "pack", "campaign_pack", "phone_worker", "{}"
        )
        is None
    )


@patch("src.enterprise.registry.get_supabase_client")
def test_get_artifact_returns_latest(mock_client: MagicMock) -> None:
    """Without a version the latest published row is returned."""
    mock_table = MagicMock()
    chain = mock_table.select.return_value.eq.return_value.eq.return_value
    chain.order.return_value.limit.return_value.execute.return_value.data = [
        {"id": "art-1", "version": 7}
    ]
    mock_client.return_value.table.return_value = mock_table

    result = get_artifact("phone_agent_core")
    assert result is not None
    assert result["version"] == 7


@patch("src.enterprise.registry.get_supabase_client")
def test_get_artifact_returns_specific_version(mock_client: MagicMock) -> None:
    """An explicit version pins the query to that row."""
    mock_table = MagicMock()
    chain = mock_table.select.return_value.eq.return_value.eq.return_value
    chain.eq.return_value.execute.return_value.data = [
        {"id": "art-1", "version": 5}
    ]
    mock_client.return_value.table.return_value = mock_table

    result = get_artifact("phone_agent_core", version=5)
    assert result is not None
    assert result["version"] == 5


@patch("src.enterprise.registry.get_supabase_client")
def test_get_artifact_missing_table_returns_none(mock_client: MagicMock) -> None:
    """Reads are failure-tolerant while the migration is unapplied."""
    mock_client.return_value.table.side_effect = RuntimeError(
        "relation does not exist"
    )
    assert get_artifact("phone_agent_core") is None


@patch("src.enterprise.registry.get_supabase_client")
def test_get_artifact_diff_returns_diff(mock_client: MagicMock) -> None:
    """A version renders together with its diff against the predecessor."""
    mock_table = MagicMock()
    prev_chain = mock_table.select.return_value.eq.return_value.eq.return_value
    prev_chain.execute.return_value.data = [{"content": "old line\n"}]
    cur_chain = (
        mock_table.select.return_value.eq.return_value.eq.return_value
    )
    cur_chain.order.return_value.limit.return_value.execute.return_value.data = [
        {"id": "art-1", "version": 7, "content": "new line\n"}
    ]
    mock_client.return_value.table.return_value = mock_table

    result = get_artifact_diff("phone_agent_core", 7)
    assert result is not None
    assert result["current"]["version"] == 7
    assert isinstance(result["diff"], list)


@patch("src.enterprise.registry.get_supabase_client")
def test_list_artifacts_deduplicates_by_name(mock_client: MagicMock) -> None:
    """Only the highest version of each artifact name is listed."""
    mock_table = MagicMock()
    chain = mock_table.select.return_value.eq.return_value.order.return_value
    # Duplicate name "SCAM-027" at two versions — only v2 should survive.
    chain.execute.return_value.data = [
        {"id": "art-1", "name": "SCAM-027", "version": 2, "tier": "pack"},
        {"id": "art-2", "name": "SCAM-027", "version": 1, "tier": "pack"},
        {"id": "art-3", "name": "SCAM-019", "version": 1, "tier": "pack"},
    ]
    mock_client.return_value.table.return_value = mock_table

    result = list_artifacts()
    assert len(result) == 2
    scam027 = [a for a in result if a["name"] == "SCAM-027"][0]
    assert scam027["version"] == 2


@patch("src.enterprise.registry.get_supabase_client")
def test_list_artifacts_filters_by_tier(mock_client: MagicMock) -> None:
    """The tier filter adds one equality clause."""
    mock_table = MagicMock()
    chain = (
        mock_table.select.return_value.eq.return_value.eq.return_value
    )
    chain.order.return_value.execute.return_value.data = [
        {
            "id": "art-1",
            "name": "phone_agent_core",
            "version": 7,
            "tier": "core",
        },
    ]
    mock_client.return_value.table.return_value = mock_table

    result = list_artifacts(tier="core")
    assert len(result) == 1
    assert result[0]["tier"] == "core"


@patch("src.enterprise.registry.get_supabase_client")
def test_list_artifacts_missing_table_returns_empty(
    mock_client: MagicMock,
) -> None:
    """An absent table renders as an empty list, never a 500."""
    mock_client.return_value.table.side_effect = RuntimeError(
        "relation does not exist"
    )
    assert list_artifacts() == []


@patch("src.enterprise.registry.get_supabase_client")
def test_rollback_artifact_publishes_old_version(
    mock_client: MagicMock,
) -> None:
    """Rollback is append-only: v5's body is republished as v8."""
    mock_table = MagicMock()
    # Latest version lookup
    latest_chain = (
        mock_table.select.return_value.eq.return_value.eq.return_value
    )
    latest_chain.order.return_value.limit.return_value.execute.return_value.data = [
        {"id": "art-1", "version": 7, "content": "current"}
    ]
    # Target version fetch
    target_chain = (
        mock_table.select.return_value.eq.return_value.eq.return_value
    )
    target_chain.eq.return_value.execute.return_value.data = [
        {
            "id": "art-2",
            "version": 5,
            "content": "old content",
            "tier": "core",
            "artifact_type": "phone_agent_core",
            "target_agent": "phone_worker",
        }
    ]
    # Max version for increment
    max_chain = mock_table.select.return_value.eq.return_value.order.return_value
    max_chain.limit.return_value.execute.return_value.data = [{"version": 7}]
    mock_table.insert.return_value.execute.return_value.data = [
        {"id": "art-3", "version": 8}
    ]
    mock_client.return_value.table.return_value = mock_table

    result = rollback_artifact("phone_agent_core", to_version=5)
    assert result is not None
    assert result["version"] == 8

    # Append-only: nothing is updated or deleted during a rollback.
    mock_table.update.assert_not_called()
    mock_table.delete.assert_not_called()
    inserted = mock_table.insert.call_args[0][0]
    assert inserted["content"] == "old content"


@patch("src.enterprise.registry.get_supabase_client")
def test_rollback_unknown_version_returns_none(
    mock_client: MagicMock,
) -> None:
    """Rolling back to a version that does not exist publishes nothing."""
    mock_table = MagicMock()
    chain = mock_table.select.return_value.eq.return_value.eq.return_value
    chain.eq.return_value.execute.return_value.data = []
    mock_client.return_value.table.return_value = mock_table

    assert rollback_artifact("phone_agent_core", to_version=99) is None
    mock_table.insert.assert_not_called()


@patch("src.enterprise.registry.get_supabase_client")
def test_record_consumption_upserts(mock_client: MagicMock) -> None:
    """A consumption receipt is an upsert on (artifact_id, agent_name)."""
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table
    assert record_consumption("art-1", "phone_worker") is True
    mock_table.upsert.assert_called_once()


@patch("src.enterprise.registry.get_supabase_client")
def test_update_effectiveness_writes_metric(
    mock_client: MagicMock,
) -> None:
    """Effectiveness is written back onto the artifact row."""
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table

    assert update_effectiveness("art-1", {"detected": 5, "total": 6}) is True
    mock_table.update.assert_called_once()


def test_publish_accepts_injected_client() -> None:
    """The Supabase client is injectable, like PostgresGraphStore's."""
    mock_table = MagicMock()
    chain = mock_table.select.return_value.eq.return_value.order.return_value
    chain.limit.return_value.execute.return_value.data = []
    mock_table.insert.return_value.execute.return_value.data = [
        {"id": "art-9", "version": 1}
    ]
    injected = MagicMock()
    injected.table.return_value = mock_table

    result = publish_artifact(
        "SCAM-030",
        "pack",
        "campaign_pack",
        "phone_worker",
        "{}",
        client=injected,
    )
    assert result is not None
    assert result["version"] == 1
    injected.table.assert_called_with("artifacts")


def test_compute_diff_adds_and_removes() -> None:
    """A changed line shows as one removal and one addition."""
    diff = _compute_diff("line1\nline2\n", "line1\nline3\n")
    types = [d["type"] for d in diff]
    assert "added" in types
    assert "removed" in types


def test_compute_diff_no_changes() -> None:
    """Identical bodies produce no add/remove entries."""
    diff = _compute_diff("same\n", "same\n")
    assert all(d["type"] == "context" for d in diff)
