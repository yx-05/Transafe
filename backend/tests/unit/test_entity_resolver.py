"""Unit tests for src.enterprise.entity_resolver."""

from unittest.mock import MagicMock, patch

import pytest

from src.enterprise.entity_resolver import (
    entities_from_identifiers,
    extract_domain_entity,
    fetch_case_entities,
    normalise_entity,
    refresh_entity_stats,
    resolve_entities,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+60 11-2345 6789", "+601123456789"),
        ("011-23456789", "+601123456789"),
        ("60112345678", "+60112345678"),
    ],
)
def test_normalise_phone(raw, expected):
    assert normalise_entity("PHONE", raw) == expected


def test_normalise_account():
    assert normalise_entity("ACCOUNT", "1234-5678-9012") == "123456789012"
    assert normalise_entity("ACCOUNT", "1234 5678 9012") == "123456789012"


def test_normalise_url():
    assert normalise_entity("URL", "https://www.bnm-verify.online/path/") == (
        "bnm-verify.online/path"
    )
    assert normalise_entity("URL", "HTTP://BNM-Verify.Online") == "bnm-verify.online"


def test_normalise_domain_strips_subdomain():
    assert normalise_entity("DOMAIN", "https://www.sub.bnm-verify.online/page") == (
        "bnm-verify.online"
    )


def test_normalise_name_strips_honorifics():
    assert normalise_entity("NAME", "Dato Sri Najib") == "najib"
    assert normalise_entity("NAME", "  Mr.   John  Tan ") == "john tan"


def test_normalise_empty_value():
    assert normalise_entity("PHONE", "") == ""
    assert normalise_entity("PHONE", "   ") == ""


def test_normalise_unknown_type_raises():
    with pytest.raises(ValueError):
        normalise_entity("SPACESHIP", "value")


def test_normalise_other_type_lowercases():
    assert normalise_entity("OTHER", " Weird Thing ") == "weird thing"


def test_extract_domain_entity():
    assert extract_domain_entity("https://pay.bnm-verify.online/x") == "bnm-verify.online"
    assert extract_domain_entity("") is None


def test_entities_from_identifiers_adds_domain_for_each_url():
    identifiers = {
        "phones": [{"value": "012-3456789"}],
        "accounts": [{"value": "1234567890"}],
        "urls": [{"value": "https://pay.bnm-verify.online/x"}],
        "amounts": [{"value": "RM5000"}],
    }
    result = entities_from_identifiers(identifiers)
    types = [e["entity_type"] for e in result]
    assert types.count("DOMAIN") == 1
    assert "PHONE" in types
    assert "ACCOUNT" in types
    assert "URL" in types
    assert "amounts" not in types


@patch("src.enterprise.entity_resolver.get_supabase_client")
def test_resolve_entities_dedupes(mock_client):
    mock_table = MagicMock()
    mock_table.upsert.return_value.execute.return_value.data = [{"id": "entity-1"}]
    mock_client.return_value.table.return_value = mock_table

    result = resolve_entities(
        "case-1",
        [
            {"entity_type": "PHONE", "value": "+60 11-2345 6789"},
            {"entity_type": "PHONE", "value": "011-23456789"},
        ],
    )
    assert len(result) == 1
    assert result[0]["value_norm"] == "+601123456789"


@patch("src.enterprise.entity_resolver.get_supabase_client")
def test_resolve_entities_links_case(mock_client):
    mock_table = MagicMock()
    mock_table.upsert.return_value.execute.return_value.data = [{"id": "entity-1"}]
    mock_client.return_value.table.return_value = mock_table

    resolve_entities("case-1", [{"entity_type": "PHONE", "value": "0112345678"}])
    tables_used = [c.args[0] for c in mock_client.return_value.table.call_args_list]
    assert "entities" in tables_used
    assert "case_entity_links" in tables_used


@patch("src.enterprise.entity_resolver.get_supabase_client")
def test_resolve_entities_skips_unknown_type(mock_client):
    mock_table = MagicMock()
    mock_table.upsert.return_value.execute.return_value.data = [{"id": "entity-1"}]
    mock_client.return_value.table.return_value = mock_table

    result = resolve_entities("case-1", [{"entity_type": "SPACESHIP", "value": "x"}])
    assert result == []


@patch("src.enterprise.entity_resolver.get_supabase_client")
def test_resolve_entities_supabase_down_returns_empty(mock_client):
    mock_client.side_effect = RuntimeError("down")
    assert resolve_entities("case-1", [{"entity_type": "PHONE", "value": "0112345678"}]) == []


# ---------------------------------------------------------------------------
# entities.case_count / last_seen — the console's graph reads these columns
# ---------------------------------------------------------------------------
def _split_table_client(link_rows):
    """Supabase mock with a distinct table mock per table name.

    The other tests here share one mock across every table, which cannot
    distinguish a write to ``entities`` from a write to ``case_entity_links``.
    """
    entities_tbl = MagicMock()
    entities_tbl.upsert.return_value.execute.return_value.data = [{"id": "entity-1"}]
    links_tbl = MagicMock()
    links_tbl.select.return_value.eq.return_value.execute.return_value.data = link_rows
    tables = {"entities": entities_tbl, "case_entity_links": links_tbl}
    client = MagicMock()
    client.table.side_effect = lambda name: tables[name]
    return client, entities_tbl, links_tbl


@patch("src.enterprise.entity_resolver.get_supabase_client")
def test_resolve_entities_refreshes_case_count_and_last_seen(mock_client):
    """Linking a case must update the entity's case_count / last_seen.

    Nothing else in v2 writes these columns, so if resolution skips them every
    node in the console's entity graph reports case_count 0 forever.
    """
    client, entities_tbl, _ = _split_table_client(
        [{"case_id": "case-1"}, {"case_id": "case-2"}, {"case_id": "case-3"}]
    )
    mock_client.return_value = client

    resolve_entities("case-3", [{"entity_type": "PHONE", "value": "0112345678"}])

    entities_tbl.update.assert_called_once()
    patch_body = entities_tbl.update.call_args[0][0]
    assert patch_body["case_count"] == 3
    assert patch_body["last_seen"]
    entities_tbl.update.return_value.eq.assert_called_once_with("id", "entity-1")


@patch("src.enterprise.entity_resolver.get_supabase_client")
def test_resolve_entities_case_count_is_derived_not_incremented(mock_client):
    """Re-ingesting the same case must not inflate the counter.

    The link table is keyed on (case_id, entity_id), so recomputing from it is
    idempotent where a ``+1`` would not be.
    """
    client, entities_tbl, _ = _split_table_client([{"case_id": "case-1"}, {"case_id": "case-2"}])
    mock_client.return_value = client

    resolve_entities("case-2", [{"entity_type": "PHONE", "value": "0112345678"}])
    resolve_entities("case-2", [{"entity_type": "PHONE", "value": "0112345678"}])

    counts = [c.args[0]["case_count"] for c in entities_tbl.update.call_args_list]
    assert counts == [2, 2]


@patch("src.enterprise.entity_resolver.get_supabase_client")
def test_resolve_entities_survives_a_stats_refresh_failure(mock_client):
    """A stale counter must not discard an entity that was resolved and linked."""
    client, entities_tbl, _ = _split_table_client([{"case_id": "case-1"}])
    entities_tbl.update.side_effect = RuntimeError("column missing")
    mock_client.return_value = client

    result = resolve_entities("case-1", [{"entity_type": "PHONE", "value": "0112345678"}])
    assert len(result) == 1
    assert result[0]["value_norm"] == "+60112345678"


def test_refresh_entity_stats_records_a_supplied_last_seen():
    """The demo seed must be able to keep its own historical timestamps.

    Its corpus is dated months back, and the live default of "now" would stamp
    every seeded entity with the moment the seed ran — silently collapsing the
    demo's timeline to a single instant while the counts beside it stayed
    correct, which is the kind of wrong number nobody re-reads.
    """
    client, entities_tbl, _ = _split_table_client([{"case_id": "case-1"}])

    refresh_entity_stats(client, "entity-1", last_seen="2026-08-02T09:15:00Z")

    patch_body = entities_tbl.update.call_args[0][0]
    assert patch_body["last_seen"] == "2026-08-02T09:15:00Z"
    assert patch_body["case_count"] == 1


def test_refresh_entity_stats_defaults_last_seen_to_now():
    """Live ingest has no timestamp to pass: the case is arriving as this runs."""
    client, entities_tbl, _ = _split_table_client([{"case_id": "case-1"}])

    refresh_entity_stats(client, "entity-1")

    assert entities_tbl.update.call_args[0][0]["last_seen"]


def test_refresh_entity_stats_refuses_to_write_a_zero_count():
    """A zero here means the link read failed or raced, not that nothing links.

    Writing it would turn a transient read error into a permanently wrong
    number on the graph, with no later run guaranteed to correct it.
    """
    client, entities_tbl, _ = _split_table_client([])

    refresh_entity_stats(client, "entity-1")

    entities_tbl.update.assert_not_called()


@patch("src.enterprise.entity_resolver.get_supabase_client")
def test_fetch_case_entities(mock_client):
    mock_client.return_value.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [  # noqa: E501
        {
            "entity_id": "e1",
            "entities": {
                "entity_type": "PHONE",
                "value_norm": "+60112345678",
                "value_raw": "011-2345678",
            },
        }
    ]
    entities = fetch_case_entities("case-1")
    assert entities == [
        {
            "entity_id": "e1",
            "entity_type": "PHONE",
            "value_norm": "+60112345678",
            "value_raw": "011-2345678",
        }
    ]
