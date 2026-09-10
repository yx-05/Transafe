"""Unit tests for src.enterprise.entity_resolver."""

from unittest.mock import MagicMock, patch

import pytest

from src.enterprise.entity_resolver import (
    entities_from_identifiers,
    extract_domain_entity,
    fetch_case_entities,
    normalise_entity,
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
