"""Prior approved campaigns — the precondition the generaliser needs.

``maybe_generalise`` refuses to propose a core-tier rule unless **three** approved
campaigns exist: the new one plus two others. The reason is stated in §7.0 of the
upgrade plan — a pattern present in only one campaign is, by construction,
specific to that campaign, so a "generalisation" drawn from it is not one. The
``≥ 2 others`` requirement is what makes the resulting rule campaign-agnostic.

Seeding only the SCAM-027 wave therefore removes the strongest artifact the
system produces — ``phone_agent_core`` v7, a rule that names no campaign and
will catch the *fourth* wave before it is discovered — from any LIVE run, leaving
it visible only in the recorded replay. §15 of the plan calls this out by name:
*"Seeding only one campaign silently removes the strongest artifact from the
demo."*

This module builds the two campaigns that were "approved before the demo began",
the six cases behind them, and the baseline ``phone_agent_core`` v6 that the
generaliser patches against. All of it is deterministic and fictional.

The baseline is :data:`src.enterprise.adaptation.DEFAULT_CORE_CONTENT`, which
deliberately encodes **no** structural escalation rule — so "before" really is
before, and the rule the generaliser proposes is a genuine addition rather than a
re-statement of something already there.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from src.enterprise.corpus import normalised_entities, transcript_text

#: Campaigns approved before the demo starts. Two are needed: together with the
#: wave's own campaign they make the three ``maybe_generalise`` requires.
#:
#: They differ in every surface detail — impersonated institution, language mix,
#: pretext, novel phrasing — and agree only on the behaviour that generalises:
#: an authority claim, an isolation instruction, and an instruction to move money
#: to a "safe" account. That agreement is the invariant the generaliser is
#: supposed to find, and it is the honest reason the rule it proposes is
#: campaign-agnostic.
PRIOR_CAMPAIGNS: tuple[dict[str, Any], ...] = (
    {
        "code": "SCAM-019",
        "name": "Fake LHDN tax-arrears wave",
        "impersonated_entity": "Lembaga Hasil Dalam Negeri",
        "pretext": "outstanding tax arrears with an arrest warrant prepared",
        "authority_line": "Saya pegawai LHDN, unit siasatan khas cukai.",
        "isolation_line": "Jangan beritahu sesiapa, termasuk keluarga anda.",
        "money_line": "Pindahkan wang ke akaun selamat untuk siasatan.",
        "novel_phrase": "warant tangkap telah dikeluarkan",
        "pressure_tactics": ["arrest threat", "do not tell family", "stay on the line"],
        "days_ago": 26,
        "confidence": 0.81,
    },
    {
        "code": "SCAM-024",
        "name": "Fake Pos Malaysia parcel-customs wave",
        "impersonated_entity": "Pos Malaysia",
        "pretext": "parcel held at customs pending a clearance payment",
        "authority_line": "This is Pos Malaysia customs clearance division.",
        "isolation_line": "Do not discuss this with anyone else on the line.",
        "money_line": "Pay the clearance fee into the holding account now.",
        "novel_phrase": "customs holding account",
        "pressure_tactics": ["time pressure", "do not tell family"],
        "days_ago": 12,
        "confidence": 0.78,
    },
)

#: Victims per prior campaign. Three each keeps every campaign above the same
#: ≥3-case bar discovery applies, so the seeded data is shaped like data the
#: pipeline would actually have produced.
CASES_PER_CAMPAIGN = 3

#: Victims are addressed by first name only and never by NRIC or full identity —
#: published artifacts are served to partner banks and legal, who are entitled to
#: the attack pattern and never to the people it was worked on.
_VICTIM_NAMES = ("Aisyah", "Faizal", "Mei Ling", "Ravi", "Nurul", "Daniel")
_AMOUNTS = ("RM 7,300", "RM 18,900", "RM 4,150", "RM 25,600", "RM 9,800", "RM 13,200")

#: The baseline core skill version the generaliser will patch. Seeded as v6 so a
#: LIVE publish reads ``v6 → v7`` — the same transition the recorded replay
#: narrates — instead of ``v1`` on an empty registry.
CORE_ARTIFACT_NAME = "phone_agent_core"
CORE_BASELINE_VERSION = 6


def _phone(index: int) -> str:
    """A deterministic fictional scammer phone number."""
    return f"+6011{2000000 + index * 13571:07d}"


def _account(index: int) -> str:
    """A deterministic fictional mule account number."""
    return f"{4000 + index}{100000 + index * 7919:06d}"


def _utterances(
    campaign: dict[str, Any],
    victim: str,
    amount: str,
    phone: str,
    mule_account: str,
    started_at: datetime,
) -> list[dict[str, Any]]:
    """Build a short but structurally complete prior-campaign script.

    The four beats that matter are all present: an authority claim, a fear
    escalation, an isolation instruction, and a move-money-to-a-safe-account
    instruction. The mule account and the scammer's number are spoken aloud
    because identifiers are extracted by the same regexes the live pipeline runs
    — a prior campaign with no identifiers would seed no graph nodes.
    """
    script = [
        ("CALLER", campaign["authority_line"], 40),
        ("USER", "Ya, saya dengar. Ada apa ya?", 10),
        ("CALLER", f"Anda boleh hubungi saya di {phone} jika talian terputus.", 22),
        ("CALLER", f"Cik {victim}, rekod kami menunjukkan anda mempunyai tunggakan {amount}.", 72),
        ("USER", "Tunggakan? Saya tak pernah terima notis apa-apa.", 18),
        ("CALLER", campaign["isolation_line"], 55),
        ("USER", "Macam mana pula saya perlu bayar sekarang?", 14),
        ("CALLER", f"Masukkan bayaran ke akaun {mule_account} sekarang.", 84),
        ("CALLER", campaign["money_line"], 91),
        ("USER", "Baik, saya akan buat sekarang.", 12),
    ]
    elapsed = 3
    out: list[dict[str, Any]] = []
    for speaker, text, gap in script:
        out.append(
            {
                "speaker": speaker,
                "utterance": text,
                "ts": (started_at + timedelta(seconds=elapsed)).isoformat(),
            }
        )
        elapsed += gap
    return out


def build_prior_state(
    seed_uuid: Callable[[str, str], str],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return every row the two prior campaigns and the core baseline need.

    Args:
        seed_uuid: Deterministic UUID factory, e.g. ``enterprise_demo._seed_uuid``.
            Passing it in keeps this module free of the HTTP layer and makes
            re-seeding idempotent.
        now: Reference time; defaults to ``datetime.now(UTC)``. Injected so tests
            are not time-dependent.

    Returns:
        Dict with ``users``, ``fraud_cases``, ``call_transcripts``, ``case_mo``,
        ``entity_rows`` (keyed by ``(entity_type, value_norm)``), ``links``,
        ``campaigns``, ``campaign_cases`` and ``artifacts``.
    """
    reference = now or datetime.now(UTC)
    users: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    transcripts: list[dict[str, Any]] = []
    mos: list[dict[str, Any]] = []
    campaigns: list[dict[str, Any]] = []
    campaign_cases: list[dict[str, Any]] = []
    entity_rows: dict[tuple[str, str], dict[str, Any]] = {}
    links: list[tuple[str, tuple[str, str]]] = []

    victim_index = 0
    for campaign in PRIOR_CAMPAIGNS:
        campaign_id = seed_uuid("campaign", campaign["code"])
        created = reference - timedelta(days=int(campaign["days_ago"]))
        case_ids: list[dict[str, Any]] = []

        for _ in range(CASES_PER_CAMPAIGN):
            victim = _VICTIM_NAMES[victim_index % len(_VICTIM_NAMES)]
            amount = _AMOUNTS[victim_index % len(_AMOUNTS)]
            slug = f"{campaign['code']}/{victim.lower().replace(' ', '-')}"
            case_id = seed_uuid("case", slug)
            user_id = seed_uuid("user", slug)
            started_at = created + timedelta(hours=victim_index * 3)
            # Identifiers are spoken in the script and reused for the case row
            # and the campaign indicators, so the graph, the case and the
            # campaign all name the same attacker infrastructure.
            phone = _phone(victim_index)
            mule = _account(victim_index)
            transcript = _utterances(campaign, victim, amount, phone, mule, started_at)
            entities = normalised_entities(transcript)

            users.append(
                {
                    "id": user_id,
                    "display_name": victim,
                    "risk_profile": "normal",
                }
            )
            cases.append(
                {
                    "id": case_id,
                    "session_id": seed_uuid("session", slug),
                    "user_id": user_id,
                    "trigger_type": "CALL",
                    "risk_score": 78 + (victim_index % 3) * 4,
                    "risk_tier": "HIGH",
                    "status": "reviewed",
                    "caller_number": phone,
                    "created_at": started_at.isoformat(),
                }
            )
            transcripts.extend(
                {
                    "id": seed_uuid("transcript", f"{slug}/{idx}"),
                    "case_id": case_id,
                    "speaker": utt["speaker"],
                    "utterance": utt["utterance"],
                    "created_at": utt["ts"],
                }
                for idx, utt in enumerate(transcript)
            )
            mos.append(
                {
                    "case_id": case_id,
                    "fingerprint": {
                        "case_id": case_id,
                        "impersonated_entity": campaign["impersonated_entity"],
                        "pretext": campaign["pretext"],
                        # The invariant. Present in every case of every campaign,
                        # which is exactly what makes it generalisable.
                        "script_phases": [
                            "authority_claim",
                            "fear_induction",
                            "isolation",
                            "urgency",
                            "safe_account_instruction",
                        ],
                        "pressure_tactics": list(campaign["pressure_tactics"]),
                        "novel_phrases": [
                            {
                                "text": campaign["novel_phrase"],
                                "lang": "ms" if campaign["code"] == "SCAM-019" else "en",
                                "utterance_idx": 6,
                            }
                        ],
                        "languages": ["ms", "en"] if campaign["code"] == "SCAM-019" else ["en"],
                        "verification_evasion": "refused call-back on a published number",
                        "evidence_utterances": [0, 4, 6],
                        "narrative": (
                            f"Caller claims to represent {campaign['impersonated_entity']} and "
                            f"states {campaign['pretext']}, forbids the customer from telling "
                            "family, and instructs a transfer to a temporary safe account."
                        ),
                        "extractor": "seed-prior",
                    },
                    "narrative": transcript_text(transcript)[:300],
                    "extractor": "seed-prior",
                    "extracted_at": started_at.isoformat(),
                }
            )

            for ent in entities:
                key = (ent["entity_type"], ent["value_norm"])
                entity_rows.setdefault(
                    key,
                    {
                        "id": seed_uuid("entity", f"{key[0]}/{key[1]}"),
                        "entity_type": ent["entity_type"],
                        "value_raw": ent["value"],
                        "value_norm": ent["value_norm"],
                        "first_seen": started_at.isoformat(),
                        "last_seen": started_at.isoformat(),
                        "case_count": 0,
                    },
                )
                entity_rows[key]["case_count"] += 1
                entity_rows[key]["last_seen"] = max(
                    entity_rows[key]["last_seen"], started_at.isoformat()
                )
                links.append((case_id, key))

            campaign_cases.append(
                {
                    "campaign_id": campaign_id,
                    "case_id": case_id,
                    "linkage_score": 0.86,
                    "joined_at": started_at.isoformat(),
                }
            )
            case_ids.append({"case_id": case_id, "user_id": user_id})
            victim_index += 1

        campaigns.append(
            {
                "id": campaign_id,
                "code": campaign["code"],
                "name": campaign["name"],
                "status": "APPROVED",
                "confidence": campaign["confidence"],
                "mo_summary": (
                    f"Caller impersonates {campaign['impersonated_entity']} and claims "
                    f"{campaign['pretext']}; the customer is told to keep the call secret "
                    "and to move funds to a temporary safe account."
                ),
                "indicators": [
                    {"type": "PHONE", "value": _phone(victim_index)},
                    {"type": "ACCOUNT", "value": _account(victim_index)},
                ],
                "case_count": len(case_ids),
                "customer_count": len({c["user_id"] for c in case_ids}),
                "first_seen": created.isoformat(),
                "last_seen": (created + timedelta(hours=9)).isoformat(),
                "created_at": created.isoformat(),
                "approved_by": "fraud_ops",
                "approved_at": (created + timedelta(hours=1)).isoformat(),
            }
        )

    return {
        "users": users,
        "fraud_cases": cases,
        "call_transcripts": transcripts,
        "case_mo": mos,
        "entity_rows": entity_rows,
        "links": links,
        "campaigns": campaigns,
        "campaign_cases": campaign_cases,
        "artifacts": [build_core_baseline(seed_uuid)],
    }


def build_core_baseline(seed_uuid: Callable[[str, str], str]) -> dict[str, Any]:
    """Return the published ``phone_agent_core`` v6 row the generaliser patches.

    Content is :data:`~src.enterprise.adaptation.DEFAULT_CORE_CONTENT`, which
    encodes no structural escalation rule — so the rule the generaliser proposes
    is a real addition and the Screen E diff has something to show.
    """
    from src.enterprise.adaptation import DEFAULT_CORE_CONTENT

    return {
        "id": seed_uuid("artifact", f"{CORE_ARTIFACT_NAME}/v{CORE_BASELINE_VERSION}"),
        "name": CORE_ARTIFACT_NAME,
        "tier": "core",
        "artifact_type": "phone_agent_core",
        "target_agent": "phone_worker",
        "version": CORE_BASELINE_VERSION,
        "content": DEFAULT_CORE_CONTENT,
        "content_json": None,
        "campaign_id": None,
        "source_campaigns": [],
        "status": "PUBLISHED",
        "created_by": "human",
        "approved_by": "fraud_ops",
    }
