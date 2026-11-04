"""Unit tests for src.enterprise.graph_store."""

from unittest.mock import MagicMock, patch

from src.enterprise.graph_store import Entity, PostgresGraphStore


@patch("src.enterprise.graph_store.get_supabase_client")
def test_upsert_entity_returns_id(mock_client):
    mock_table = MagicMock()
    mock_table.upsert.return_value.execute.return_value.data = [{"id": "entity-1"}]
    mock_client.return_value.table.return_value = mock_table

    store = PostgresGraphStore()
    assert store.upsert_entity("PHONE", "+60112345678") == "entity-1"


@patch("src.enterprise.graph_store.get_supabase_client")
def test_upsert_entity_no_data_returns_empty(mock_client):
    mock_table = MagicMock()
    mock_table.upsert.return_value.execute.return_value.data = []
    mock_client.return_value.table.return_value = mock_table

    assert PostgresGraphStore().upsert_entity("PHONE", "+60112345678") == ""


@patch("src.enterprise.graph_store.get_supabase_client")
def test_upsert_link_orders_case_ids(mock_client):
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table

    store = PostgresGraphStore()
    store.upsert_link("case-z", "case-a", "fused", 0.85, ["case-z", "case-a"])

    payload = mock_table.upsert.call_args[0][0]
    assert payload["case_a"] == "case-a"
    assert payload["case_b"] == "case-z"
    assert payload["score"] == 0.85
    assert payload["signals"]["link_type"] == "fused"


@patch("src.enterprise.graph_store.get_supabase_client")
def test_upsert_link_merges_extra_signals(mock_client):
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table

    PostgresGraphStore().upsert_link(
        "a", "b", "fused", 0.9, ["a", "b"], signals={"shared_identifier": {"matched": True}}
    )
    payload = mock_table.upsert.call_args[0][0]
    assert payload["signals"]["shared_identifier"] == {"matched": True}


@patch("src.enterprise.graph_store.get_supabase_client")
def test_components_returns_sets(mock_client):
    mock_table = MagicMock()
    mock_table.select.return_value.gte.return_value.execute.return_value.data = [
        {"case_a": "c1", "case_b": "c2", "score": 0.85},
        {"case_a": "c2", "case_b": "c3", "score": 0.75},
        {"case_a": "c4", "case_b": "c5", "score": 0.90},
    ]
    mock_client.return_value.table.return_value = mock_table

    components = PostgresGraphStore().components(min_weight=0.6)
    assert len(components) == 2
    assert {"c1", "c2", "c3"} in components
    assert {"c4", "c5"} in components


@patch("src.enterprise.graph_store.get_supabase_client")
def test_components_empty_when_no_links(mock_client):
    mock_table = MagicMock()
    mock_table.select.return_value.gte.return_value.execute.return_value.data = []
    mock_client.return_value.table.return_value = mock_table
    assert PostgresGraphStore().components(min_weight=0.6) == []


@patch("src.enterprise.graph_store.get_supabase_client")
def test_case_links_returns_links(mock_client):
    mock_table = MagicMock()
    mock_table.select.return_value.or_.return_value.gte.return_value.execute.return_value.data = [
        {"case_a": "c1", "case_b": "c2", "score": 0.85}
    ]
    mock_client.return_value.table.return_value = mock_table

    links = PostgresGraphStore().case_links("c1", min_score=0.6)
    assert len(links) == 1
    assert links[0]["score"] == 0.85


@patch("src.enterprise.graph_store.get_supabase_client")
def test_neighbours_uses_rpc(mock_client):
    mock_client.return_value.rpc.return_value.execute.return_value.data = [
        {
            "id": "e2",
            "entity_type": "ACCOUNT",
            "value_norm": "123456789",
            "value_raw": "1234-56789",
            "case_count": 3,
        }
    ]
    neighbours = PostgresGraphStore().neighbours("e1", depth=1)
    assert len(neighbours) == 1
    assert isinstance(neighbours[0], Entity)
    assert neighbours[0].entity_type == "ACCOUNT"
    mock_client.return_value.rpc.assert_called_once_with(
        "graph_neighbours", {"entity_id": "e1", "depth": 1}
    )


@patch("src.enterprise.graph_store.get_supabase_client")
def test_get_entities(mock_client):
    mock_table = MagicMock()
    mock_table.select.return_value.limit.return_value.execute.return_value.data = [
        {"id": "e1", "entity_type": "PHONE", "value_norm": "+60112345678", "case_count": 2}
    ]
    mock_client.return_value.table.return_value = mock_table

    entities = PostgresGraphStore().get_entities()
    assert entities[0].to_dict()["entity_type"] == "PHONE"


def test_entity_equality_and_hash():
    a = Entity(id="1", entity_type="PHONE", value_norm="x")
    b = Entity(id="1", entity_type="PHONE", value_norm="y")
    assert a == b
    assert len({a, b}) == 1


def test_store_accepts_injected_client():
    client = MagicMock()
    store = PostgresGraphStore(client=client)
    store.get_all_links()
    assert client.table.called
