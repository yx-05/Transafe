"""Financial Worker Agent for TranSafe Multi-Agent pipeline."""

import inspect
import json
import logging
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from src.agents.llm import DEEPSEEK_BASE_URL, extract_json_object, invoke_groq_with_key_rotation
from src.agents.prompts import build_financial_prompt
from src.agents.state import GraphState, WorkerFinding
from src.db.supabase import fetch_user_transaction_history

logger = logging.getLogger(__name__)


def get_financial_llm(model_name: str = "deepseek-chat") -> ChatOpenAI:
    """Get ChatOpenAI LLM instance (DeepSeek) reading DEEPSEEK_API_KEY dynamically at runtime."""
    raw_key = os.getenv("DEEPSEEK_API_KEY") or "sk-placeholder_key_for_initialization"
    return ChatOpenAI(
        model=model_name,
        temperature=0.0,
        api_key=SecretStr(raw_key),
        base_url=DEEPSEEK_BASE_URL,
    )


class DynamicFinancialLLM:
    """Dynamic LLM proxy using DeepSeek with multi-key rotation and 429 rate limit fallback."""

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        return invoke_groq_with_key_rotation(messages)


llm = DynamicFinancialLLM()


FINANCIAL_SYSTEM_PROMPT = """You are an expert financial fraud audit agent specialized in transactional behavior anomaly detection.
Your task is to analyze the details of a pending bank transfer against the customer's historical 90-day transaction patterns and any active, user-associated case context (which may include live call transcripts or phishing screenshot OCR text).

Analyze the transaction for the following indicators:
1. Deviations in Amount: Is the amount significantly higher than their typical average (e.g. > 5x avg amount)?
2. First-Time Recipient: Has the sender ever transacted with this recipient account before?
3. Unorthodox Timing: Is the transfer initiated at an unusual hour (e.g. between 12:00 AM and 5:00 AM) that deviates from historical peaks?
4. Round-Number/Scam Cadence: Scammers often request round numbers (e.g. RM 5,000, RM 10,000) or push for a series of rapid transfers in under 10 minutes.
5. Case Coercion Match: Check the `associated_case_context`. Does the recipient's account number, name, or bank match account details mentioned in the scam call transcripts or extracted from the phishing message? If so, this is a severe signal that the transaction is scammer-coerced (override score to 95+).

Return your findings in strict JSON format:
{
  "score": integer (0-100),
  "confidence": float (0.0-1.0),
  "evidence": ["bullet point 1", "bullet point 2"]
}"""


def _check_case_context_match(
    recipient_account: str, case_context: dict[str, Any] | None
) -> bool:
    """Check if recipient account appears in active associated case context."""
    if not case_context or not recipient_account:
        return False

    bank_accounts: list[str] = case_context.get("bank_accounts", [])
    if recipient_account in bank_accounts:
        return True

    # Check text representations (transcripts, OCR text, raw content)
    context_str = json.dumps(case_context)
    return recipient_account in context_str


def _rule_based_financial_analysis(
    pending_tx: dict[str, Any],
    history: dict[str, Any],
    case_context: dict[str, Any] | None,
) -> WorkerFinding:
    """Rule-based transactional anomaly detection baseline."""
    amount = float(pending_tx.get("amount", 0.0))
    recipient = str(pending_tx.get("recipient_account", ""))

    avg_amount = float(history.get("avg_amount", 0.0))
    known_recipients = history.get("known_recipients", [])

    evidence: list[str] = []
    score = 10
    confidence = 0.90

    # 1. Amount deviation check
    if avg_amount > 0 and amount > (5 * avg_amount):
        multiple = amount / avg_amount
        score += 35
        evidence.append(
            f"Transfer amount RM {amount:,.2f} is {multiple:.1f}x higher than 90-day average (RM {avg_amount:,.2f})"
        )

    # 2. First time recipient
    if recipient and recipient not in known_recipients:
        score += 25
        evidence.append("Recipient account has never been transacted with in the past 90 days")

    # 3. Round number scam pattern check
    if amount >= 1000 and (amount % 500 == 0 or amount % 1000 == 0):
        score += 15
        evidence.append(f"Round transfer amount RM {amount:,.2f} fits common scam instruction pattern")

    # 4. Associated Case Context Match Override (CRITICAL REQUIREMENT)
    if _check_case_context_match(recipient, case_context):
        score = max(score, 98)
        confidence = 0.95
        evidence.insert(
            0,
            f"CRITICAL: Recipient account {recipient} matches active call transcript or phishing case context",
        )

    score = min(score, 100)
    if not evidence:
        evidence.append("Transaction amount and recipient are consistent with 90-day historical patterns")

    return WorkerFinding(
        worker="financial",
        score=score,
        confidence=confidence,
        evidence=evidence,
    )


def financial_worker_node(state: GraphState) -> dict[str, Any]:
    """Pure state transformation node for Financial Worker.

    Analyzes pending transaction details against 90-day history baseline and
    cross-references associated_case_context for account matches.
    """
    payload = state.get("trigger_payload") or {}
    tx_data = payload.get("transaction") if isinstance(payload.get("transaction"), dict) else payload

    # Build clean pending_tx dict with fallback to top-level payload keys
    pending_tx: dict[str, Any] = {
        "amount": tx_data.get("amount") or payload.get("amount", 0.0),
        "sender_account": str(tx_data.get("sender_account") or payload.get("sender_account", "")),
        "recipient_account": str(tx_data.get("recipient_account") or payload.get("recipient_account", "")),
        "currency": str(tx_data.get("currency") or payload.get("currency", "MYR")),
        "description": str(tx_data.get("description") or payload.get("description", "")),
        "initiated_at": str(tx_data.get("initiated_at") or payload.get("initiated_at", "")),
    }

    sender_account = pending_tx["sender_account"]
    recipient_account = pending_tx["recipient_account"]
    case_context = state.get("associated_case_context")

    # Fetch history baseline
    history: dict[str, Any] = {"avg_amount": 200.0, "known_recipients": []}
    current_tx_id = tx_data.get("transaction_id") or payload.get("transaction_id")
    if sender_account:
        try:
            raw_hist = fetch_user_transaction_history(
                sender_account,
                current_tx_id=current_tx_id,
                current_recipient_account=recipient_account,
            )
            if inspect.isawaitable(raw_hist):
                history = {"avg_amount": 200.0, "known_recipients": []}
            elif isinstance(raw_hist, dict):
                history = raw_hist
        except Exception as err:  # noqa: BLE001
            logger.warning(f"Failed to fetch user transaction history: {err}")

    # Baseline rule-based assessment
    finding = _rule_based_financial_analysis(pending_tx, history, case_context)

    # Invoke LLM dynamically with current DEEPSEEK_API_KEY
    try:
        prompt_text = build_financial_prompt(pending_tx, history, case_context)
        messages = [
            SystemMessage(content=FINANCIAL_SYSTEM_PROMPT),
            HumanMessage(content=prompt_text),
        ]
        llm_response = llm.invoke(messages)
        parsed = extract_json_object(llm_response.content if hasattr(llm_response, "content") else llm_response)
        if isinstance(parsed, dict):
            score = int(parsed.get("score", finding.score))
            confidence = float(parsed.get("confidence", finding.confidence))
            evidence = list(parsed.get("evidence", finding.evidence))
            if not evidence:
                if score == 0:
                    evidence = ["Transaction amount and recipient account align with normal banking patterns."]
                else:
                    evidence = [f"Financial transaction risk evaluated with score {score}/100."]
            finding = WorkerFinding(
                worker="financial",
                score=score,
                confidence=confidence,
                evidence=evidence,
            )
    except Exception as err:  # noqa: BLE001
        logger.debug(f"Financial LLM invocation skipped or failed, using rule base: {err}")

    # Hard enforcement: A recipient account matching the linked case's context
    # (scam call transcript / phishing material) is a severe coercion signal.
    # Force score to 98 and surface the CRITICAL evidence even when the LLM
    # already returned a high score, so downstream risk scoring can rely on it.
    if _check_case_context_match(recipient_account, case_context):
        finding.score = max(finding.score, 98)
        finding.confidence = max(finding.confidence, 0.95)
        match_ev = (
            f"Recipient account {recipient_account} matches active call "
            "transcript or phishing case context"
        )
        if not any(match_ev in e for e in finding.evidence):
            finding.evidence.insert(0, match_ev)

    return {"financial_finding": finding.model_dump()}
