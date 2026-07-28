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
    """Build system and human prompt for Telemetry Worker.

    Args:
        user_id: User identifier.
        session_id: Session identifier.
        device_id: Device identifier.
        events: List of telemetry events.
        metrics: Optional aggregated metrics.
        biometrics: Optional biometrics analysis dictionary.
        fingerprint: Optional device/network fingerprint dictionary.

    Returns:
        Formatted prompt string.
    """
    events_json = json.dumps(events, indent=2)
    metrics_str = json.dumps(metrics, indent=2) if metrics is not None else "N/A"
    biometrics_str = json.dumps(biometrics, indent=2) if biometrics is not None else "N/A"
    fingerprint_str = json.dumps(fingerprint, indent=2) if fingerprint is not None else "N/A"

    return f"""You are an expert fraud behavioral biometrics analyst at a retail bank.
Your job is to analyze the sequence of telemetry events and behavioral biometrics from a user's session and output a risk assessment.
Look for the following signals:
1. Hesitation or Dictation: Typing cadence that is extremely slow (avg flight time > 500ms) or contains high backspace counts, indicating the user is typing under coercion/dictation.
2. Automation/Bots: Flight times near 0ms or highly constant typing speed, indicating automated inputs.
3. Instruction Following: Copy-pasting account numbers or names, erratic mouse cursor movements, and frequent tab switches.
4. Direct Compromise: Orientations changing rapidly, screenshots taken, or active screen sharing flags.

You must respond in strict JSON format with keys "score" (0-100), "confidence" (0.0-1.0), and "evidence" (list of strings).

Analyze the following telemetry and behavioral biometric data:
User ID: {user_id}
Session ID: {session_id}
Device ID: {device_id}

Telemetry Sequence (Newest First):
{events_json}

Aggregated Metrics:
{metrics_str}

Biometrics:
{biometrics_str}

Device/Network Fingerprint:
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
    history_json = json.dumps(history, indent=2)
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
    internal_json = json.dumps(internal_hits, indent=2)
    tavily_json = json.dumps(tavily_hits, indent=2)

    return f"""You are an expert financial fraud research intelligence agent.
Analyze the query entities (phone numbers, bank accounts, URLs) alongside the RAG search results from our internal fraud database and public web reports.
Your job is to determine:
1. If any of the query entities appear directly in historical scam logs (high similarity matches > 0.80).
2. If there are close semantic matches describing similar fraud patterns involving these entities.
3. If public web reports indicate these accounts or numbers are linked to online scams, police reports, or central bank warning lists.

Return your findings in strict JSON format:
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


def build_phishing_analysis_prompt(source: str, content: str) -> str:
    """Build prompt for Phishing Worker content analysis.

    Args:
        source: Material source (e.g., 'TEXT', 'URL', 'IMAGE').
        content: Material content or OCR text to analyze.

    Returns:
        Formatted prompt string.
    """
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

Provide your structured risk finding."""


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
