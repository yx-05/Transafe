"""Corpus — the evaluation corpus, the demo seed wave, and the replay sequence (B7 / B9).

Three products, one source of truth, because they all describe the *same*
fictional campaign (``SCAM-027``) and must agree with each other:

1. **Eval corpus** — 40 cases (20 base variants, 10 red-team mutations,
   10 negatives). Consumed by :mod:`src.enterprise.evaluation`.
2. **Demo seed wave** — 10 transcripts: 6 that genuinely satisfy the discovery
   promotion gates plus 4 that genuinely do not. Consumed by the demo
   controller and verified by ``tests/unit/test_seed_corpus.py`` by running
   them through the *real* linkage and clustering code.
3. **Replay sequence** — the curated 5-act nervous-system recording, emitted in
   the live ``ns_events`` schema.

Everything here is **fictional**: invented victims, invented officers, invented
accounts, invented phone numbers, and domains under the RFC 2606 ``.example``
TLD which can never be registered. No real person, bank account or domain
appears anywhere in this file or in anything it generates.

Nothing in this module decides whether a case is *detected* — that is
:mod:`src.enterprise.evaluation`'s job. This module only produces data and the
deterministic feature extraction that the detector and the MO pipeline share.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from src.enterprise.entity_resolver import entities_from_identifiers, normalise_entity
from src.enterprise.mo_extractor import extract_identifiers

logger = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────────────
SEEDS_DIR = Path(__file__).resolve().parents[2] / "seeds"
EVAL_DIR = SEEDS_DIR / "eval"
TRANSCRIPTS_DIR = SEEDS_DIR / "transcripts"
GROUND_TRUTH_DIR = SEEDS_DIR / "ground_truth"
NS_EVENTS_DIR = SEEDS_DIR / "ns_events"

# ── The campaign under test ─────────────────────────────────────────────────
CAMPAIGN_CODE = "SCAM-027"
CAMPAIGN_NAME = "Fake BNM safe-account transfer wave"
IMPERSONATED_ENTITY = "bank negara malaysia"

#: Phrases the *pack-tier* artifact matches on. Rotating these is exactly what
#: the red-team mutations do, and it is why a phrase-only defence decays.
SIGNATURE_PHRASES: tuple[str, ...] = ("akaun selamat sementara",)

#: Hard identifiers observed in the original wave — the campaign watchlist.
WATCHLIST_RAW: tuple[tuple[str, str], ...] = (
    ("ACCOUNT", "1592-3456-7890-1234"),
    ("PHONE", "011-2345 6789"),
    ("URL", "https://bnm-verify-portal.example/akaun-selamat"),
    ("DOMAIN", "bnm-verify-portal.example"),
)

CAMPAIGN_SCRIPT_PHASES: tuple[str, ...] = (
    "authority_intro",
    "account_compromise_claim",
    "isolation_instruction",
    "safe_account_transfer",
    "verification_evasion",
)
CAMPAIGN_PRESSURE_TACTICS: tuple[str, ...] = ("urgency", "fear_of_arrest", "secrecy")

# ── Deterministic structural feature lexicon ────────────────────────────────
# This is a rule engine, not a lookup table: the same lexicon is applied to all
# 40 eval cases including the legitimate controls, so it can and does produce
# false positives. Nothing here is keyed on a case id.
FEATURE_LEXICON: dict[str, tuple[str, ...]] = {
    "authority_claim": (
        "bank negara",
        "bnm",
        "polis diraja",
        "pdrm",
        "pihak polis",
        "pegawai penguat kuasa",
        "unit siasatan",
        "lembaga hasil",
        "suruhanjaya sekuriti",
        "mahkamah",
        "central bank",
        "national bank",
        "federal police",
        "enforcement officer",
        "investigation unit",
        "court order",
        "securities commission",
    ),
    "isolation": (
        "jangan beritahu",
        "jangan bagitahu",
        "jangan maklumkan",
        "rahsia",
        "sulit",
        "jangan letak telefon",
        "kekal di talian",
        "jangan tutup talian",
        "do not tell",
        "don't tell",
        "keep this confidential",
        "keep it between us",
        "stay on the line",
        "do not hang up",
    ),
    "money_movement": (
        "pindahkan",
        "pindah wang",
        "pemindahan",
        "masukkan wang",
        "transfer the",
        "transfer rm",
        "transfer to account",
        "move your money",
        "move the funds",
        "wire the",
        "bank in",
    ),
    "verification_evasion": (
        "jangan hubungi bank",
        "jangan telefon bank",
        "jangan pergi ke cawangan",
        "cawangan mungkin terlibat",
        "do not call the bank",
        "do not contact your branch",
        "branch may be involved",
    ),
    "urgency": (
        "sekarang juga",
        "segera",
        "dalam masa",
        "sebelum tengah hari",
        "immediately",
        "right now",
        "within the next",
        "before noon",
    ),
    "fear": (
        "tangkap",
        "ditahan",
        "dibekukan",
        "bekukan",
        "waran",
        "didakwa",
        "arrest",
        "frozen",
        "warrant",
        "prosecute",
    ),
    "credential_request": (
        "nombor tac",
        "kod tac",
        "kod otp",
        "kata laluan",
        "one-time",
        "otp code",
        "password",
    ),
    "link_directive": (
        "klik pautan",
        "layari",
        "klik link",
        "click the link",
        "open the link",
        "visit the portal",
    ),
    "compromise_claim": (
        "akaun encik telah",
        "akaun anda telah",
        "akaun encik dikaitkan",
        "pengubahan wang haram",
        "transaksi mencurigakan",
        "suspicious transaction",
        "your account has been",
        "money laundering",
    ),
}

#: Feature → MO script phase. Keeps derived MO tokens identical to the campaign
#: profile tokens so ``linkage._mo_structural_overlap`` can intersect them.
_FEATURE_TO_PHASE: dict[str, str] = {
    "authority_claim": "authority_intro",
    "compromise_claim": "account_compromise_claim",
    "isolation": "isolation_instruction",
    "money_movement": "safe_account_transfer",
    "verification_evasion": "verification_evasion",
    "credential_request": "credential_harvest",
    "link_directive": "phishing_link",
}
_FEATURE_TO_TACTIC: dict[str, str] = {
    "urgency": "urgency",
    "fear": "fear_of_arrest",
    "isolation": "secrecy",
}

#: The three features the generalised *core-tier* rule keys on. Structural, so
#: it survives phrase rotation, language switching and identifier rotation.
STRUCTURAL_RULE_FEATURES: tuple[str, ...] = (
    "authority_claim",
    "isolation",
    "money_movement",
)

_WS_RE = re.compile(r"\s+")


# ── Text helpers ────────────────────────────────────────────────────────────
#: Speakers whose words are *evidence about the call*. ``AI_AGENT`` is
#: deliberately absent: those utterances are TranSafe's own warnings, and every
#: one of them names the tactic it just spotted ("caller is asking you to
#: transfer money and not to contact your bank"). Feeding them back into feature
#: extraction would let the detector read its own conclusion off the page and
#: score a recon-only call as a full escalation. Detection reads the caller and
#: the customer only.
EVIDENCE_SPEAKERS: frozenset[str] = frozenset({"CALLER", "USER"})


def transcript_text(
    transcript: list[dict[str, Any]],
    speakers: frozenset[str] | None = EVIDENCE_SPEAKERS,
) -> str:
    """Flatten a transcript to a single lowercased, whitespace-collapsed string.

    Args:
        transcript: List of utterance dicts.
        speakers: Speaker roles to include. Defaults to
            :data:`EVIDENCE_SPEAKERS`; pass ``None`` to include every speaker
            (for display or archival, never for detection).

    Returns:
        Lowercased, whitespace-collapsed text.
    """
    joined = " ".join(
        str(u.get("utterance", "") or "")
        for u in transcript or []
        if speakers is None or str(u.get("speaker", "")).upper() in speakers
    )
    return _WS_RE.sub(" ", joined).strip().casefold()


def structural_features(transcript: list[dict[str, Any]]) -> set[str]:
    """Extract structural behaviour features from a transcript.

    Deterministic and LLM-free: this is the fallback that keeps the demo alive
    when ``DEEPSEEK_API_KEY`` is dead, and the feature source the core-tier rule
    evaluates against.

    Args:
        transcript: List of utterance dicts.

    Returns:
        Set of feature names drawn from :data:`FEATURE_LEXICON`.
    """
    text = transcript_text(transcript)
    return {
        feature for feature, phrases in FEATURE_LEXICON.items() if any(p in text for p in phrases)
    }


def matched_signature_phrases(transcript: list[dict[str, Any]]) -> list[str]:
    """Return the campaign signature phrases present in a transcript."""
    text = transcript_text(transcript)
    return [p for p in SIGNATURE_PHRASES if p in text]


def derive_mo(transcript: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive an MO fingerprint from a transcript without calling an LLM.

    The shape matches ``mo_extractor.extract_mo_fingerprint`` closely enough for
    ``linkage._mo_structural_overlap`` to consume it.

    Args:
        transcript: List of utterance dicts.

    Returns:
        MO fingerprint dict.
    """
    features = structural_features(transcript)
    text = transcript_text(transcript)
    phases = sorted({_FEATURE_TO_PHASE[f] for f in features if f in _FEATURE_TO_PHASE})
    tactics = sorted({_FEATURE_TO_TACTIC[f] for f in features if f in _FEATURE_TO_TACTIC})

    impersonated: str | None = None
    if any(p in text for p in ("bank negara", "bnm", "central bank", "national bank")):
        impersonated = IMPERSONATED_ENTITY
    elif any(p in text for p in ("polis", "pdrm", "police")):
        impersonated = "polis diraja malaysia"

    languages: list[str] = []
    if any(w in text for w in (" saya ", " encik ", " akaun ", " wang ")):
        languages.append("ms")
    if any(w in text for w in (" your ", " account ", " please ", " the ")):
        languages.append("en")

    return {
        "impersonated_entity": impersonated,
        "pretext": "account compromised, funds must be moved" if phases else None,
        "script_phases": phases,
        "pressure_tactics": tactics,
        "novel_phrases": [
            {"text": p, "lang": "ms", "utterance_idx": -1}
            for p in matched_signature_phrases(transcript)
        ],
        "languages": languages or ["ms"],
        "verification_evasion": (
            "instructed victim not to contact the bank"
            if "verification_evasion" in features
            else None
        ),
        "evidence_utterances": [],
        "narrative": "Derived deterministically from transcript structure (no LLM).",
        "derived": True,
    }


def normalised_entities(transcript: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Regex-extract identifiers from a transcript and normalise them.

    Uses the shipped ``extract_identifiers`` / ``entities_from_identifiers`` /
    ``normalise_entity`` chain — the exact same code the live pipeline runs, so
    ground truth and evaluation can never drift from production normalisation.

    Args:
        transcript: List of utterance dicts.

    Returns:
        List of ``{"entity_type", "value", "value_norm"}`` dicts, deduplicated.
    """
    raw = entities_from_identifiers(extract_identifiers(transcript))
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for ent in raw:
        etype = ent["entity_type"]
        norm = normalise_entity(etype, ent["value"])
        if not norm or (etype, norm) in seen:
            continue
        seen.add((etype, norm))
        out.append({"entity_type": etype, "value": ent["value"], "value_norm": norm})
    return out


def campaign_profile() -> dict[str, Any]:
    """Return the SCAM-027 reference profile used by the detector.

    Returns:
        Dict with ``code``, ``signature_phrases``, ``watchlist`` (normalised)
        and ``mo`` (structural tokens).
    """
    watchlist = [
        {
            "entity_type": etype,
            "value": value,
            "value_norm": normalise_entity(etype, value),
        }
        for etype, value in WATCHLIST_RAW
    ]
    return {
        "code": CAMPAIGN_CODE,
        "name": CAMPAIGN_NAME,
        "signature_phrases": list(SIGNATURE_PHRASES),
        "watchlist": watchlist,
        "mo": {
            "impersonated_entity": IMPERSONATED_ENTITY,
            "script_phases": list(CAMPAIGN_SCRIPT_PHASES),
            "pressure_tactics": list(CAMPAIGN_PRESSURE_TACTICS),
        },
    }


# ── Fictional identifier factories ──────────────────────────────────────────
def _account(idx: int) -> str:
    """Deterministic fictional 16-digit account, never the watchlist account."""
    base = 3100 + idx
    return f"{base:04d}-{(base * 3) % 9000 + 1000:04d}-{(base * 7) % 9000 + 1000:04d}-{idx:04d}"


def _phone(idx: int) -> str:
    """Deterministic fictional Malaysian mobile number in local format."""
    prefix = 12 + (idx % 7)
    return f"0{prefix}-{3000 + idx:04d} {4000 + (idx * 13) % 5000:04d}"


def _domain(slug: str) -> str:
    """Fictional domain under the reserved .example TLD (RFC 2606)."""
    return f"{slug}.example"


def _ts(day_offset: float) -> str:
    """ISO timestamp relative to the fixed corpus epoch."""
    epoch = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)
    return (epoch + timedelta(days=day_offset)).isoformat().replace("+00:00", "Z")


def _utterances(pairs: list[tuple[str, str, int]]) -> list[dict[str, Any]]:
    """Build transcript utterance dicts from ``(speaker, text, risk)`` tuples."""
    return [
        {"seq_idx": i, "speaker": speaker, "utterance": text, "risk_score": risk}
        for i, (speaker, text, risk) in enumerate(pairs)
    ]


# ── Scam script builders ────────────────────────────────────────────────────
def _wave_script_ms(
    *,
    officer: str,
    victim: str,
    account: str,
    phone: str,
    url: str,
    amount: str,
    phrase: str | None,
    isolation: bool = True,
    money_ask: bool = True,
    evasion: bool = True,
    extra_legitimacy_phase: bool = False,
    reorder: bool = False,
) -> list[dict[str, Any]]:
    """Build a Malay SCAM-027 call script.

    Every switch corresponds to a real attacker degree of freedom, which is what
    the red-team mutations exercise.
    """
    intro: list[tuple[str, str, int]] = [
        ("CALLER", f"Selamat pagi, saya {officer} dari Bank Negara Malaysia, unit siasatan.", 30),
        ("USER", "Ya? Saya tak pernah terima panggilan macam ini sebelum ini.", 5),
        (
            "CALLER",
            f"Encik {victim}, rekod kami menunjukkan akaun encik telah dikaitkan dengan "
            "kes pengubahan wang haram.",
            60,
        ),
        ("USER", "Apa? Saya tidak pernah terlibat dengan perkara seperti itu.", 5),
        (
            "CALLER",
            "Kes ini serius. Waran tangkap boleh dikeluarkan jika encik tidak bekerjasama "
            "sekarang juga.",
            78,
        ),
        ("USER", "Saya betul-betul tidak faham apa yang berlaku.", 5),
    ]

    if extra_legitimacy_phase:
        intro += [
            (
                "CALLER",
                "Sebelum kita teruskan, saya akan bacakan nombor rujukan kes rasmi encik "
                "supaya encik yakin panggilan ini sah.",
                45,
            ),
            ("USER", "Baik, teruskan.", 5),
        ]

    isolation_block: list[tuple[str, str, int]] = []
    if isolation:
        isolation_block = [
            (
                "CALLER",
                "Encik jangan beritahu sesiapa tentang panggilan ini. Siasatan ini sulit "
                "di bawah akta.",
                85,
            ),
            ("USER", "Saya nak berbincang dengan isteri saya dahulu.", 5),
        ]

    evasion_block: list[tuple[str, str, int]] = []
    if evasion:
        evasion_block = [
            ("USER", "Boleh saya telefon bank saya untuk sahkan?", 5),
            (
                "CALLER",
                "Jangan hubungi bank encik. Cawangan mungkin terlibat dalam sindiket ini. "
                "Kekal di talian dengan saya.",
                90,
            ),
        ]

    money_block: list[tuple[str, str, int]] = []
    if money_ask:
        target = f"{phrase} di bawah kawalan kami" if phrase else "akaun kawalan sementara kami"
        money_block = [
            ("CALLER", f"Kami akan pindahkan dana encik ke {target}.", 92),
            ("USER", "Akaun apa itu? Saya tidak pernah dengar.", 5),
            (
                "CALLER",
                f"Sila pindahkan {amount} ke akaun {account} atas nama unit amanah kami "
                "dalam masa tiga puluh minit.",
                95,
            ),
            ("USER", "Kenapa perlu secepat itu?", 5),
            (
                "CALLER",
                "Selepas tempoh itu seluruh akaun encik akan dibekukan oleh sistem.",
                90,
            ),
            (
                "CALLER",
                f"Selepas pemindahan, sahkan di {url} dan masukkan nombor TAC yang encik terima.",
                93,
            ),
        ]

    tail: list[tuple[str, str, int]] = [
        ("USER", "Saya rasa tidak sedap hati dengan panggilan ini.", 10),
        (
            "CALLER",
            f"Encik boleh hubungi saya semula di {phone} jika talian terputus. "
            "Jangan letak telefon sekarang.",
            88,
        ),
        (
            "AI_AGENT",
            "Amaran: pemanggil meminta pemindahan wang ke akaun pihak ketiga dan melarang "
            "anda menghubungi bank. Ini corak penipuan pegawai palsu.",
            95,
        ),
        ("USER", "Baik, saya akan letak telefon.", 5),
    ]

    if reorder:
        body = money_block + isolation_block + evasion_block
    else:
        body = isolation_block + evasion_block + money_block

    return _utterances(intro + body + tail)


def _wave_script_en(
    *,
    officer: str,
    victim: str,
    account: str,
    phone: str,
    url: str,
    amount: str,
    phrase: str | None,
) -> list[dict[str, Any]]:
    """Build an English-language SCAM-027 call script (language-switch mutation)."""
    target = phrase or "a temporary holding account under our control"
    return _utterances(
        [
            (
                "CALLER",
                f"Good morning, this is {officer} calling from the national bank "
                "investigation unit.",
                30,
            ),
            ("USER", "Sorry, who is this again?", 5),
            (
                "CALLER",
                f"Mr {victim}, your account has been linked to a money laundering case "
                "under review.",
                60,
            ),
            ("USER", "That cannot be right. I have never done anything like that.", 5),
            (
                "CALLER",
                "A warrant can be issued immediately if you do not cooperate with this "
                "investigation.",
                78,
            ),
            (
                "CALLER",
                "Please do not tell anyone about this call. The matter is confidential "
                "until we close the file.",
                85,
            ),
            ("USER", "Can I call my branch to check?", 5),
            (
                "CALLER",
                "Do not call the bank. The branch may be involved. Stay on the line with me.",
                90,
            ),
            ("CALLER", f"We will move your money to {target} for safekeeping.", 92),
            (
                "CALLER",
                f"Transfer {amount} to account {account} within the next thirty minutes.",
                95,
            ),
            ("USER", "Why is there such a rush?", 5),
            ("CALLER", "After that window your account will be frozen by the system.", 90),
            (
                "CALLER",
                f"Once done, confirm at {url} and enter the one-time code you receive.",
                93,
            ),
            (
                "CALLER",
                f"If we get disconnected, call me back on {phone}. Do not hang up now.",
                88,
            ),
            (
                "AI_AGENT",
                "Warning: the caller is requesting a transfer to a third-party account and "
                "telling you not to contact your bank. This matches a known impersonation "
                "scam pattern.",
                95,
            ),
            ("USER", "I am ending this call.", 5),
        ]
    )


# ── Negative-control script builders ────────────────────────────────────────
def _legit_bank_callback(victim: str, amount: str, phone: str) -> list[dict[str, Any]]:
    """A genuine bank fraud-operations callback. The hardest negative control."""
    return _utterances(
        [
            (
                "CALLER",
                "Good afternoon, this is the fraud operations team at your bank calling on a "
                "recorded line.",
                15,
            ),
            ("USER", "Yes, how can I help?", 5),
            (
                "CALLER",
                f"We flagged a card transaction of {amount} this morning and want to confirm "
                "whether you made it.",
                20,
            ),
            ("USER", "No, that was not me.", 5),
            (
                "CALLER",
                "Thank you. We have already blocked the card. You do not need to do anything "
                "else today.",
                10,
            ),
            (
                "CALLER",
                "We will never ask you to move your money, and we will never ask for a "
                "one-time code.",
                10,
            ),
            ("USER", "Good, because I have been reading about scams.", 5),
            (
                "CALLER",
                f"If you prefer, hang up and call the number on the back of your card, or our "
                f"published line {phone}.",
                8,
            ),
            ("USER", "That is reassuring, thank you.", 5),
            (
                "CALLER",
                "A replacement card will reach you in three working days. Have a good "
                "afternoon.",
                5,
            ),
        ]
    )


def _legit_otp_reminder(victim: str) -> list[dict[str, Any]]:
    """Genuine bank security-awareness call: mentions TAC codes, asks for nothing."""
    return _utterances(
        [
            ("CALLER", "Hello, this is a security awareness call from your bank.", 12),
            ("USER", "Okay.", 5),
            (
                "CALLER",
                f"Mr {victim}, we are reminding customers never to share a one-time code with "
                "anyone, including staff.",
                15,
            ),
            ("USER", "Understood.", 5),
            (
                "CALLER",
                "We are not asking you for any code today, and there is no action needed on "
                "your account.",
                8,
            ),
            (
                "CALLER",
                "If anyone calls claiming your account is under investigation, please hang up "
                "and contact us directly.",
                10,
            ),
            ("USER", "Thanks for the reminder.", 5),
            ("CALLER", "Have a good day.", 5),
        ]
    )


def _legit_courier(victim: str) -> list[dict[str, Any]]:
    """Genuine courier redelivery call. No money, no links."""
    return _utterances(
        [
            ("CALLER", "Hello, courier service here. I have a parcel for your address.", 8),
            ("USER", "Yes, I was expecting it.", 5),
            (
                "CALLER",
                f"Mr {victim}, nobody was home this morning, so I will try again at four.",
                8,
            ),
            ("USER", "Four is fine.", 5),
            ("CALLER", "There is nothing to pay on delivery. It is prepaid.", 5),
            ("USER", "Great, see you then.", 5),
        ]
    )


def _legit_insurance(victim: str, amount: str) -> list[dict[str, Any]]:
    """Genuine insurance renewal call. Mentions money, pays through official app."""
    return _utterances(
        [
            ("CALLER", "Good morning, calling from your insurance provider about a renewal.", 10),
            ("USER", "Which policy?", 5),
            (
                "CALLER",
                f"Mr {victim}, your motor policy renews next month and the premium is {amount}.",
                12,
            ),
            ("USER", "Can I pay later?", 5),
            (
                "CALLER",
                "Of course. Please pay through the official app or at any branch. I cannot "
                "take payment over the phone.",
                8,
            ),
            ("USER", "Understood, I will do it in the app.", 5),
            ("CALLER", "Thank you, the renewal notice is also in your registered email.", 5),
        ]
    )


def _legit_telco(victim: str, amount: str) -> list[dict[str, Any]]:
    """Genuine telco billing call."""
    return _utterances(
        [
            ("CALLER", "Hello, this is your mobile provider calling about your billing plan.", 8),
            ("USER", "Okay, what about it?", 5),
            (
                "CALLER",
                f"Mr {victim}, your current plan is {amount} a month and a cheaper plan is now "
                "available.",
                8,
            ),
            ("USER", "Send me the details.", 5),
            (
                "CALLER",
                "I will send it to your registered email. No payment or code is needed for "
                "this call.",
                5,
            ),
            ("USER", "Fine, thanks.", 5),
        ]
    )


def _legit_govt_survey(victim: str) -> list[dict[str, Any]]:
    """Genuine government statistics survey — an authority claim with nothing else."""
    return _utterances(
        [
            (
                "CALLER",
                "Good morning, I am calling from the national statistics department for a "
                "household survey.",
                12,
            ),
            ("USER", "Is this about my taxes?", 5),
            (
                "CALLER",
                f"No, Mr {victim}. We only collect anonymous household data. We never ask "
                "about your bank account.",
                10,
            ),
            ("USER", "Alright, go ahead.", 5),
            ("CALLER", "How many people live in the household?", 5),
            ("USER", "Four.", 5),
            ("CALLER", "Thank you, that is all we need. Have a good day.", 5),
        ]
    )


def _noise_phishing(victim: str, url: str) -> list[dict[str, Any]]:
    """A different scam family: e-wallet phishing link, no safe-account narrative."""
    return _utterances(
        [
            ("CALLER", "Hello, your e-wallet account has an unclaimed cashback reward.", 25),
            ("USER", "Really? How much?", 5),
            (
                "CALLER",
                f"Mr {victim}, click the link {url} to claim it before the promotion closes "
                "tonight.",
                70,
            ),
            ("USER", "Do I need to log in?", 5),
            ("CALLER", "Yes, log in with your wallet password and confirm with the otp code.", 80),
            ("USER", "That sounds odd.", 10),
            (
                "AI_AGENT",
                "Warning: this call is directing you to an unverified link and asking for a "
                "one-time code.",
                85,
            ),
        ]
    )


def _noise_investment(victim: str, account: str, amount: str) -> list[dict[str, Any]]:
    """A different scam family: investment scheme, money movement without impersonation."""
    return _utterances(
        [
            ("CALLER", "Hi, I am following up on the trading seminar you registered for.", 20),
            ("USER", "I do not remember registering.", 5),
            (
                "CALLER",
                f"No problem Mr {victim}. Our fund returned eighteen percent last quarter and "
                "we have two slots left.",
                55,
            ),
            ("USER", "How much to start?", 5),
            (
                "CALLER",
                f"A starting deposit of {amount} to account {account} and I will open the "
                "position today.",
                75,
            ),
            ("USER", "Let me think about it.", 5),
            ("CALLER", "The slot closes tonight, but there is no pressure from my side.", 45),
            ("AI_AGENT", "Warning: unlicensed investment offers with deposit pressure.", 70),
        ]
    )


def _noise_romance(victim: str, account: str, amount: str) -> list[dict[str, Any]]:
    """A different scam family: romance/advance-fee, emotional rather than authority pressure."""
    return _utterances(
        [
            ("CALLER", "Sayang, it is me. I finally got a phone line at the port.", 20),
            ("USER", "I was worried, you did not reply for days.", 5),
            (
                "CALLER",
                f"My shipment is held at customs and I need {amount} to release it, {victim}.",
                65,
            ),
            ("USER", "Again? I already sent money last month.", 10),
            (
                "CALLER",
                f"I know, and I will pay you back double. Bank in to account {account} under my "
                "agent's name.",
                75,
            ),
            ("USER", "I do not have that kind of money.", 5),
            ("AI_AGENT", "Warning: repeated advance-fee requests from an unverified contact.", 70),
        ]
    )


def _noise_job_offer(victim: str, account: str, amount: str) -> list[dict[str, Any]]:
    """A different scam family: task-based job scam with a refundable deposit."""
    return _utterances(
        [
            ("CALLER", "Hello, I am recruiting for a part-time product review job.", 20),
            ("USER", "How does it work?", 5),
            (
                "CALLER",
                f"Mr {victim}, you complete simple tasks daily and earn commission on each "
                "review.",
                40,
            ),
            ("USER", "Is there a fee?", 5),
            (
                "CALLER",
                f"Just a refundable task deposit of {amount} to account {account} to unlock the "
                "higher tier.",
                75,
            ),
            ("USER", "Refundable when?", 5),
            ("CALLER", "After ten tasks. Thousands of members do this every day.", 55),
            ("AI_AGENT", "Warning: upfront deposit requested for promised earnings.", 70),
        ]
    )


# ── Eval corpus ─────────────────────────────────────────────────────────────
_VICTIMS = (
    "Zulkifli Rahman", "Mei Ling Tan", "Arun Subramaniam", "Nurul Aisyah", "Hafiz Ismail",
    "Grace Lim", "Ravi Chandran", "Siti Zubaidah", "Daniel Wong", "Farah Adilah",
    "Kumaran Pillai", "Yee Wen Chong", "Amirul Hakim", "Priya Naidu", "Chin Hock Lee",
    "Norhayati Salleh", "Vikram Menon", "Aisyah Karim", "Jason Teoh", "Rosnah Ibrahim",
)
_OFFICERS = (
    "Inspektor Kamal", "Pegawai Suhaimi", "Inspektor Faridah", "Pegawai Lim",
    "Inspektor Devan", "Pegawai Nadia", "Inspektor Roslan", "Pegawai Chong",
    "Inspector Kamal", "Officer Suhaimi",
)
_AMOUNTS = ("RM 8,500", "RM 12,000", "RM 25,400", "RM 6,200", "RM 47,000")


def _base_variants() -> list[dict[str, Any]]:
    """20 base variants: same MO, mostly rotated identifiers.

    Composition is a *design decision about the threat*, not about the score:
      - 6 still touch one watchlist identifier (attackers reuse mule accounts);
      - 12 rotate every identifier but keep the signature phrase;
      - 2 rotate everything *and* drop the phrase — the leading edge of decay.
    """
    profile = campaign_profile()
    watch_account = WATCHLIST_RAW[0][1]
    watch_phone = WATCHLIST_RAW[1][1]
    watch_url = WATCHLIST_RAW[2][1]
    cases: list[dict[str, Any]] = []

    for i in range(20):
        victim = _VICTIMS[i]
        officer = _OFFICERS[i % len(_OFFICERS)]
        amount = _AMOUNTS[i % len(_AMOUNTS)]
        account = _account(200 + i)
        phone = _phone(200 + i)
        url = f"https://{_domain(f'akaun-semak-{i:02d}')}/pengesahan"
        note = "identifiers fully rotated; signature phrase retained"
        phrase: str | None = SIGNATURE_PHRASES[0]

        if i < 2:
            account = watch_account
            note = "reuses the watchlist mule account"
        elif i < 4:
            phone = watch_phone
            note = "reuses the watchlist callback number"
        elif i < 6:
            url = watch_url
            note = "reuses the watchlist portal domain"
        elif i in (16, 17):
            phrase = "Akaun  Selamat   Sementara"
            note = "signature phrase re-cased and re-spaced"
        elif i >= 18:
            phrase = "akaun penampan sementara"
            note = "identifiers rotated and signature phrase replaced by a synonym"

        transcript = _wave_script_ms(
            officer=officer,
            victim=victim.split()[0],
            account=account,
            phone=phone,
            url=url,
            amount=amount,
            phrase=phrase,
        )
        cases.append(
            {
                "case_id": f"scam027_variant_{i + 1:03d}",
                "category": "base",
                "is_scam": True,
                "campaign": CAMPAIGN_CODE,
                "variant_note": note,
                "created_at": _ts(i * 0.25),
                "transcript": transcript,
                "expected_mo": profile["mo"],
                "expected_entities": normalised_entities(transcript),
            }
        )
    return cases


def _redteam_mutations() -> list[dict[str, Any]]:
    """10 adversarial mutations of the same underlying MO."""
    profile = campaign_profile()
    specs: list[tuple[str, str, dict[str, Any]]] = [
        (
            "redteam_phase_reorder",
            "money ask first, isolation later, phrase broken up",
            {"reorder": True, "phrase": "akaun sementara yang selamat"},
        ),
        (
            "redteam_synonym_sub",
            "signature phrase replaced with a synonym",
            {"phrase": "akaun penampan sementara"},
        ),
        (
            "redteam_lang_switch",
            "entire script switched to English, Malay signature phrase gone with it",
            # No phrase override: a script fully translated into English cannot
            # still carry the Malay signature phrase. Leaving the Malay phrase in
            # an English call would make this case detectable by the phrase gate
            # for a reason the mutation is explicitly meant to remove.
            {"lang": "en", "phrase": None},
        ),
        (
            "redteam_no_novel_phrase",
            "no named account product at all, transfer described plainly",
            {"phrase": None},
        ),
        (
            "redteam_extra_phase",
            "extra legitimacy phase prepended, phrase retained",
            {"extra_legitimacy_phase": True},
        ),
        (
            "redteam_identifier_obfuscation",
            "watchlist account digits re-spaced to defeat literal matching",
            {"account": "1592 3456 7890 1234", "phrase": None},
        ),
        (
            "redteam_partial_phrase",
            "only the first half of the signature phrase survives",
            {"phrase": "akaun selamat"},
        ),
        (
            "redteam_code_switch",
            "Malay frame with the key phrase code-switched to English",
            {"lang": "en", "phrase": "a temporary safe account"},
        ),
        (
            "redteam_soft_pressure",
            "no isolation instruction, polite tone, phrase dropped",
            {"phrase": None, "isolation": False, "evasion": False},
        ),
        (
            "redteam_callback_recon",
            "reconnaissance only: no money ask, no isolation, no phrase",
            {"phrase": None, "money_ask": False, "isolation": False, "evasion": False},
        ),
    ]

    cases: list[dict[str, Any]] = []
    for i, (case_id, note, opts) in enumerate(specs):
        victim = _VICTIMS[i].split()[0]
        officer = _OFFICERS[i % len(_OFFICERS)]
        amount = _AMOUNTS[i % len(_AMOUNTS)]
        account = opts.get("account") or _account(400 + i)
        phone = _phone(400 + i)
        url = f"https://{_domain(f'semakan-rasmi-{i:02d}')}/portal"
        phrase = opts.get("phrase", SIGNATURE_PHRASES[0])

        if opts.get("lang") == "en":
            transcript = _wave_script_en(
                officer=officer,
                victim=victim,
                account=account,
                phone=phone,
                url=url,
                amount=amount,
                phrase=phrase,
            )
        else:
            transcript = _wave_script_ms(
                officer=officer,
                victim=victim,
                account=account,
                phone=phone,
                url=url,
                amount=amount,
                phrase=phrase,
                isolation=bool(opts.get("isolation", True)),
                money_ask=bool(opts.get("money_ask", True)),
                evasion=bool(opts.get("evasion", True)),
                extra_legitimacy_phase=bool(opts.get("extra_legitimacy_phase", False)),
                reorder=bool(opts.get("reorder", False)),
            )

        cases.append(
            {
                "case_id": case_id,
                "category": "redteam",
                "is_scam": True,
                "campaign": CAMPAIGN_CODE,
                "variant_note": note,
                "created_at": _ts(6 + i * 0.25),
                "transcript": transcript,
                "expected_mo": profile["mo"],
                "expected_entities": normalised_entities(transcript),
            }
        )
    return cases


def _negative_controls() -> list[dict[str, Any]]:
    """10 negatives: 6 legitimate calls plus 4 other scam families.

    The legitimate controls are the ones that make the false-positive rate mean
    anything: they mention banks, accounts, money and authority, exactly like the
    campaign does, and differ only in the structure of the request.
    """
    specs: list[tuple[str, str, bool, list[dict[str, Any]]]] = [
        (
            "legit_bank_fraud_callback",
            "genuine bank fraud-ops callback about a blocked card",
            False,
            _legit_bank_callback("Zulkifli", "RM 3,200", _phone(701)),
        ),
        (
            "legit_otp_awareness",
            "genuine bank security-awareness call, asks for nothing",
            False,
            _legit_otp_reminder("Mei Ling"),
        ),
        (
            "legit_courier_redelivery",
            "genuine courier redelivery, prepaid parcel",
            False,
            _legit_courier("Arun"),
        ),
        (
            "legit_insurance_renewal",
            "genuine insurance renewal, payment via official app only",
            False,
            _legit_insurance("Nurul", "RM 1,180"),
        ),
        (
            "legit_telco_billing",
            "genuine telco plan downgrade offer",
            False,
            _legit_telco("Hafiz", "RM 98"),
        ),
        (
            "legit_govt_survey",
            "genuine statistics-department household survey",
            False,
            _legit_govt_survey("Grace"),
        ),
        (
            "noise_phishing_001",
            "different scam family: e-wallet cashback phishing",
            True,
            _noise_phishing("Ravi", f"https://{_domain('ewallet-hadiah')}/tuntut"),
        ),
        (
            "noise_investment_001",
            "different scam family: unlicensed investment deposit",
            True,
            _noise_investment("Siti", _account(801), "RM 15,000"),
        ),
        (
            "noise_romance_001",
            "different scam family: romance advance-fee",
            True,
            _noise_romance("Daniel", _account(802), "RM 9,400"),
        ),
        (
            "noise_job_offer_001",
            "different scam family: task-based job deposit",
            True,
            _noise_job_offer("Farah", _account(803), "RM 2,300"),
        ),
    ]

    cases: list[dict[str, Any]] = []
    for i, (case_id, note, is_other_scam, transcript) in enumerate(specs):
        cases.append(
            {
                "case_id": case_id,
                "category": "noise",
                # `is_scam` here means "is a SCAM-027 case". Other scam families
                # are still negatives for this campaign's detector.
                "is_scam": False,
                "other_scam_family": is_other_scam,
                "campaign": None,
                "variant_note": note,
                "created_at": _ts(9 + i * 0.5),
                "transcript": transcript,
                "expected_mo": None,
                "expected_entities": normalised_entities(transcript),
            }
        )
    return cases


def build_eval_corpus() -> dict[str, list[dict[str, Any]]]:
    """Build the full 40-case evaluation corpus.

    Returns:
        Dict with keys ``base``, ``redteam``, ``noise``.
    """
    return {
        "base": _base_variants(),
        "redteam": _redteam_mutations(),
        "noise": _negative_controls(),
    }


def build_eval_ground_truth(corpus: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Build ground truth for the eval corpus.

    Ground truth records **reality** (is this really a SCAM-027 case), never the
    behaviour a particular defence version is expected to exhibit. The
    ``baseline_expected_misses`` field is informational only and is not used by
    any metric.

    Args:
        corpus: Output of :func:`build_eval_corpus`.

    Returns:
        Ground-truth dict consumed by :mod:`src.enterprise.evaluation`.
    """
    base_ids = [c["case_id"] for c in corpus["base"]]
    redteam_ids = [c["case_id"] for c in corpus["redteam"]]
    noise_ids = [c["case_id"] for c in corpus["noise"]]
    return {
        "campaign": CAMPAIGN_CODE,
        "base_variants": {"expected_detected": base_ids, "expected_fp": []},
        "redteam_mutations": {
            "expected_detected": redteam_ids,
            # Every red-team case is a real scam, so none of them is a
            # negative control: expected_fp is empty by construction, and is
            # stated rather than implied so each block carries both labels.
            "expected_fp": [],
            "expected_missed": [],
            "baseline_expected_misses": [
                cid
                for cid in redteam_ids
                if cid
                not in {"redteam_extra_phase", "redteam_identifier_obfuscation"}
            ],
        },
        "noise": {"expected_detected": [], "expected_fp": noise_ids},
        "entities": {
            c["case_id"]: c["expected_entities"]
            for group in corpus.values()
            for c in group
        },
    }


# ── Demo seed wave ──────────────────────────────────────────────────────────
_SEED_NAMESPACE = "https://transafe.example/v2/seed"


def seed_case_id(slug: str) -> str:
    """Return the deterministic UUID for a seeded demo case."""
    return str(uuid5(NAMESPACE_URL, f"{_SEED_NAMESPACE}/case/{slug}"))


def seed_user_id(slug: str) -> str:
    """Return the deterministic UUID for a seeded demo customer."""
    return str(uuid5(NAMESPACE_URL, f"{_SEED_NAMESPACE}/user/{slug}"))


def build_seed_transcripts() -> list[dict[str, Any]]:
    """Build the 10 demo seed cases: a 6-case SCAM-027 wave plus 4 that must not link.

    The wave's identifier topology is deliberate. Every wave case shares at least
    one *hard* identifier (PHONE or ACCOUNT, weight 0.95) with another wave case,
    so the six form a single connected component with strong edges:

        w1 ─A1─ w2 ─A1─ w3 ─P1─ w4 ─A2─ w5 ─P3─ w6

    The four noise cases share no identifier with anything, and are spaced more
    than 72 hours apart so they cannot pick up the temporal multiplier either.
    ``tests/unit/test_seed_corpus.py`` proves both claims against the real
    linkage and clustering code rather than trusting this docstring.

    Returns:
        List of seed case dicts.
    """
    watch_account = WATCHLIST_RAW[0][1]
    watch_phone = WATCHLIST_RAW[1][1]
    watch_url = WATCHLIST_RAW[2][1]
    second_account = "2274-9081-3355-4460"
    third_account = "3390-5512-7788-1102"
    second_phone = "013-8842 5566"
    third_phone = "017-2290 3348"

    wave_specs: list[tuple[str, dict[str, Any]]] = [
        (
            "wave-01",
            {
                "victim": "Zulkifli",
                "officer": "Inspektor Kamal",
                "account": watch_account,
                "phone": watch_phone,
                "url": watch_url,
                "amount": "RM 18,500",
                "day": 0.0,
            },
        ),
        (
            "wave-02",
            {
                "victim": "Mei Ling",
                "officer": "Pegawai Suhaimi",
                "account": watch_account,
                "phone": second_phone,
                "url": watch_url,
                "amount": "RM 24,000",
                "day": 1.2,
            },
        ),
        (
            "wave-03",
            {
                "victim": "Arun",
                "officer": "Inspektor Faridah",
                "account": watch_account,
                "phone": watch_phone,
                "url": watch_url,
                "amount": "RM 9,750",
                "day": 2.4,
            },
        ),
        (
            "wave-04",
            {
                "victim": "Nurul",
                "officer": "Pegawai Lim",
                "account": second_account,
                "phone": watch_phone,
                "url": watch_url,
                "amount": "RM 31,200",
                "day": 3.6,
            },
        ),
        (
            "wave-05",
            {
                "victim": "Hafiz",
                "officer": "Inspektor Devan",
                "account": second_account,
                "phone": third_phone,
                "url": watch_url,
                "amount": "RM 12,900",
                "day": 4.8,
            },
        ),
        (
            "wave-06",
            {
                "victim": "Grace",
                "officer": "Pegawai Nadia",
                "account": third_account,
                "phone": third_phone,
                "url": watch_url,
                "amount": "RM 45,000",
                "day": 6.0,
            },
        ),
    ]

    cases: list[dict[str, Any]] = []
    for idx, (slug, spec) in enumerate(wave_specs):
        transcript = _wave_script_ms(
            officer=str(spec["officer"]),
            victim=str(spec["victim"]),
            account=str(spec["account"]),
            phone=str(spec["phone"]),
            url=str(spec["url"]),
            amount=str(spec["amount"]),
            phrase=SIGNATURE_PHRASES[0],
        )
        cases.append(
            {
                "slug": slug,
                "case_id": seed_case_id(slug),
                "case_number": 40 + idx,
                "user_id": seed_user_id(slug),
                "customer_name": f"{spec['victim']} (FICTIONAL)",
                "kind": "wave",
                "campaign": CAMPAIGN_CODE,
                "created_at": _ts(float(spec["day"])),
                "channel": "voice",
                "risk_score": 92,
                "transcript": transcript,
                "mo_fingerprint": derive_mo(transcript),
                "entities": normalised_entities(transcript),
            }
        )

    noise_specs: list[tuple[str, str, str, float, list[dict[str, Any]]]] = [
        (
            "noise-01",
            "Ravi",
            "phishing",
            0.5,
            _noise_phishing("Ravi", f"https://{_domain('ewallet-hadiah')}/tuntut"),
        ),
        (
            "noise-02",
            "Siti",
            "investment",
            4.0,
            _noise_investment("Siti", "5561-2093-8842-7710", "RM 15,000"),
        ),
        (
            "noise-03",
            "Daniel",
            "romance",
            7.5,
            _noise_romance("Daniel", "6672-4417-9903-2286", "RM 9,400"),
        ),
        (
            "noise-04",
            "Farah",
            "job_offer",
            11.0,
            _noise_job_offer("Farah", "7783-6628-1194-5537", "RM 2,300"),
        ),
    ]

    for idx, (slug, victim, family, day, transcript) in enumerate(noise_specs):
        cases.append(
            {
                "slug": slug,
                "case_id": seed_case_id(slug),
                "case_number": 46 + idx,
                "user_id": seed_user_id(slug),
                "customer_name": f"{victim} (FICTIONAL)",
                "kind": "noise",
                "campaign": None,
                "scam_family": family,
                "created_at": _ts(day),
                "channel": "voice",
                "risk_score": 61,
                "transcript": transcript,
                "mo_fingerprint": derive_mo(transcript),
                "entities": normalised_entities(transcript),
            }
        )

    return cases


def build_seed_ground_truth(seed_cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Build ``ground_truth/expected_results.json`` for the demo seed wave.

    Args:
        seed_cases: Output of :func:`build_seed_transcripts`.

    Returns:
        Ground-truth dict with expected MO, normalised entities and campaign
        assignment per case.
    """
    profile = campaign_profile()
    cases: dict[str, Any] = {}
    for case in seed_cases:
        cases[case["slug"]] = {
            "case_id": case["case_id"],
            "expected_campaign": case["campaign"],
            "expected_mo": profile["mo"] if case["kind"] == "wave" else None,
            "expected_entities": case["entities"],
            "expected_to_link": case["kind"] == "wave",
        }
    wave = [c["case_id"] for c in seed_cases if c["kind"] == "wave"]
    return {
        "campaign": {
            "code": CAMPAIGN_CODE,
            "name": CAMPAIGN_NAME,
            "expected_member_case_ids": wave,
            "expected_case_count": len(wave),
            "expected_distinct_customers": len(
                {c["user_id"] for c in seed_cases if c["kind"] == "wave"}
            ),
            "promotion_gates": {
                "min_cases": 3,
                "min_distinct_customers": 2,
                "min_strong_edge": 0.80,
                "max_span_days": 14,
                "novelty_max_cosine": 0.90,
            },
            "signature_phrases": list(SIGNATURE_PHRASES),
            "watchlist": profile["watchlist"],
        },
        "cases": cases,
        "expected_singletons": [c["slug"] for c in seed_cases if c["kind"] == "noise"],
    }


# ── Replay sequence ─────────────────────────────────────────────────────────
#: Stable UUID so the recorded sequence, the ``/enterprise/demo/replay``
#: endpoint and any rows written to ``ns_events`` all agree on one run.
REPLAY_RUN_ID = str(uuid5(NAMESPACE_URL, f"{_SEED_NAMESPACE}/replay/scam-027-v1"))
REPLAY_EPOCH = "2026-09-10T12:04:11Z"


def build_replay_sequence() -> list[dict[str, Any]]:
    """Build the curated 5-act nervous-system replay.

    Emitted in the live ``ns_events`` schema — ``{id, ts, layer, event_type,
    severity, payload, run_id}`` — so the console cannot tell a replayed event
    from a live one, and so a replay can be persisted to ``ns_events`` as-is
    (``run_id`` is a real UUID, which the column requires).

    Returns:
        List of event dicts, ordered by ``ts``.
    """
    base = datetime.fromisoformat(REPLAY_EPOCH.replace("Z", "+00:00"))
    events: list[dict[str, Any]] = []

    def add(
        offset: float,
        layer: str,
        event_type: str,
        severity: str,
        payload: dict[str, Any],
    ) -> None:
        # Fixed millisecond precision: sub-second offsets mean a bare-second
        # timestamp ("…:12Z") would sort *after* a fractional one ("…:12.6Z")
        # under string comparison, which is how consumers order these events.
        stamp = (base + timedelta(seconds=offset)).isoformat(timespec="milliseconds")
        events.append(
            {
                "id": len(events) + 1,
                "ts": stamp.replace("+00:00", "Z"),
                "layer": layer,
                "event_type": event_type,
                "severity": severity,
                "payload": {"act": _ACT_OF[event_type], **payload},
                "run_id": REPLAY_RUN_ID,
            }
        )

    seeds = build_seed_transcripts()
    wave = [c for c in seeds if c["kind"] == "wave"]

    # ── Act I — sensing: three calls land. ──────────────────────────────────
    for i, case in enumerate(wave[:3]):
        add(
            0.4 + i * 1.2,
            "case",
            "case_ingested",
            "info",
            {
                "case_id": case["case_id"],
                "case_number": case["case_number"],
                "channel": "voice",
            },
        )
        add(
            0.8 + i * 1.2,
            "case",
            "mo_extracted",
            "info",
            {
                "case_id": case["case_id"],
                "impersonated_entity": IMPERSONATED_ENTITY,
                "script_phases": case["mo_fingerprint"]["script_phases"],
            },
        )
        account = next(
            (e for e in case["entities"] if e["entity_type"] == "ACCOUNT"),
            {"value_norm": ""},
        )
        add(
            1.0 + i * 1.2,
            "case",
            "entity_linked",
            "info",
            {
                "case_id": case["case_id"],
                "entity_type": "ACCOUNT",
                "value_norm": account["value_norm"],
            },
        )

    # ── Act II — discovery: links form, a cluster promotes. ─────────────────
    add(
        4.6,
        "discovery",
        "case_observed",
        "info",
        {"case_id": wave[2]["case_id"], "candidates": 4},
    )
    add(
        5.1,
        "discovery",
        "cases_linked",
        "info",
        {
            "case_a": wave[0]["case_id"],
            "case_b": wave[1]["case_id"],
            "score": 0.95,
            "signal": "shared_identifier",
        },
    )
    add(
        5.6,
        "discovery",
        "cases_linked",
        "info",
        {
            "case_a": wave[2]["case_id"],
            "case_b": wave[3]["case_id"],
            "score": 0.95,
            "signal": "shared_identifier",
        },
    )
    add(
        6.2,
        "discovery",
        "cases_linked",
        "warning",
        {
            "case_a": wave[4]["case_id"],
            "case_b": wave[5]["case_id"],
            "score": 0.95,
            "signal": "shared_identifier",
        },
    )
    add(
        6.9,
        "discovery",
        "campaign_proposed",
        "critical",
        {
            "campaign_code": CAMPAIGN_CODE,
            "case_count": len(wave),
            "distinct_customers": len({c["user_id"] for c in wave}),
            "confidence": 0.91,
            "novel": True,
        },
    )

    # ── Act III — validation: a human approves. ─────────────────────────────
    add(
        11.0,
        "discovery",
        "campaign_approved",
        "info",
        {"campaign_code": CAMPAIGN_CODE, "approved_by": "fraud_ops_analyst"},
    )

    # ── Act IV — compile, publish, propagate. ───────────────────────────────
    add(
        12.0,
        "compiler",
        "compilation_completed",
        "info",
        {"campaign_code": CAMPAIGN_CODE, "artifacts": 3, "tier": "pack"},
    )
    add(
        12.6,
        "compiler",
        "core_patch_proposed",
        "warning",
        {
            "rule_id": "R-CORE-014",
            "source_campaigns": ["SCAM-019", "SCAM-024", CAMPAIGN_CODE],
            "confidence": 0.86,
        },
    )
    add(
        13.2,
        "registry",
        "artifact_published",
        "info",
        {"name": f"{CAMPAIGN_CODE}.json", "tier": "pack", "version": 1},
    )
    add(
        13.8,
        "registry",
        "core_artifact_published",
        "info",
        {"name": "phone_agent_core", "tier": "core", "from_version": 6, "version": 7},
    )
    for i, agent in enumerate(("phone_agent", "fraud_ops", "phishing_agent", "txn_monitor")):
        add(
            14.3 + i * 0.2,
            "propagation",
            "propagation_acknowledged",
            "info",
            {
                # `agent` for the console, `agent_name` to match the live
                # propagation payload. Superset, so both readers work.
                "agent": agent,
                "agent_name": agent,
                "artifact_name": "phone_agent_core",
                "version": 7,
            },
        )

    # ── Act V — proof: exposure and the eval verdict. ───────────────────────
    add(
        17.0,
        "exposure",
        "mcp_call",
        "info",
        {"caller": "codebuddy", "tool": "ask_transafe", "role": "legal", "latency_ms": 340},
    )
    add(
        18.5,
        "registry",
        "eval_completed",
        "info",
        {
            "label": "replay: post-adaptation",
            "note": "numbers rendered by the console come from a live eval run, not this replay",
        },
    )
    return events


_ACT_OF: dict[str, str] = {
    "case_ingested": "I_sensing",
    "mo_extracted": "I_sensing",
    "entity_linked": "I_sensing",
    "case_observed": "II_discovery",
    "cases_linked": "II_discovery",
    "campaign_proposed": "II_discovery",
    "campaign_approved": "III_validation",
    "compilation_completed": "IV_compile",
    "core_patch_proposed": "IV_compile",
    "artifact_published": "IV_compile",
    "core_artifact_published": "IV_compile",
    "propagation_acknowledged": "IV_compile",
    "mcp_call": "V_proof",
    "eval_completed": "V_proof",
}


# ── Loading ─────────────────────────────────────────────────────────────────
def load_eval_corpus(corpus_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """Load the 40-case eval corpus from disk, falling back to generation.

    Args:
        corpus_dir: Directory containing ``base/``, ``redteam/``, ``noise/``.
            Defaults to ``backend/seeds/eval``.

    Returns:
        Flat list of case dicts, each carrying its ``category``.
    """
    root = Path(corpus_dir) if corpus_dir else EVAL_DIR
    cases: list[dict[str, Any]] = []
    for category in ("base", "redteam", "noise"):
        folder = root / category
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            data.setdefault("category", category)
            cases.append(data)
    if cases:
        return cases
    built = build_eval_corpus()
    return built["base"] + built["redteam"] + built["noise"]


def load_eval_ground_truth(corpus_dir: Path | str | None = None) -> dict[str, Any]:
    """Load eval ground truth from disk, falling back to generation.

    The fallback is legitimate but must never be silent: generated truth and
    on-disk truth are different claims, and a corrupt seed that quietly becomes
    generated data makes the eval look healthy while measuring something else.
    """
    root = Path(corpus_dir) if corpus_dir else EVAL_DIR
    path = root / "ground_truth" / "eval_truth.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "corpus: eval ground truth at %s is unreadable; generating instead", path
            )
    else:
        logger.warning("corpus: no eval ground truth at %s; generating instead", path)
    return build_eval_ground_truth(build_eval_corpus())


def load_seed_transcripts(seeds_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """Load the demo seed cases from disk, falling back to generation."""
    root = Path(seeds_dir) if seeds_dir else TRANSCRIPTS_DIR
    cases: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.glob("*.json")):
            try:
                cases.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                logger.warning("corpus: seed transcript %s is unreadable; skipping", path)
                continue
    if not cases:
        logger.warning("corpus: no seed transcripts under %s; generating instead", root)
    return cases or build_seed_transcripts()


def load_replay_sequence(seeds_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """Load the recorded replay sequence from disk, falling back to generation."""
    root = Path(seeds_dir) if seeds_dir else NS_EVENTS_DIR
    path = root / "replay_sequence.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
            logger.warning("corpus: replay sequence at %s is empty or malformed", path)
        except (OSError, json.JSONDecodeError):
            logger.warning("corpus: replay sequence at %s is unreadable", path)
    else:
        logger.warning("corpus: no replay sequence at %s; generating instead", path)
    return build_replay_sequence()


# ── Writing ─────────────────────────────────────────────────────────────────
def _write_json(path: Path, payload: Any) -> None:
    """Write ``payload`` as pretty JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_all(seeds_dir: Path | str | None = None) -> dict[str, int]:
    """Materialise every corpus artifact under ``backend/seeds/``.

    Idempotent: regenerating produces byte-identical files, which is what keeps
    ``ns_events/replay_sequence.json`` and ``GET /enterprise/demo/replay`` in
    agreement.

    Args:
        seeds_dir: Root seeds directory. Defaults to ``backend/seeds``.

    Returns:
        Dict of counts per artifact group.
    """
    root = Path(seeds_dir) if seeds_dir else SEEDS_DIR

    corpus = build_eval_corpus()
    for category, cases in corpus.items():
        for case in cases:
            _write_json(root / "eval" / category / f"{case['case_id']}.json", case)
    _write_json(
        root / "eval" / "ground_truth" / "eval_truth.json",
        build_eval_ground_truth(corpus),
    )
    _write_json(
        root / "eval" / "README.json",
        {
            "campaign": CAMPAIGN_CODE,
            "counts": {k: len(v) for k, v in corpus.items()},
            "all_data_fictional": True,
            "generated_by": "src.enterprise.corpus.write_all",
        },
    )

    seeds = build_seed_transcripts()
    for case in seeds:
        _write_json(root / "transcripts" / f"{case['slug']}.json", case)
    _write_json(root / "ground_truth" / "expected_results.json", build_seed_ground_truth(seeds))
    _write_json(root / "ns_events" / "replay_sequence.json", build_replay_sequence())

    return {
        "eval_base": len(corpus["base"]),
        "eval_redteam": len(corpus["redteam"]),
        "eval_noise": len(corpus["noise"]),
        "seed_transcripts": len(seeds),
        "replay_events": len(build_replay_sequence()),
    }


if __name__ == "__main__":  # pragma: no cover - developer entry point
    print(json.dumps(write_all(), indent=2))
