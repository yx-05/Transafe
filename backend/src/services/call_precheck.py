"""Phone call pre-check helpers: real blacklist lookup + spoofed-prefix detection.

Used by both the call trigger endpoint and the call events WebSocket so the
pre-check logic stays consistent in one place. Mirrors the documented design in
doc/03_agent_flow.md / doc/systemflow.md (section 5.3).
"""

import logging
import re

from src.db.vector_store import check_blacklist

logger = logging.getLogger(__name__)

# Demo numbers always treated as blacklisted (deterministic demo behaviour + tests)
DEMO_BLACKLIST_NUMBERS = [
    "+60161234567",
    "0161234567",
    "+60197654321",
]

# Known spoofed bank hotline prefixes (documented in doc/systemflow.md 5.3)
SPOOFED_PREFIXES = ["1300", "1800", "032612", "032170"]


def normalize_phone(number: str) -> str:
    """Normalize a phone number: strip spaces, dashes, parens, and a leading +."""
    if not number:
        return ""
    return re.sub(r"[\s\-()]", "", str(number)).lstrip("+")


def is_spoofed_prefix(number: str) -> bool:
    """Detect whether a caller number uses a known spoofed bank hotline prefix."""
    norm = normalize_phone(number)
    if not norm:
        return False
    return any(norm.startswith(prefix) for prefix in SPOOFED_PREFIXES)


def run_call_precheck(number: str) -> dict[str, object]:
    """Run the full call pre-check for a caller number.

    Returns a dict with:
        blacklisted (bool), blacklist_cases (int), spoofed_prefix (bool),
        initial_risk (str), warning (str | None), warning_ms (str | None).
    """
    blacklisted = number in DEMO_BLACKLIST_NUMBERS
    blacklist_cases = 2 if blacklisted else 0

    try:
        hits = check_blacklist(phone=number) or []
        if hits:
            blacklisted = True
            blacklist_cases = max(blacklist_cases, len(hits))
    except Exception as err:  # noqa: BLE001
        logger.warning(f"Call pre-check blacklist lookup failed: {err}")

    spoofed = is_spoofed_prefix(number)
    initial_risk = "HIGH" if (blacklisted or spoofed) else "LOW"

    if blacklisted:
        warning = (
            f"This number has been reported {blacklist_cases} time(s) for "
            "impersonation scams."
        )
        warning_ms = (
            f"Nombor ini telah dilaporkan {blacklist_cases} kali untuk "
            "penipuan penyamaran."
        )
    elif spoofed:
        warning = "This number uses a spoofed bank hotline prefix."
        warning_ms = "Nombor ini menggunakan awalan hotline bank yang dipalsukan."
    else:
        warning = None
        warning_ms = None

    return {
        "blacklisted": blacklisted,
        "blacklist_cases": blacklist_cases,
        "spoofed_prefix": spoofed,
        "initial_risk": initial_risk,
        "warning": warning,
        "warning_ms": warning_ms,
    }
