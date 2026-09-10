"""Unit tests for the demo corpus seeder (src.api.enterprise_demo).

The seeded graph is the one a human is actually shown, so a number that is
merely *usually* right here is worse than one that is wrong in the live path:
nobody re-derives what the demo asserts.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.api.enterprise_demo import _seed_entities

#: Two entities, one of them shared across two cases — the shape that makes the
#: linkage graph light up, and the only shape where a miscounted entity is
#: visible.
ENTITY_ROWS: dict[tuple[str, str], dict[str, object]] = {
    ("PHONE", "+60123456789"): {
        "id": "ent-phone",
        "entity_type": "PHONE",
        "value_raw": "012-345 6789",
        "value_norm": "+60123456789",
        "first_seen": "2026-08-01T09:00:00Z",
        "last_seen": "2026-08-02T09:15:00Z",
        "case_count": 2,
    },
    ("ACCOUNT", "1592"): {
        "id": "ent-acct",
        "entity_type": "ACCOUNT",
        "value_raw": "1592",
        "value_norm": "1592",
        "first_seen": "2026-08-01T09:00:00Z",
        "last_seen": "2026-08-01T09:00:00Z",
        "case_count": 1,
    },
}

LINKS: list[tuple[str, tuple[str, str]]] = [
    ("case-1", ("PHONE", "+60123456789")),
    ("case-2", ("PHONE", "+60123456789")),
    ("case-1", ("ACCOUNT", "1592")),
]


def test_seed_reconciles_entity_counts_against_the_links_it_wrote() -> None:
    """``case_count`` must be derived from ``case_entity_links``, not predicted.

    The count built while walking the corpus is a Python-side prediction of the
    link upsert. It agrees with the database only for as long as that upsert
    wholly succeeds, and it duplicates a derivation the live resolver already
    owns — two sources of truth for one number a human reads off the graph.
    """
    client = MagicMock()
    warnings: list[str] = []

    with patch("src.api.enterprise_demo.refresh_entity_stats") as refresh:
        written, link_count = _seed_entities(client, ENTITY_ROWS, LINKS, warnings)

    assert (written, link_count) == (2, 3)
    assert warnings == []
    refreshed = {c.args[1]: c.kwargs["last_seen"] for c in refresh.call_args_list}
    assert refreshed == {
        "ent-phone": "2026-08-02T09:15:00Z",
        "ent-acct": "2026-08-01T09:00:00Z",
    }


def test_seed_passes_the_corpus_timestamp_not_wall_clock_now() -> None:
    """Reconciling must not rewrite the seeded timeline to "just now".

    ``refresh_entity_stats`` defaults ``last_seen`` to the current time, which
    is correct for live ingest and wrong here: the corpus is dated historically
    and the demo's span is part of what it demonstrates. Asserting the argument
    is passed at all is the point — omitting it fails silently, with correct
    counts beside collapsed dates.
    """
    client = MagicMock()

    with patch("src.api.enterprise_demo.refresh_entity_stats") as refresh:
        _seed_entities(client, ENTITY_ROWS, LINKS, [])

    # Without this the loop below iterates nothing and the test passes against
    # a seeder that never reconciles at all.
    assert refresh.call_count == len(ENTITY_ROWS)
    for call in refresh.call_args_list:
        assert call.kwargs.get("last_seen"), "last_seen must be passed explicitly"


def test_seed_does_not_reconcile_when_no_links_were_written() -> None:
    """With the link upsert failed there is nothing to derive a count from.

    ``refresh_entity_stats`` would read an empty link table. It declines to
    write a zero, but calling it at all would be asserting a reconciliation
    that cannot have happened — and the warning is the honest output here.
    """
    client = MagicMock()
    client.table.return_value.upsert.return_value.execute.side_effect = [
        MagicMock(),  # entities upsert succeeds
        RuntimeError("links table missing"),
    ]
    warnings: list[str] = []

    with patch("src.api.enterprise_demo.refresh_entity_stats") as refresh:
        written, link_count = _seed_entities(client, ENTITY_ROWS, LINKS, warnings)

    assert written == 2
    assert link_count == 0
    assert warnings and "case_entity_links" in warnings[0]
    refresh.assert_not_called()


def test_seed_writes_no_links_when_the_entities_upsert_fails() -> None:
    """A link row pointing at an entity that was never written is a dangling FK."""
    client = MagicMock()
    client.table.return_value.upsert.return_value.execute.side_effect = RuntimeError("down")
    warnings: list[str] = []

    with patch("src.api.enterprise_demo.refresh_entity_stats") as refresh:
        assert _seed_entities(client, ENTITY_ROWS, LINKS, warnings) == (0, 0)

    refresh.assert_not_called()
    assert warnings and "entities" in warnings[0]
