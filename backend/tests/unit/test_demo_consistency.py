"""Demo-consistency guards found by running the demo guide end to end.

Two defects that only appear when the recorded REPLAY and a LIVE run are compared
side by side — which is exactly what the pitch does, and exactly what unit tests
over each layer in isolation never exercise:

1. ``ns_events.run_id`` is a UUID column, but the replay runner stamped its
   events with the literal string ``"demo-replay"``. Every replay INSERT failed
   with 22P02; ``_persist`` swallows that, so the frames still broadcast live and
   *nothing is stored* — a reload mid-replay lost the entire run.
2. Campaign codes were allocated by counting rows, so the discovered wave became
   ``SCAM-003`` live while the docs, replay, console fixtures and artefact
   citations all call it ``SCAM-027``.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.api.enterprise.router import LIVE_RUN_ID, LIVE_RUN_LABEL
from src.api.enterprise_demo import REPLAY_RUN_ID, REPLAY_RUN_LABEL
from src.enterprise.discovery import CAMPAIGN_CODE_FLOOR, _next_campaign_code


def test_replay_run_id_is_a_uuid() -> None:
    """The replay run id must be storable in a UUID column."""
    parsed = uuid.UUID(REPLAY_RUN_ID)  # raises if it is a label
    assert str(parsed) == REPLAY_RUN_ID


def test_live_run_id_is_a_uuid() -> None:
    """The live run id must be storable too.

    This is the same defect the replay test above guards, missed because the
    constant lives in a different module: emitting the label "demo-live" failed
    the ``ns_events`` INSERT with 22P02, and the swallowed persist failure meant
    every live-mode event broadcast normally while never being stored.
    """
    parsed = uuid.UUID(LIVE_RUN_ID)  # raises if it is a label
    assert str(parsed) == LIVE_RUN_ID
    assert LIVE_RUN_ID != LIVE_RUN_LABEL


def test_live_run_id_is_stable_and_labelled() -> None:
    """Derived from the label, so it is reproducible and still traceable."""
    assert str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"https://transafe.local/v2/seed/{LIVE_RUN_LABEL}")
    ) == LIVE_RUN_ID


def test_live_and_replay_run_ids_differ() -> None:
    """A live frame and a scripted frame must stay distinguishable."""
    assert LIVE_RUN_ID != REPLAY_RUN_ID


def test_replay_run_id_is_stable_and_labelled() -> None:
    """A stable id keeps the run groupable; the label keeps it readable."""
    assert str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"https://transafe.local/v2/seed/{REPLAY_RUN_LABEL}")
    ) == REPLAY_RUN_ID
    assert REPLAY_RUN_LABEL == "demo-replay"


def test_campaign_code_continues_from_history() -> None:
    """The demo's next campaign is SCAM-027, not the row count."""
    existing: list[dict[str, Any]] = [{"code": "SCAM-019"}, {"code": "SCAM-024"}]
    assert _next_campaign_code(existing) == "SCAM-027"


def test_campaign_code_from_empty_registry_is_still_27() -> None:
    """A fresh database must not name the wave SCAM-001."""
    assert _next_campaign_code([]) == f"SCAM-{CAMPAIGN_CODE_FLOOR + 1:03d}"


def test_campaign_code_never_reuses_an_archived_number() -> None:
    """Counting rows would collide with a still-present ARCHIVED/REJECTED code."""
    existing = [{"code": "SCAM-003"}, {"code": "SCAM-027"}, {"code": "SCAM-019"}]
    assert _next_campaign_code(existing) == "SCAM-028"


def test_campaign_code_tolerates_missing_and_odd_values() -> None:
    """A campaign row with no code, or a foreign code, must not crash allocation."""
    existing: list[dict[str, Any]] = [{"code": None}, {}, {"code": "PATTERN-A"}]
    assert _next_campaign_code(existing) == "SCAM-027"

    existing.append({"code": "scam-009"})
    assert _next_campaign_code(existing) == "SCAM-027"
