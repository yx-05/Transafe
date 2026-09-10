"""Unit tests for the Liaison Agent (04_mcp_gateway.md §5 Testing).

The LLM is always mocked; no API key is required. The security-critical tests
are the ones asserting that redaction happens *before* synthesis sees anything
and that citations name records that were actually retrieved.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.enterprise.liaison_agent import (
    MAX_ITERATIONS,
    _plan_retrieval,
    _synthesise,
    ask_transafe,
)

LLM = "src.enterprise.liaison_agent.invoke_deepseek_with_key_rotation"


def _llm(payload: dict) -> MagicMock:
    """Build a mock LLM response carrying ``payload`` as JSON."""
    response = MagicMock()
    response.content = json.dumps(payload)
    return response


# ── Planning ─────────────────────────────────────────────────────────────────
def test_plan_retrieval_returns_plan():
    with patch(LLM) as mock_llm:
        mock_llm.return_value = _llm(
            {
                "intent": "find campaigns",
                "retrieval_plan": [{"tool": "list_active_campaigns", "args": {}}],
            }
        )
        plan = _plan_retrieval("What campaigns are active?", "fraud_ops")

    assert plan["retrieval_plan"][0]["tool"] == "list_active_campaigns"


def test_plan_retrieval_handles_llm_failure():
    with patch(LLM, side_effect=Exception("API down")):
        assert _plan_retrieval("test", "fraud_ops") is None


def test_plan_retrieval_rejects_malformed_plan():
    with patch(LLM) as mock_llm:
        mock_llm.return_value = _llm({"intent": "x"})
        assert _plan_retrieval("test", "fraud_ops") is None


# ── Synthesis ────────────────────────────────────────────────────────────────
def test_synthesise_returns_answer():
    """NOTE: 04_mcp_gateway.md's fixture for this case retrieves
    ``{"campaigns": []}`` and then requires the SCAM-027 citation to survive
    with ``confidence == "high"`` — i.e. the doc's happy path is itself an
    unsupported-citation case. The fixture is corrected here so SCAM-027 is
    actually present in the retrieved records; the assertions then hold *and*
    mean something.
    """
    gathered = [
        {"tool": "list_active_campaigns", "result": {"campaigns": [{"code": "SCAM-027"}]}}
    ]
    with patch(LLM) as mock_llm:
        mock_llm.return_value = _llm(
            {
                "answer": "Campaign SCAM-027 is active with 5 cases.",
                "citations": [{"type": "campaign", "id": "SCAM-027"}],
                "confidence": "high",
            }
        )
        result = _synthesise("test", "fraud_ops", gathered)

    assert "SCAM-027" in result["answer"]
    assert result["citations"] == [{"type": "campaign", "id": "SCAM-027"}]
    assert result["confidence"] == "high"
    assert "dropped_citations" not in result


def test_synthesise_empty_data():
    result = _synthesise("test", "fraud_ops", [])
    assert "could not" in result["answer"].lower()
    assert result["confidence"] == "low"


def test_synthesise_drops_citations_that_were_not_retrieved():
    """Citing a record you did not retrieve is a bug, not a flourish."""
    gathered = [{"tool": "list_active_campaigns", "result": {"campaigns": [{"code": "SCAM-001"}]}}]
    with patch(LLM) as mock_llm:
        mock_llm.return_value = _llm(
            {
                "answer": "Two campaigns are relevant.",
                "citations": [
                    {"type": "campaign", "id": "SCAM-001"},
                    {"type": "campaign", "id": "SCAM-999"},
                ],
                "confidence": "high",
            }
        )
        result = _synthesise("test", "fraud_ops", gathered)

    assert [c["id"] for c in result["citations"]] == ["SCAM-001"]
    assert result["dropped_citations"][0]["id"] == "SCAM-999"


# ── Confidence is lowered when citations do not survive verification ─────────
def test_partial_drop_caps_confidence_at_medium():
    """A model that cited a non-existent record has proved its own confidence
    signal unreliable *for this answer*. Shipping "high" beside a citation we
    had to delete is the confident-but-unsupported output this system exists
    to prevent, and no consumer cross-references ``dropped_citations``.
    """
    gathered = [{"tool": "list_active_campaigns", "result": {"campaigns": [{"code": "SCAM-001"}]}}]
    with patch(LLM) as mock_llm:
        mock_llm.return_value = _llm(
            {
                "answer": "Two campaigns.",
                "citations": [
                    {"type": "campaign", "id": "SCAM-001"},
                    {"type": "campaign", "id": "SCAM-999"},
                ],
                "confidence": "high",
            }
        )
        result = _synthesise("test", "fraud_ops", gathered)

    assert result["confidence"] == "medium"
    assert result["dropped_citations"]


def test_total_drop_forces_confidence_low():
    gathered = [{"tool": "list_active_campaigns", "result": {"campaigns": [{"code": "SCAM-001"}]}}]
    with patch(LLM) as mock_llm:
        mock_llm.return_value = _llm(
            {
                "answer": "Campaign SCAM-999 is active.",
                "citations": [{"type": "campaign", "id": "SCAM-999"}],
                "confidence": "high",
            }
        )
        result = _synthesise("test", "fraud_ops", gathered)

    assert result["citations"] == []
    assert result["confidence"] == "low"


def test_downgrade_never_raises_a_low_confidence():
    """The cap only lowers. A model that said "low" does not get promoted."""
    gathered = [{"tool": "list_active_campaigns", "result": {"campaigns": [{"code": "SCAM-001"}]}}]
    with patch(LLM) as mock_llm:
        mock_llm.return_value = _llm(
            {
                "answer": "Maybe.",
                "citations": [
                    {"type": "campaign", "id": "SCAM-001"},
                    {"type": "campaign", "id": "SCAM-999"},
                ],
                "confidence": "low",
            }
        )
        result = _synthesise("test", "fraud_ops", gathered)

    assert result["confidence"] == "low"


def test_downgrade_handles_a_nonsense_confidence_value():
    gathered = [{"tool": "list_active_campaigns", "result": {"campaigns": [{"code": "SCAM-001"}]}}]
    with patch(LLM) as mock_llm:
        mock_llm.return_value = _llm(
            {
                "answer": "Two campaigns.",
                "citations": [
                    {"type": "campaign", "id": "SCAM-001"},
                    {"type": "campaign", "id": "SCAM-999"},
                ],
                "confidence": "absolutely certain",
            }
        )
        result = _synthesise("test", "fraud_ops", gathered)

    assert result["confidence"] == "medium"


def test_synthesise_falls_back_deterministically_when_llm_unavailable():
    """No LLM, still a real answer, still honest citations."""
    gathered = [
        {
            "tool": "list_active_campaigns",
            "result": {"campaigns": [{"code": "SCAM-027"}, {"code": "SCAM-031"}]},
        }
    ]
    with patch(LLM, side_effect=Exception("API down")):
        result = _synthesise("What is active?", "fraud_ops", gathered)

    assert result["synthesis"] == "deterministic"
    assert {c["id"] for c in result["citations"]} == {"SCAM-027", "SCAM-031"}
    assert "SCAM-027" in result["answer"]


def test_deterministic_synthesis_admits_when_nothing_citable():
    with patch(LLM, side_effect=Exception("API down")):
        result = _synthesise("test", "public", [{"tool": "query_stats", "result": {}}])

    assert result["citations"] == []
    assert result["confidence"] == "low"
    assert "no records" in result["answer"].lower()


def test_deterministic_synthesis_ignores_redacted_ids():
    """A redacted id is not a citable record."""
    gathered = [{"tool": "get_campaign", "result": {"code": "[REDACTED]", "id": "[REDACTED]"}}]
    with patch(LLM, side_effect=Exception("API down")):
        result = _synthesise("test", "public", gathered)

    assert result["citations"] == []


# ── Bounded loop ─────────────────────────────────────────────────────────────
async def test_ask_transafe_bounded_iterations():
    calls: list[str] = []

    def _tool(**_kwargs):
        calls.append("call")
        return {"campaigns": [{"code": "SCAM-027"}]}

    plan = {
        "intent": "x",
        "retrieval_plan": [{"tool": "list_active_campaigns", "args": {}} for _ in range(10)],
    }
    with patch(LLM) as mock_llm:
        mock_llm.side_effect = [
            _llm(plan),
            _llm({"answer": "ok", "citations": [], "confidence": "medium"}),
        ]
        await ask_transafe("q", "fraud_ops", {"list_active_campaigns": _tool})

    assert len(calls) == MAX_ITERATIONS


async def test_ask_transafe_skips_unavailable_tools():
    plan = {"intent": "x", "retrieval_plan": [{"tool": "get_case_evidence", "args": {}}]}
    with patch(LLM) as mock_llm:
        mock_llm.side_effect = [_llm(plan)]
        result = await ask_transafe("q", "partner_bank", {})

    assert result["confidence"] == "low"
    assert any(step.get("status") == "not_found" for step in result["trace"])


async def test_ask_transafe_survives_tool_error():
    def _boom(**_kwargs):
        raise RuntimeError("supabase down")

    plan = {"intent": "x", "retrieval_plan": [{"tool": "list_active_campaigns", "args": {}}]}
    with patch(LLM) as mock_llm:
        mock_llm.side_effect = [_llm(plan)]
        result = await ask_transafe("q", "fraud_ops", {"list_active_campaigns": _boom})

    assert result["citations"] == []
    error_steps = [s for s in result["trace"] if s.get("status") == "error"]
    assert error_steps and error_steps[0]["error"] == "supabase down"


async def test_ask_transafe_supports_async_tools():
    async def _tool(**_kwargs):
        return {"campaigns": [{"code": "SCAM-027"}]}

    plan = {"intent": "x", "retrieval_plan": [{"tool": "list_active_campaigns", "args": {}}]}
    with patch(LLM) as mock_llm:
        mock_llm.side_effect = [
            _llm(plan),
            _llm(
                {
                    "answer": "SCAM-027 is active.",
                    "citations": [{"type": "campaign", "id": "SCAM-027"}],
                    "confidence": "high",
                }
            ),
        ]
        result = await ask_transafe("q", "fraud_ops", {"list_active_campaigns": _tool})

    assert result["citations"][0]["id"] == "SCAM-027"


# ── Fallback ─────────────────────────────────────────────────────────────────
async def test_fallback_when_planning_fails_still_cites_real_records():
    def _tool(**_kwargs):
        return {"campaigns": [{"code": "SCAM-027", "name": "Fake bank officer"}]}

    with patch(LLM, side_effect=Exception("API down")):
        result = await ask_transafe("q", "fraud_ops", {"list_active_campaigns": _tool})

    assert result["degraded"] is True
    assert "SCAM-027" in {c["id"] for c in result["citations"]}


async def test_fallback_says_it_cannot_answer_when_nothing_retrievable():
    with patch(LLM, side_effect=Exception("API down")):
        result = await ask_transafe("q", "public", {"list_active_campaigns": lambda **_: {}})

    assert result["citations"] == []
    assert "unable to answer" in result["answer"].lower()
    assert result["confidence"] == "low"


async def test_fallback_without_a_lister_cannot_answer():
    with patch(LLM, side_effect=Exception("API down")):
        result = await ask_transafe("q", "public", {})

    assert result["citations"] == []
    assert "unable to answer" in result["answer"].lower()


async def test_fallback_tool_error_cannot_answer():
    def _boom(**_kwargs):
        raise RuntimeError("down")

    with patch(LLM, side_effect=Exception("API down")):
        result = await ask_transafe("q", "fraud_ops", {"list_active_campaigns": _boom})

    assert result["citations"] == []
    assert "unable to answer" in result["answer"].lower()


# ── Security: redaction precedes synthesis ───────────────────────────────────
async def test_raw_value_never_reaches_synthesis_for_unentitled_role():
    """The structural guarantee of B6.

    The tool returns real transcript text and real PII. The caller is
    ``public``. The synthesis step must never be handed those values — not
    "must be told not to repeat them", must never receive them.
    """
    secret_transcript = "my OTP is 449122"
    secret_name = "Tan Ah Kow"

    def _tool(**_kwargs):
        return {
            "campaigns": [
                {
                    "code": "SCAM-027",
                    "victim_name": secret_name,
                    "transcripts": [{"speaker": "victim", "utterance": secret_transcript}],
                    "recipient_account": "1592-3456",
                }
            ]
        }

    seen: list[list[dict]] = []

    def _capture(question, role, gathered_data):
        seen.append(gathered_data)
        return {"answer": "ok", "citations": [], "confidence": "low"}

    plan = {"intent": "x", "retrieval_plan": [{"tool": "list_active_campaigns", "args": {}}]}
    with (
        patch(LLM) as mock_llm,
        patch("src.enterprise.liaison_agent._synthesise", side_effect=_capture),
    ):
        mock_llm.side_effect = [_llm(plan)]
        await ask_transafe("who was scammed?", "public", {"list_active_campaigns": _tool})

    assert seen, "synthesis was never reached"
    blob = json.dumps(seen[0])
    assert secret_transcript not in blob
    assert secret_name not in blob
    assert "1592-3456" not in blob
    assert "SCAM-027" not in blob


async def test_entitled_role_does_reach_synthesis_with_the_data():
    """The mirror of the above: redaction must not simply blank everything."""
    def _tool(**_kwargs):
        return {"campaigns": [{"code": "SCAM-027", "victim_name": "Tan Ah Kow"}]}

    seen: list[list[dict]] = []

    def _capture(question, role, gathered_data):
        seen.append(gathered_data)
        return {"answer": "ok", "citations": [], "confidence": "low"}

    plan = {"intent": "x", "retrieval_plan": [{"tool": "list_active_campaigns", "args": {}}]}
    with (
        patch(LLM) as mock_llm,
        patch("src.enterprise.liaison_agent._synthesise", side_effect=_capture),
    ):
        mock_llm.side_effect = [_llm(plan)]
        await ask_transafe("q", "fraud_ops", {"list_active_campaigns": _tool})

    blob = json.dumps(seen[0])
    assert "Tan Ah Kow" in blob
    assert "SCAM-027" in blob
