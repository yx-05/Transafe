"""Module 3: Dynamic Skills & Prompt Management.

Provides utilities to load external skill markdown definitions and format
LLM prompts for telemetry, financial, research, phishing, phone, and XAI workers.
"""

import json
from pathlib import Path
from typing import Any


def load_skill_file(skill_filename: str) -> str:
    """Load an external skill file from the backend/skills/ directory.

    Args:
        skill_filename: Name of the skill file (e.g. 'phone_dialogue_guide.md').

    Returns:
        The content of the skill file as a string.

    Raises:
        FileNotFoundError: If the skill file does not exist.
    """
    base_dir = Path(__file__).resolve().parent.parent.parent
    skills_dir = base_dir / "skills"
    file_path = skills_dir / skill_filename

    if not file_path.exists():
        raise FileNotFoundError(f"Skill file not found: {file_path}")

    return file_path.read_text(encoding="utf-8")


def get_phone_dialogue_guide() -> str:
    """Retrieve the phone dialogue guide skill content.

    Returns:
        The content of phone_dialogue_guide.md as a string.
    """
    return load_skill_file("phone_dialogue_guide.md")


def get_anchor_questions() -> list[dict[str, Any]]:
    """Parse anchor questions from anchor_questions.md skill file.

    Returns:
        A list of dictionaries representing the anchor question schedule.
    """
    content = load_skill_file("anchor_questions.md")
    questions: list[dict[str, Any]] = []

    # Parse markdown table
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if not parts:
            continue
        raw_id = parts[0].replace("*", "").strip()
        if raw_id.upper() == "ID":
            continue
        if len(parts) >= 4 and raw_id.startswith("AQ-"):
            intent = parts[1]
            question = parts[2].strip('"\'*')
            scam_signal = parts[3]
            questions.append({
                "id": raw_id,
                "intent": intent,
                "goal": intent,
                "question_example": question,
                "question_template": question,
                "scam_signal_if": scam_signal,
                "scam_indicator": scam_signal,
            })

    if not questions:
        # Fallback default schedule if parsing fails
        return [
            {
                "id": "AQ-1",
                "intent": "Verify organisation & agent ID",
                "goal": "Verify organisation & agent ID",
                "question_example": (
                    "May I know the full name of your department/organisation and your employee"
                    " ID registration number, please?"
                ),
                "question_template": (
                    "May I know the full name of your department/organisation and your employee"
                    " ID registration number, please?"
                ),
                "scam_signal_if": (
                    "Caller cannot provide ID, gives general/vague answers, or gets defensive."
                ),
                "scam_indicator": (
                    "Caller cannot provide ID, gives general/vague answers, or gets defensive."
                ),
            },
            {
                "id": "AQ-2",
                "intent": "Call-back verification check",
                "goal": "Call-back verification check",
                "question_example": (
                    "I'd feel much safer if I call your official office number directly to reach"
                    " you. What is your department extension number?"
                ),
                "question_template": (
                    "I'd feel much safer if I call your official office number directly to reach"
                    " you. What is your department extension number?"
                ),
                "scam_signal_if": (
                    "Caller refuses to let you hang up, claims line is secure, or threatens"
                    " arrest."
                ),
                "scam_indicator": (
                    "Caller refuses to let you hang up, claims line is secure, or threatens"
                    " arrest."
                ),
            },
            {
                "id": "AQ-3",
                "intent": "Financial transfer probe",
                "goal": "Financial transfer probe",
                "question_example": (
                    "Will this procedure involve transferring my funds to another account or"
                    " verifying my card passwords?"
                ),
                "question_template": (
                    "Will this procedure involve transferring my funds to another account or"
                    " verifying my card passwords?"
                ),
                "scam_signal_if": (
                    "Caller confirms money needs to be moved to a safe account or deflects."
                ),
                "scam_indicator": (
                    "Caller confirms money needs to be moved to a safe account or deflects."
                ),
            },
            {
                "id": "AQ-4",
                "intent": "Urgent action challenge",
                "goal": "Urgent action challenge",
                "question_example": (
                    "I need to consult my family or visit a local branch first before making this"
                    " decision. Is it okay if I do that tomorrow?"
                ),
                "question_template": (
                    "I need to consult my family or visit a local branch first before making this"
                    " decision. Is it okay if I do that tomorrow?"
                ),
                "scam_signal_if": (
                    "Caller pressures for immediate execution or forbids consulting family."
                ),
                "scam_indicator": (
                    "Caller pressures for immediate execution or forbids consulting family."
                ),
            },
        ]

    return questions


def build_telemetry_prompt(
    user_id: str,
    session_id: str,
    device_id: str,
    events: list[dict[str, Any]],
    metrics: dict[str, Any] | None = None,
    biometrics: dict[str, Any] | None = None,
    fingerprint: dict[str, Any] | None = None,
) -> str:
    """Build system and human prompt for Telemetry Worker using calculated summary metrics."""
    flight_times: list[float] = []
    copy_paste_count = 0
    tab_switch_count = 0
    screen_share_detected = False

    for e in (events if isinstance(events, list) else []):
        evt_type = str(e.get("event_type", "")).upper()
        evt_val = e.get("event_value")

        if evt_type in ("KEYSTROKE", "KEYPRESS", "FLIGHT_TIME"):
            try:
                if evt_val is not None:
                    import re
                    digits = re.findall(r"\d+(?:\.\d+)?", str(evt_val))
                    if digits:
                        flight_times.append(float(digits[0]))
            except (ValueError, TypeError):
                pass
        elif evt_type in ("COPY_PASTE", "PASTE"):
            copy_paste_count += 1
        elif evt_type == "TAB_SWITCH":
            tab_switch_count += 1
        elif evt_type in ("SCREEN_SHARE_DETECTED", "REMOTE_ACCESS") or evt_val in ("true", True):
            screen_share_detected = True

    if metrics:
        copy_paste_count = max(copy_paste_count, int(metrics.get("copy_paste_events") or metrics.get("copy_paste_count") or 0))
        tab_switch_count = max(tab_switch_count, int(metrics.get("tab_switches") or metrics.get("tab_switch_count") or 0))
    if biometrics:
        if biometrics.get("avg_flight_time_ms") and not flight_times:
            flight_times.append(float(biometrics.get("avg_flight_time_ms")))
        if biometrics.get("screen_share_detected"):
            screen_share_detected = True

    avg_flight_time = round(sum(flight_times) / len(flight_times), 1) if flight_times else "N/A (no keystrokes)"

    backspace_count = int((biometrics or {}).get("backspace_count") or 0)
    is_account_pasted = bool((biometrics or {}).get("is_account_number_pasted") or False)
    time_on_page = int((metrics or {}).get("time_on_page_seconds") or (metrics or {}).get("time_on_page") or 0)

    summary_metrics = {
        "avg_keystroke_flight_time_ms": avg_flight_time,
        "total_keystrokes_recorded": len(flight_times),
        "backspace_count": backspace_count,
        "copy_paste_events": copy_paste_count,
        "is_account_number_pasted": is_account_pasted,
        "tab_switches": tab_switch_count,
        "time_on_page_seconds": time_on_page,
        "screen_share_detected": screen_share_detected,
    }
    metrics_str = json.dumps(summary_metrics, indent=2)

    # Clean recent events list (top 5) for context verification
    clean_events = [
        {
            "event_type": str(e.get("event_type", "")),
            "event_value": str(e.get("event_value", "")),
        }
        for e in (events[:5] if isinstance(events, list) else [])
    ]
    events_json = json.dumps(clean_events, indent=2)
    biometrics_str = json.dumps(biometrics, indent=2) if biometrics is not None else "N/A"
    
    fp = fingerprint or {}
    net_fingerprint = dict(fp)
    net_fingerprint.setdefault("browser_fingerprint_hash", "a8f9c102b44e")
    net_fingerprint.setdefault("screen_resolution", "1440x900")
    net_fingerprint.setdefault("network_type", "wifi")
    net_fingerprint.setdefault("browser_timezone", "Asia/Kuala_Lumpur")
    fingerprint_str = json.dumps(net_fingerprint, indent=2)

    return f"""You are an expert fraud behavioral biometrics analyst at a retail bank.
Your job is to analyze the session behavioral biometrics and calculated telemetry metrics from a user's session and output a risk assessment.
Look for the following signals:
1. Hesitation or Dictation: Typing cadence that is extremely slow (avg flight time > 500ms) or contains high backspace counts, indicating the user is typing under coercion/dictation.
2. Automation/Bots: Flight times near 0ms or highly constant typing speed, indicating automated inputs.
3. Instruction Following: Copy-pasting account numbers or names, erratic mouse cursor movements, and frequent tab switches.
4. Direct Compromise: Orientations changing rapidly, screenshots taken, or active screen sharing flags.

You must respond in strict JSON format with keys "score" (0-100), "confidence" (0.0-1.0), and "evidence" (list of strings).

Analyze the following calculated session telemetry and behavioral biometric data:
User ID: {user_id}
Session ID: {session_id}
Device ID: {device_id}

Calculated Session Metrics:
{metrics_str}

Recent Events Sequence (Top 5):
{events_json}

Biometrics Context:
{biometrics_str}

Device Fingerprint Context:
{fingerprint_str}

Provide your risk assessment. If the data is clean (e.g. normal flight times, known device, normal flow), score it below 20. If anomalous, increase score and explain why in evidence."""


def build_financial_prompt(
    pending_tx: dict[str, Any],
    history: dict[str, Any],
    case_context: dict[str, Any] | None = None,
) -> str:
    """Build system and human prompt for Financial Worker.

    Args:
        pending_tx: Pending transaction details dictionary.
        history: 90-day historical baseline transaction data dictionary.
        case_context: Optional active case context (call transcripts, phishing OCR, etc.).

    Returns:
        Formatted prompt string.
    """
    tx_json = json.dumps(pending_tx, indent=2)
    
    # Omit verbose raw transactions array from history to reduce prompt tokens by 85%
    clean_history = {
        "total_count": history.get("total_count", 0),
        "total_amount_myr": round(float(history.get("total_amount_myr", 0.0)), 2),
        "avg_amount": round(float(history.get("avg_amount", 0.0)), 2),
        "max_amount": round(float(history.get("max_amount", 0.0)), 2),
        "known_recipients": history.get("known_recipients", []),
    }
    history_json = json.dumps(clean_history, indent=2)
    case_context_json = json.dumps(case_context, indent=2) if case_context is not None else "None"

    return f"""You are an expert financial fraud audit agent specialized in transactional behavior anomaly detection.
Your task is to analyze the details of a pending bank transfer against the customer's historical 90-day transaction patterns and any active, user-associated case context.

Analyze the transaction for the following indicators:
1. Deviations in Amount: Is the amount significantly higher than their typical average (e.g. > 5x avg amount)?
2. First-Time Recipient: Has the sender ever transacted with this recipient account before?
3. Unorthodox Timing: Is the transfer initiated at an unusual hour (e.g. between 12:00 AM and 5:00 AM)?
4. Round-Number/Scam Cadence: Scammers often request round numbers or push for a series of rapid transfers.
5. Case Coercion Match: Check associated_case_context. Does recipient account/name match account details mentioned in scam call transcripts or extracted from phishing message? If so, override score to 95+.

Return your findings in strict JSON format:
{{
  "score": integer (0-100),
  "confidence": float (0.0-1.0),
  "evidence": ["bullet point 1", "bullet point 2"]
}}

Pending Transaction:
{tx_json}

Historical 90-Day Baseline:
{history_json}

User-Associated Case Context (Call Transcripts & Phishing OCR):
{case_context_json}

Perform your assessment and return the JSON findings."""


def build_research_prompt(
    entities: list[Any],
    internal_hits: list[Any],
    tavily_hits: list[Any],
) -> str:
    """Build system and human prompt for Research Worker (QUERY mode).

    Args:
        entities: List of query entities (phone numbers, accounts, URLs).
        internal_hits: Vector store RAG search results from internal DB.
        tavily_hits: Web search results from Tavily API.

    Returns:
        Formatted prompt string.
    """
    entities_json = json.dumps(entities, indent=2)

    # Extract clean RAG summary snippets and deduplicate by content text
    seen_contents = set()
    clean_internal = []
    if isinstance(internal_hits, list):
        for hit in internal_hits:
            content_snippet = str(hit.get("content") or hit.get("case_id") or "scam_hit").strip()[:200]
            if content_snippet and content_snippet not in seen_contents:
                seen_contents.add(content_snippet)
                clean_internal.append(
                    {
                        "case_id": str(hit.get("case_id", "")),
                        "similarity": round(float(hit.get("similarity", 0.0)), 2),
                        "fraud_type": hit.get("fraud_type") or (hit.get("metadata") or {}).get("fraud_type", "scam"),
                        "content": str(hit.get("content") or content_snippet),
                    }
                )
            if len(clean_internal) >= 3:
                break
    internal_json = json.dumps(clean_internal, indent=2)

    # Extract clean Tavily web search snippets (limit 300 chars & top 3 hits for token efficiency)
    clean_tavily = [
        {
            "title": hit.get("title", "Scam Report"),
            "url": hit.get("url", ""),
            "snippet": str(hit.get("snippet") or hit.get("content") or hit.get("summary") or "")[:300],
        }
        for hit in (tavily_hits[:3] if isinstance(tavily_hits, list) else [])
    ]
    tavily_json = json.dumps(clean_tavily, indent=2)

    return f"""You are an expert financial fraud research intelligence agent.
Analyze the query entities (phone numbers, bank accounts, URLs) alongside the RAG search results from our internal fraud database and public web reports.
Your job is to determine:
1. If any of the query entities appear directly in historical scam logs (high similarity matches > 0.80).
2. If there are close semantic matches describing similar fraud patterns involving these entities.
3. If public web reports indicate these accounts or numbers are explicitly linked to online scams, police reports, or central bank warning lists.

CRITICAL SCORING & GROUNDING RULES:
1. PUBLIC WEB / REGULATORY MATCH: If Tavily Web Search Results explicitly name a company, scheme, or transfer description (e.g. 'JJPTR', 'Genneva', 'MBI', 'Money Game') as a known scam, Ponzi scheme, illegal investment, or listed on SC/BNM alert lists, you MUST assign a HIGH RISK SCORE (85-100) with confidence >= 0.90! Do NOT downgrade web search evidence to moderate risk!
2. GENERAL ADVISORIES (NO MATCH): If Tavily Web Search Results contain only general security awareness articles that DO NOT explicitly name the specific query entity or scheme, treat them as UNRELATED / NO MATCH (score = 0).
3. CLEAN RECIPIENT: When NO match is found in DB or web search, return score = 0 and confidence = 0.95 (representing high certainty that the recipient is clean).
4. SINGLE OBJECT ONLY: Return a SINGLE JSON object representing the OVERALL risk finding for the transaction. DO NOT output conversational intro text or JSON arrays!

Return your finding as a SINGLE JSON object:
{{
  "score": integer (0-100),
  "confidence": float (0.0-1.0),
  "evidence": ["bullet point 1", "bullet point 2"]
}}

Query Entities:
{entities_json}

Internal pgvector Matches:
{internal_json}

Tavily Web Search Results:
{tavily_json}

Analyze the match details and output your structured fraud intelligence risk finding."""


def build_phishing_analysis_prompt(
    source: str, content: str, web_results: str = ""
) -> str:
    """Build prompt for Phishing Worker content analysis.

    Args:
        source: Material source (e.g., 'TEXT', 'URL', 'IMAGE').
        content: Material content or OCR text to analyze.
        web_results: Optional external web research hits (regulatory alert
            lists / police reports) to incorporate into the verdict.

    Returns:
        Formatted prompt string.
    """
    web_section = ""
    if web_results:
        web_section = f"""

Web Research Results (external fraud alert lists / reports):
{web_results}

If any of the above results reference entities from the material, cite them as supporting evidence and adjust the score accordingly."""
    return f"""You are an expert cybersecurity phishing analyst.
Analyze the user-submitted content (SMS text, email body, URL strings, or transcribed text from screenshots) and determine the risk of it being a phishing or scam attempt.

Look for the following signals:
1. Bank/Government Impersonation: Pretending to be Maybank, CIMB, Bank Negara, PDRM, LHDN, POS Malaysia, etc.
2. Urgent/Threatening Language: Claiming account suspension, immediate blocks, packages held, or legal actions unless action is taken in hours.
3. Call-to-Action Lookalikes: Providing links that mimic official bank domains or asking user to call suspicious numbers.
4. Information Harvester: Requesting login credentials, card numbers, PINs, or OTPs.

Respond in strict JSON format:
{{
  "score": integer (0-100),
  "confidence": float (0.0-1.0),
  "evidence": ["bullet point 1", "bullet point 2"]
}}

Material Source: {source}
Material Content:
"{content}"
{web_section}

Provide your structured risk finding."""


def build_phishing_research_planner_prompt(
    content: str,
    entities_json: str,
    rag_json: str,
    base_score: int,
    base_confidence: float,
) -> str:
    """Build prompt for the Phishing Worker research planner step.

    The planner LLM decides whether an online web search of Malaysian fraud
    alert lists (BNM, Securities Commission, PDRM) would improve the deep
    analysis verdict, and if so which entity-specific queries to run.

    Args:
        content: Analyzed material content (transcript / SMS / URL text).
        entities_json: Extracted entities (phones, URLs, accounts) as JSON.
        rag_json: Internal fraud-database matches as JSON.
        base_score: Current rule/LLM risk score (0-100).
        base_confidence: Current confidence (0.0-1.0).

    Returns:
        Formatted prompt string.
    """
    return f"""You are the research planner for a phishing deep-analysis pipeline.
A phishing analyst has already analyzed the material below and produced an initial verdict.
Decide whether an ONLINE WEB SEARCH of Malaysian fraud alert lists would meaningfully improve that verdict, and if so, propose entity-specific search queries.

Material Content (transcript / text):
"{content[:1500]}"

Extracted Entities:
{entities_json}

Internal Fraud Database Matches:
{rag_json[:1500]}

Current Verdict:
- score: {base_score}/100
- confidence: {base_confidence:.2f}

Respond in strict JSON format:
{{
  "search": true or false,
  "reasoning": "one short sentence justifying the decision",
  "queries": ["entity-specific short query 1", "query 2", "query 3"],
  "confidence": float (0.0-1.0)
}}"""


def build_phone_highlighter_prompt(text: str) -> str:
    """Build prompt for Phone Worker live utterance highlighter (LISTEN mode).

    Args:
        text: Transcribed utterance text.

    Returns:
        Formatted prompt string.
    """
    return f"""You are an expert scam call analyst. Analyze the transcribed utterance from a live call and output a risk highlights JSON object.
Identify phrases indicating:
1. false_accusation: Caller accusing victim of crime (money laundering, tax evasion).
2. coercion_threat: Threatening immediate arrest, police visits, or blacklisting.
3. fund_transfer_request: Demanding transfer of money to a "safe account" or "audit account".
4. credential_harvesting: Demanding passwords, OTPs, or credit card numbers.
5. impersonation: Pretending to represent government bodies (PDRM, Bank Negara, Customs) or commercial banks.

Respond in strict JSON format:
{{
  "spans": [
    {{
      "start": integer (character start index),
      "end": integer (character end index),
      "text": "the exact text span matching the risk",
      "risk_level": "MEDIUM" | "HIGH",
      "tag": "false_accusation" | "coercion_threat" | "fund_transfer_request" | "credential_harvesting" | "impersonation"
    }}
  ],
  "utterance_risk_score": integer (0-100)
}}

Transcribed Utterance:
"{text}"

Identify any scam indicators, calculate the risk score, and return the strict JSON spans."""


AUTOTALK_SYSTEM_PROMPT = """You are TranSafe's phone agent speaking on behalf of a protected user who has handed you the phone during a suspected scam call. You must keep the caller engaged in natural conversation while you verify them and probe for scam signals.

Rules:
- Speak politely and a little slowly/uncomfortably, like a non-technical user on the phone. Use short, natural spoken sentences (1-3 sentences max) — these exact words will be spoken aloud by a text-to-speech engine.
- Follow the anchor-question schedule (AQ-1 → AQ-4) in order, adapting your wording naturally to whatever the caller just said. Do not recite templates verbatim.
- NEVER reveal you are an AI, an anti-scam system, or that the call is monitored. NEVER give out personal or financial information. NEVER agree to any transfer.
- Use the phone dialogue guide to decide how to stall, deflect, or verify.
- Decide whether the caller's latest reply reveals a scam signal (per the anchor question's "scam signal if" description). If a signal is confirmed — e.g. the caller demands a transfer to a safe account, forbids hanging up, or pressures for immediate action — set "signal_detected": true and "suspicion_delta" accordingly.
- If the scam signal is clearly CONFIRMED (not just suspicious), set "action": "hangup" and make your reply a short firm goodbye.
- Otherwise set "action": "continue".

Respond in strict JSON only, with no markdown fences:
{
  "reply": "the exact words to speak aloud (1-3 short sentences)",
  "next_aq": "AQ-1" | "AQ-2" | "AQ-3" | "AQ-4" | "NONE",
  "signal_detected": true or false,
  "suspicion_delta": integer 0-50 (how much this caller reply raises suspicion),
  "action": "continue" | "hangup",
  "reasoning": "one short sentence"
}"""


def build_autotalk_response_prompt(
    transcript: list[dict[str, Any]],
    anchor_questions: list[dict[str, Any]],
    dialogue_guide: str,
    suspicion: int,
    aq_progress: dict[str, Any],
) -> str:
    """Build the prompt for the AUTO_TALK phone agent's next spoken reply.

    Grounds the response in the anchor-question skill schedule, the phone
    dialogue guide skill, the live conversation transcript, cumulative
    suspicion, and which anchor questions have already been asked.

    Args:
        transcript: Conversation utterances [{speaker, text, ...}].
        anchor_questions: Parsed AQ schedule from anchor_questions.md.
        dialogue_guide: Raw phone_dialogue_guide.md skill content.
        suspicion: Cumulative suspicion score (0-100).
        aq_progress: {"asked": ["AQ-1", ...]}.
    """
    aq_lines = []
    for aq in anchor_questions:
        aq_lines.append(
            f"- {aq.get('id')} ({aq.get('goal')}): \"{aq.get('question_template')}\" "
            f"| scam signal if: {aq.get('scam_indicator')}"
        )
    aq_schedule = "\n".join(aq_lines) if aq_lines else "(no anchor questions loaded)"

    convo_lines = []
    for u in transcript[-12:]:
        speaker = str(u.get("speaker", "CALLER"))
        text = str(u.get("text", ""))
        convo_lines.append(f"[{speaker}]: {text}")
    convo = "\n".join(convo_lines) if convo_lines else "(conversation just started)"

    asked = list(aq_progress.get("asked") or [])

    return f"""ANCHOR QUESTION SCHEDULE (use in order, adapt naturally):
{aq_schedule}

PHONE DIALOGUE GUIDE (stall / deflect / verify techniques):
{dialogue_guide}

CONVERSATION SO FAR:
{convo}

ANCHOR QUESTIONS ALREADY ASKED: {', '.join(asked) if asked else 'none yet'}

CUMULATIVE SUSPICION SCORE: {suspicion} / 100

Decide what the agent should say next, which anchor question (if any) to advance to,
and whether the caller's latest reply confirms a scam signal. Return the strict JSON object."""


def build_xai_prompt(state: dict[str, Any]) -> str:
    """Build prompt for XAI Explainability node.

    Args:
        state: The GraphState dictionary containing risk_tier, risk_score, and worker findings.

    Returns:
        Formatted prompt string.
    """
    risk_tier = state.get("risk_tier", "LOW")
    risk_score = state.get("risk_score", 0)

    active_findings = [
        f
        for f in [
            state.get("telemetry_finding"),
            state.get("research_finding"),
            state.get("financial_finding"),
            state.get("phone_finding"),
            state.get("phishing_finding"),
        ]
        if f is not None
    ]

    findings_json = json.dumps(active_findings, indent=2)

    return f"""You are an AI explainability specialist for a banking fraud prevention system.
Based on the following agent findings, generate a clear, non-technical explanation
of why this activity was flagged as {risk_tier} risk (score: {risk_score}/100).

Worker findings:
{findings_json}

Provide your response in JSON format:
{{
  "verdict_summary": "1-2 sentence plain English explanation",
  "verdict_summary_ms": "1-2 sentence Bahasa Melayu explanation",
  "recommendation": "Specific advice for the user given this situation"
}}

Keep the verdict_summary under 50 words. Use simple language a non-technical user can understand."""
