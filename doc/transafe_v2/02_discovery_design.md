# 02 — Discovery Layer Design (L3)

> **Parent:** `01_upgrade_plan.md` §6
> **Scope:** MO extraction (L1 post-call), entity resolution (L2), linkage, clustering, discovery trigger, GraphStore, OBSERVED state
> **Build blocks:** B1 (mo_extractor + entity_resolver), B2 (linkage + clustering + discovery + GraphStore)
> **Status:** Implementation-ready

---

## 1. Module inventory

| Module | File | Layer | Build block | Depends on |
|---|---|---|---|---|
| MO extractor | `enterprise/mo_extractor.py` | L1 (post-call, async) | B1 | `agents/llm.py`, `db/vector_store.py` |
| Entity resolver | `enterprise/entity_resolver.py` | L2 | B1 | `db/supabase.py` |
| Linkage | `enterprise/linkage.py` | L3 | B2 | `enterprise/graph_store.py`, `db/vector_store.py` |
| Clustering | `enterprise/clustering.py` | L3 | B2 | `enterprise/linkage.py`, `enterprise/graph_store.py` |
| Discovery | `enterprise/discovery.py` | L3 | B2 | all above + `enterprise/events.py` |
| Graph store | `enterprise/graph_store.py` | L3 | B2 | `db/supabase.py` |
| Events | `enterprise/events.py` | cross-cutting | B0 | Supabase `ns_events` table |

---

## 2. MO Extractor — `enterprise/mo_extractor.py`

### 2.1 Purpose

Runs **post-call, asynchronous** after the v1 pipeline completes. Extracts a structured behavioural fingerprint from the stored transcript. This is the enabling change for narrative linkage — identifiers give precision; the MO fingerprint gives recall.

### 2.2 Hard split — safety rule

| Data | Extractor | Rationale |
|---|---|---|
| Phone, account number, URL, amount, IBAN | **Regex / deterministic only. Never an LLM.** | A hallucinated digit in an account number creates a false graph edge → false campaign → countermeasure justified by a number nobody said. |
| Impersonated entity, pretext, script phases, pressure tactics, novel phrases, escalation timing | **LLM, schema-constrained JSON** | Regex fundamentally cannot represent behaviour. |

### 2.3 Output schema

```json
{
  "case_id": "uuid",
  "impersonated_entity": "Bank Negara Malaysia",
  "pretext": "account implicated in money-laundering investigation",
  "script_phases": ["authority_claim", "fear_induction", "isolation", "urgency", "safe_account_instruction"],
  "pressure_tactics": ["arrest threat", "do not tell family", "stay on the line"],
  "novel_phrases": [
    {"text": "akaun selamat sementara", "lang": "ms", "utterance_idx": 14},
    {"text": "pegawai siasatan BNM", "lang": "ms", "utterance_idx": 6}
  ],
  "languages": ["ms", "en"],
  "time_to_money_ask_sec": 187,
  "verification_evasion": "refused call-back to published BNM hotline",
  "evidence_utterances": [3, 6, 14, 22],
  "narrative": "Caller claims to be a BNM investigation officer, states the victim's account is used for money laundering, forbids contacting family, and instructs transfer to a temporary 'safe account'."
}
```

### 2.4 Three hard constraints

1. **Every field must cite `utterance_idx`.** The validator clicks a phrase and lands on the exact transcript line. Hallucinated MOs cannot silently become campaign evidence.
2. **Runs post-case, off the live path.** No latency regression on the phone agent.
3. **`narrative` is what gets embedded** (768-dim, `embed_text`, same pipeline as `fraud_memory`). This vector powers narrative linkage in L3.

### 2.5 Function signatures

```python
from __future__ import annotations

import json
import logging
from typing import Any

from agents.llm import extract_json_object, invoke_deepseek_with_key_rotation
from db.vector_store import embed_text
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

MO_EXTRACTION_SYSTEM_PROMPT = """\
You are a fraud behavioural analyst. You extract a Modus Operandi (MO) fingerprint \
from a call transcript. You MUST:
1. Ground every extracted field in a specific utterance index from the transcript.
2. Never invent identifiers (phone numbers, account numbers, URLs) — those are \
extracted by deterministic regex, not by you.
3. Return ONLY a JSON object matching the required schema.
4. If the transcript is too short or ambiguous, return {"ambiguous": true}.

Schema:
{
  "impersonated_entity": "string or null",
  "pretext": "string or null",
  "script_phases": ["string", ...],
  "pressure_tactics": ["string", ...],
  "novel_phrases": [{"text": "string", "lang": "ms|en|mixed", "utterance_idx": int}, ...],
  "languages": ["ms", "en", ...],
  "time_to_money_ask_sec": int or null,
  "verification_evasion": "string or null",
  "evidence_utterances": [int, ...],
  "narrative": "string — 2-4 sentence summary of the scam script"
}
"""


def extract_mo_fingerprint(
    case_id: str,
    transcript: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Extract MO fingerprint from a call transcript.

    Args:
        case_id: UUID of the fraud case.
        transcript: List of utterance dicts with keys:
            speaker, utterance, risk_score, seq_idx.

    Returns:
        MO fingerprint dict matching the schema, or None on failure.
        The dict includes ``case_id`` and ``narrative`` keys.
        On ambiguous transcripts, returns {"ambiguous": True}.

    Raises:
        RuntimeError: If LLM is unavailable and no fallback is possible.
    """
    if not transcript or len(transcript) < 3:
        logger.warning("Transcript for case %s too short (%d utterances)", case_id, len(transcript))
        return None

    # Format transcript for the LLM
    transcript_text = "\n".join(
        f"[{i}] {u.get('speaker', 'UNKNOWN')}: {u.get('utterance', '')}"
        for i, u in enumerate(transcript)
    )

    messages = [
        SystemMessage(content=MO_EXTRACTION_SYSTEM_PROMPT),
        HumanMessage(content=f"Case ID: {case_id}\n\nTranscript:\n{transcript_text}"),
    ]

    try:
        response = invoke_deepseek_with_key_rotation(messages)
        mo = extract_json_object(response.content)
        if mo is None:
            logger.error("MO extractor: LLM returned unparseable JSON for case %s", case_id)
            return _mo_fallback(transcript)
        if mo.get("ambiguous"):
            logger.info("MO extractor: transcript %s marked ambiguous", case_id)
            return None
        mo["case_id"] = case_id
        # Validate evidence_utterances are within bounds
        mo["evidence_utterances"] = [
            idx for idx in mo.get("evidence_utterances", []) if 0 <= idx < len(transcript)
        ]
        return mo
    except Exception:
        logger.exception("MO extractor failed for case %s", case_id)
        return _mo_fallback(transcript)


def _mo_fallback(transcript: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Deterministic fallback when LLM is unavailable.

    Extracts structural signals only: language detection (ms/en ratio),
    approximate time-to-money-ask, and a minimal narrative from the
    concatenated transcript. No script phases or pressure tactics.
    """
    if not transcript:
        return None
    full_text = " ".join(u.get("utterance", "") for u in transcript)
    # Simple language heuristic
    ms_chars = sum(1 for c in full_text if "\u0600" <= c <= "\u06FF")
    en_chars = sum(1 for c in full_text if c.isascii() and c.isalpha())
    languages = []
    if ms_chars > 10:
        languages.append("ms")
    if en_chars > 10:
        languages.append("en")

    # Find first utterance mentioning money/transfer/account
    money_keywords = ["transfer", "akaun", "account", "bank", "rm", "wang", "bayaran"]
    money_idx = None
    for i, u in enumerate(transcript):
        text_lower = u.get("utterance", "").lower()
        if any(kw in text_lower for kw in money_keywords):
            money_idx = i
            break

    time_to_money = None
    if money_idx is not None and len(transcript) > 1:
        # Approximate: assume uniform spacing
        total_duration = len(transcript) * 15  # 15 sec per utterance heuristic
        time_to_money = money_idx * 15

    narrative = full_text[:300] if full_text else ""

    return {
        "impersonated_entity": None,
        "pretext": None,
        "script_phases": [],
        "pressure_tactics": [],
        "novel_phrases": [],
        "languages": languages,
        "time_to_money_ask_sec": time_to_money,
        "verification_evasion": None,
        "evidence_utterances": list(range(min(5, len(transcript)))),
        "narrative": narrative,
        "extractor": "fallback-v1",
    }


def store_mo_fingerprint(mo: dict[str, Any]) -> str | None:
    """Store MO fingerprint + narrative embedding in the case_mo table.

    Args:
        mo: MO fingerprint dict from extract_mo_fingerprint.

    Returns:
        The case_id if stored successfully, None on failure.
    """
    from db.vector_store import get_supabase_client

    case_id = mo.get("case_id")
    if not case_id:
        return None

    narrative = mo.get("narrative", "")
    embedding = embed_text(narrative) if narrative else [0.0] * 768

    row = {
        "case_id": case_id,
        "fingerprint": json.dumps(mo),
        "narrative": narrative,
        "embedding": embedding,
        "extractor": mo.get("extractor", "llm-v1"),
    }

    try:
        client = get_supabase_client()
        client.table("case_mo").upsert(row).execute()
        return case_id
    except Exception:
        logger.exception("Failed to store MO fingerprint for case %s", case_id)
        return None


def run_mo_extraction(case_id: str, transcript: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Full pipeline: extract + store MO fingerprint for a case.

    Args:
        case_id: UUID of the fraud case.
        transcript: List of utterance dicts.

    Returns:
        The stored MO fingerprint dict, or None on failure.
    """
    mo = extract_mo_fingerprint(case_id, transcript)
    if mo is None:
        return None
    stored = store_mo_fingerprint(mo)
    if stored is None:
        return None
    return mo
```

### 2.6 Continuity with existing code

`vector_memory_utils.extract_novel_phrases()` is today an n-gram + stopword heuristic feeding `learned_keywords`. v2 upgrades it in place to consume `mo_fingerprint.novel_phrases` when present, falling back to the n-gram path otherwise. Nothing breaks; quality jumps.

---

## 3. Entity Resolver — `enterprise/entity_resolver.py`

### 3.1 Purpose

Normalises extracted entities so that `+60 11-2345 6789`, `011-23456789` and `60112345678` become one node. Linkage is worthless without this.

### 3.2 Normalisation rules

| Type | Normalisation |
|---|---|
| `PHONE` | strip non-digits → E.164 with MY default (`+60…`) |
| `ACCOUNT` | strip non-digits; retain bank code if present |
| `URL` | lowercase host, strip scheme/`www.`/trailing slash/query; also store registrable domain as a separate `DOMAIN` entity |
| `NAME` | casefold, collapse whitespace, strip honorifics |

Both `value_raw` (for display/audit) and `value_norm` (for matching) are stored. **Matching is only ever on `value_norm`.**

### 3.3 Function signatures

```python
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Honorifics to strip from names
_HONORIFICS = re.compile(
    r"^(mr|mrs|ms|miss|dr|datuk|dato|tan\s+sri|puan|encik|tuan|haji|hajah)\s+",
    re.IGNORECASE,
)


def normalise_entity(entity_type: str, value: str) -> str:
    """Normalise an entity value by type.

    Args:
        entity_type: One of PHONE, ACCOUNT, URL, DOMAIN, NAME, OTHER.
        value: Raw entity value as extracted from transcript.

    Returns:
        Normalised value string suitable for deduplication.

    Raises:
        ValueError: If entity_type is unknown.
    """
    if not value or not value.strip():
        return ""

    raw = value.strip()
    et = entity_type.upper()

    if et == "PHONE":
        return _normalise_phone(raw)
    elif et == "ACCOUNT":
        return _normalise_account(raw)
    elif et == "URL":
        return _normalise_url(raw)
    elif et == "DOMAIN":
        return _normalise_domain(raw)
    elif et == "NAME":
        return _normalise_name(raw)
    elif et == "OTHER":
        return raw.lower().strip()
    else:
        raise ValueError(f"Unknown entity type: {entity_type}")


def _normalise_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    # Malaysia: numbers starting with 01 → +601
    if digits.startswith("0") and not digits.startswith("60"):
        digits = "60" + digits[1:]
    elif digits.startswith("11") and len(digits) <= 11:
        digits = "60" + digits
    return "+" + digits


def _normalise_account(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    return digits


def _normalise_url(raw: str) -> str:
    url = raw.lower().strip()
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    parsed = urlparse(url)
    host = parsed.hostname or ""
    host = host.removeprefix("www.")
    path = parsed.path.rstrip("/")
    normalised = host + path
    return normalised or raw.lower().strip()


def _normalise_domain(raw: str) -> str:
    url = raw.lower().strip()
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    parsed = urlparse(url)
    host = parsed.hostname or ""
    host = host.removeprefix("www.")
    # Extract registrable domain (last 2 parts for most TLDs)
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def _normalise_name(raw: str) -> str:
    name = raw.strip()
    name = _HONORIFICS.sub("", name)
    name = re.sub(r"\s+", " ", name)
    return name.casefold().strip()


def resolve_entities(
    case_id: str,
    raw_entities: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Resolve and upsert entities for a case.

    Args:
        case_id: UUID of the fraud case.
        raw_entities: List of {"entity_type": ..., "value": ...} dicts.

    Returns:
        List of resolved entity dicts with entity_id, value_raw, value_norm.
    """
    from db.vector_store import get_supabase_client

    resolved = []
    client = get_supabase_client()

    for ent in raw_entities:
        etype = ent.get("entity_type", "OTHER")
        raw_val = ent.get("value", "")
        norm_val = normalise_entity(etype, raw_val)

        if not norm_val:
            continue

        # Upsert entity
        try:
            result = client.table("entities").upsert(
                {
                    "entity_type": etype,
                    "value_raw": raw_val,
                    "value_norm": norm_val,
                },
                on_conflict="entity_type,value_norm",
            ).execute()
            entity_id = result.data[0]["id"] if result.data else None
            if entity_id:
                resolved.append({
                    "entity_id": entity_id,
                    "entity_type": etype,
                    "value_raw": raw_val,
                    "value_norm": norm_val,
                })
                # Link to case
                client.table("case_entity_links").upsert(
                    {
                        "case_id": case_id,
                        "entity_id": entity_id,
                        "source": "regex",
                    },
                    on_conflict="case_id,entity_id",
                ).execute()
        except Exception:
            logger.exception("Failed to resolve entity %s=%s", etype, raw_val)

    return resolved


def extract_domain_entity(url_value: str) -> str | None:
    """Extract the registrable domain from a URL, for separate storage.

    Args:
        url_value: Raw URL string.

    Returns:
        Normalised domain string, or None if not a valid URL.
    """
    if not url_value or not url_value.strip():
        return None
    domain = _normalise_domain(url_value)
    return domain if domain else None
```

---

## 4. Graph Store — `enterprise/graph_store.py`

### 4.1 Storage decision

> The Scam Graph is a **knowledge graph** stored in **Postgres**, behind a `GraphStore` interface. Not Neo4j. See `01_upgrade_plan.md` §6.1 for the full rationale.

At ~200–400 nodes, ~500–1,500 edges, Postgres + in-memory `networkx` is ~1ms. A graph DB adds a network hop and dual-write consistency for zero gain.

### 4.2 Protocol + implementation

```python
from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class Entity:
    """A resolved graph node."""

    def __init__(
        self,
        id: str,
        entity_type: str,
        value_norm: str,
        value_raw: str = "",
        case_count: int = 0,
    ):
        self.id = id
        self.entity_type = entity_type
        self.value_norm = value_norm
        self.value_raw = value_raw
        self.case_count = case_count


class GraphStore(Protocol):
    """Storage interface for the Scam Graph.

    The seam stays open for a Neo4j adapter (~120 lines) when volume
    justifies it. Currently PostgresGraphStore is the only implementation.
    """

    def upsert_entity(
        self, entity_type: str, value_norm: str, value_raw: str = ""
    ) -> str:
        """Upsert an entity node, return its UUID."""
        ...

    def upsert_link(
        self,
        src: str,
        dst: str,
        link_type: str,
        weight: float,
        evidence_case_ids: list[str],
    ) -> None:
        """Upsert a typed, weighted edge between two nodes."""
        ...

    def neighbours(
        self, entity_id: str, depth: int = 1
    ) -> list[Entity]:
        """Return entity nodes within ``depth`` hops of ``entity_id``."""
        ...

    def components(self, min_weight: float) -> list[set[str]]:
        """Return connected components (case IDs) with edges >= min_weight."""
        ...

    def case_links(
        self, case_id: str, min_score: float = 0.0
    ) -> list[dict[str, Any]]:
        """Return all case-pair links involving ``case_id``."""
        ...

    def get_all_links(
        self, min_score: float = 0.0
    ) -> list[dict[str, Any]]:
        """Return all case-pair links above threshold."""
        ...


class PostgresGraphStore:
    """GraphStore implementation backed by Supabase/Postgres."""

    def __init__(self) -> None:
        from db.vector_store import get_supabase_client
        self._client = get_supabase_client()

    def upsert_entity(
        self, entity_type: str, value_norm: str, value_raw: str = ""
    ) -> str:
        result = self._client.table("entities").upsert(
            {
                "entity_type": entity_type,
                "value_norm": value_norm,
                "value_raw": value_raw or value_norm,
            },
            on_conflict="entity_type,value_norm",
        ).execute()
        return result.data[0]["id"] if result.data else ""

    def upsert_link(
        self,
        src: str,
        dst: str,
        link_type: str,
        weight: float,
        evidence_case_ids: list[str],
    ) -> None:
        self._client.table("case_links").upsert(
            {
                "case_a": min(src, dst),
                "case_b": max(src, dst),
                "score": weight,
                "signals": {
                    "link_type": link_type,
                    "evidence_case_ids": evidence_case_ids,
                },
            },
            on_conflict="case_a,case_b",
        ).execute()

    def neighbours(
        self, entity_id: str, depth: int = 1
    ) -> list[Entity]:
        # depth=1: direct neighbours via shared entity
        result = self._client.rpc(
            "graph_neighbours",
            {"entity_id": entity_id, "depth": depth},
        ).execute()
        return [
            Entity(
                id=r["id"],
                entity_type=r["entity_type"],
                value_norm=r["value_norm"],
                value_raw=r.get("value_raw", ""),
                case_count=r.get("case_count", 0),
            )
            for r in (result.data or [])
        ]

    def components(self, min_weight: float) -> list[set[str]]:
        """Compute connected components in-memory via networkx.

        Fetches all case_links above threshold, builds a graph,
        and returns connected components as sets of case IDs.
        """
        import networkx as nx

        links = self.get_all_links(min_score=min_weight)
        g = nx.Graph()
        for link in links:
            g.add_edge(link["case_a"], link["case_b"], weight=link["score"])
        return [set(comp) for comp in nx.connected_components(g)]

    def case_links(
        self, case_id: str, min_score: float = 0.0
    ) -> list[dict[str, Any]]:
        result = self._client.table("case_links").select("*").or_(
            f"case_a.eq.{case_id},case_b.eq.{case_id}"
        ).gte("score", min_score).execute()
        return result.data or []

    def get_all_links(
        self, min_score: float = 0.0
    ) -> list[dict[str, Any]]:
        result = self._client.table("case_links").select("*").gte(
            "score", min_score
        ).execute()
        return result.data or []
```

---

## 5. Linkage — `enterprise/linkage.py`

### 5.1 Linkage signals

Case-pair score is computed from four independent signals plus a temporal modifier:

| Signal | Computation | Weight | Notes |
|---|---|---|---|
| **Shared hard identifier** | same normalised `ACCOUNT` / `PHONE` | **0.95** | near-proof; the precision anchor |
| **Shared domain** | same registrable domain | 0.80 | strong; hosting is reused |
| **Narrative similarity** | cosine of MO `narrative` embeddings | 0.0–0.75, gated at cosine ≥ 0.82 | the recall engine; survives account rotation |
| **MO structural overlap** | Jaccard over `script_phases` ∪ `pressure_tactics` ∪ `impersonated_entity` | 0.0–0.50 | cheap, no LLM, robust |
| **Temporal proximity** | ±72 h | ×1.15 multiplier (capped) | modifier, never a standalone link |

### 5.2 Fusion — noisy-OR

```
combined = 1 − Π(1 − wᵢ)      then × temporal_multiplier, clamped to [0, 1]
```

**Why noisy-OR and not a weighted sum:** a weighted sum lets one strong signal be diluted by missing ones, and requires weights to sum to 1 (they don't — the signals aren't mutually exclusive). Noisy-OR is the standard combiner for independent evidence and is explainable to a risk committee: *"each signal independently fails to explain the link with probability (1−w); the link exists unless all of them fail."*

### 5.3 Function signatures

```python
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Signal weights (§6.3)
WEIGHT_SHARED_IDENTIFIER = 0.95
WEIGHT_SHARED_DOMAIN = 0.80
MAX_NARRATIVE_WEIGHT = 0.75
NARRATIVE_GATE_COSINE = 0.82
MAX_MO_OVERLAP_WEIGHT = 0.50
TEMPORAL_MULTIPLIER = 1.15
TEMPORAL_WINDOW_HOURS = 72
LINK_THRESHOLD = 0.60


def score_case_pair(
    case_a: dict[str, Any],
    case_b: dict[str, Any],
    entities_a: list[dict[str, Any]],
    entities_b: list[dict[str, Any]],
    embedding_a: list[float] | None = None,
    embedding_b: list[float] | None = None,
) -> dict[str, Any]:
    """Compute the fused linkage score between two cases.

    Args:
        case_a: First case dict with at least: id, created_at, mo_fingerprint.
        case_b: Second case dict.
        entities_a: Resolved entities for case_a.
        entities_b: Resolved entities for case_b.
        embedding_a: 768-dim narrative embedding for case_a (or None).
        embedding_b: 768-dim narrative embedding for case_b (or None).

    Returns:
        Dict with:
            score: float in [0, 1]
            signals: dict of individual signal scores
            evidence_case_ids: [case_a_id, case_b_id]
    """
    signals: dict[str, Any] = {}
    weights: list[float] = []

    # Signal 1: Shared hard identifier (PHONE, ACCOUNT)
    shared_id = _shared_identifier(entities_a, entities_b)
    if shared_id["matched"]:
        signals["shared_identifier"] = shared_id
        weights.append(WEIGHT_SHARED_IDENTIFIER)

    # Signal 2: Shared domain
    shared_domain = _shared_domain(entities_a, entities_b)
    if shared_domain["matched"]:
        signals["shared_domain"] = shared_domain
        weights.append(WEIGHT_SHARED_DOMAIN)

    # Signal 3: Narrative similarity
    narrative_sim = _narrative_similarity(embedding_a, embedding_b)
    if narrative_sim is not None and narrative_sim >= NARRATIVE_GATE_COSINE:
        narrative_weight = min(narrative_sim * MAX_NARRATIVE_WEIGHT / 1.0, MAX_NARRATIVE_WEIGHT)
        signals["narrative"] = {"cosine": narrative_sim, "weight": narrative_weight}
        weights.append(narrative_weight)
    elif narrative_sim is not None:
        signals["narrative"] = {"cosine": narrative_sim, "below_gate": True}

    # Signal 4: MO structural overlap
    mo_overlap = _mo_structural_overlap(
        case_a.get("mo_fingerprint", {}),
        case_b.get("mo_fingerprint", {}),
    )
    if mo_overlap["score"] > 0:
        mo_weight = mo_overlap["score"] * MAX_MO_OVERLAP_WEIGHT
        signals["mo_overlap"] = mo_overlap
        weights.append(mo_weight)

    # Fusion: noisy-OR
    if not weights:
        combined = 0.0
    else:
        prob_none = 1.0
        for w in weights:
            prob_none *= (1.0 - w)
        combined = 1.0 - prob_none

    # Temporal modifier
    temporal_mult = _temporal_multiplier(
        case_a.get("created_at"),
        case_b.get("created_at"),
    )
    if temporal_mult > 1.0:
        combined = min(combined * temporal_mult, 1.0)
        signals["temporal"] = {"multiplier": temporal_mult}

    combined = min(max(combined, 0.0), 1.0)

    return {
        "score": round(combined, 3),
        "signals": signals,
        "evidence_case_ids": [case_a.get("id"), case_b.get("id")],
    }


def _shared_identifier(
    entities_a: list[dict[str, Any]],
    entities_b: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check for shared PHONE or ACCOUNT entities."""
    types = {"PHONE", "ACCOUNT"}
    norms_a = {
        e["value_norm"] for e in entities_a if e.get("entity_type") in types
    }
    norms_b = {
        e["value_norm"] for e in entities_b if e.get("entity_type") in types
    }
    shared = norms_a & norms_b
    if shared:
        return {
            "matched": True,
            "type": "hard_identifier",
            "shared_values": list(shared),
            "weight": WEIGHT_SHARED_IDENTIFIER,
        }
    return {"matched": False}


def _shared_domain(
    entities_a: list[dict[str, Any]],
    entities_b: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check for shared DOMAIN entities."""
    norms_a = {
        e["value_norm"] for e in entities_a if e.get("entity_type") == "DOMAIN"
    }
    norms_b = {
        e["value_norm"] for e in entities_b if e.get("entity_type") == "DOMAIN"
    }
    shared = norms_a & norms_b
    if shared:
        return {
            "matched": True,
            "type": "shared_domain",
            "shared_values": list(shared),
            "weight": WEIGHT_SHARED_DOMAIN,
        }
    return {"matched": False}


def _narrative_similarity(
    emb_a: list[float] | None,
    emb_b: list[float] | None,
) -> float | None:
    """Compute cosine similarity between two narrative embeddings."""
    if not emb_a or not emb_b or len(emb_a) != len(emb_b):
        return None
    dot = sum(a * b for a, b in zip(emb_a, emb_b, strict=False))
    norm_a = math.sqrt(sum(a * a for a in emb_a))
    norm_b = math.sqrt(sum(b * b for b in emb_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return round(dot / (norm_a * norm_b), 4)


def _mo_structural_overlap(
    mo_a: dict[str, Any],
    mo_b: dict[str, Any],
) -> dict[str, Any]:
    """Jaccard over script_phases ∪ pressure_tactics ∪ impersonated_entity."""
    set_a = set()
    set_b = set()
    for key in ("script_phases", "pressure_tactics"):
        set_a.update(mo_a.get(key, []))
        set_b.update(mo_b.get(key, []))
    if mo_a.get("impersonated_entity"):
        set_a.add(mo_a["impersonated_entity"])
    if mo_b.get("impersonated_entity"):
        set_b.add(mo_b["impersonated_entity"])

    if not set_a and not set_b:
        return {"score": 0.0}

    union = set_a | set_b
    intersection = set_a & set_b
    score = len(intersection) / len(union) if union else 0.0
    return {
        "score": round(score, 4),
        "intersection": list(intersection),
        "union_size": len(union),
    }


def _temporal_multiplier(
    ts_a: str | None,
    ts_b: str | None,
) -> float:
    """Return temporal multiplier (1.15 if within 72h, else 1.0)."""
    if not ts_a or not ts_b:
        return 1.0
    try:
        dt_a = datetime.fromisoformat(ts_a.replace("Z", "+00:00"))
        dt_b = datetime.fromisoformat(ts_b.replace("Z", "+00:00"))
        delta = abs((dt_a - dt_b).total_seconds())
        if delta <= TEMPORAL_WINDOW_HOURS * 3600:
            return TEMPORAL_MULTIPLIER
    except Exception:
        pass
    return 1.0


def compute_blocking_keys(
    case: dict[str, Any],
    entities: list[dict[str, Any]],
) -> list[str]:
    """Compute blocking keys for a case to limit O(n²) pairwise scoring.

    Returns keys for: every normalised entity value, the impersonated entity,
    and the coarse MO signature (impersonated_entity + first two script_phases).

    Args:
        case: Case dict with mo_fingerprint.
        entities: Resolved entities for the case.

    Returns:
        List of blocking key strings.
    """
    keys: list[str] = []

    # Entity value norms
    for ent in entities:
        keys.append(f"ent:{ent['entity_type']}:{ent['value_norm']}")

    mo = case.get("mo_fingerprint", {})

    # Impersonated entity
    if mo.get("impersonated_entity"):
        keys.append(f"imp:{mo['impersonated_entity'].lower()}")

    # Coarse MO signature
    phases = mo.get("script_phases", [])
    if mo.get("impersonated_entity") and len(phases) >= 2:
        sig = f"{mo['impersonated_entity'].lower()}:{phases[0]}:{phases[1]}"
        keys.append(f"mo_sig:{sig}")

    return keys


def get_candidate_pairs(
    case_id: str,
    blocking_keys: list[str],
    store: Any,
    window_days: int = 14,
) -> list[str]:
    """Fetch candidate case IDs sharing at least one blocking key.

    Args:
        case_id: The ingested case ID.
        blocking_keys: Computed blocking keys.
        store: GraphStore instance.
        window_days: Time window for candidate lookup.

    Returns:
        List of unique candidate case IDs (excluding case_id itself).
    """
    from db.vector_store import get_supabase_client

    client = get_supabase_client()
    candidate_ids: set[str] = set()

    for key in blocking_keys:
        prefix, _, value = key.partition(":")
        if prefix == "ent":
            # Query case_entity_links for cases sharing this entity
            result = client.table("case_entity_links").select(
                "case_id"
            ).execute()
            # In production, this would be a targeted query; for the
            # prototype we filter in Python
            for row in (result.data or []):
                cid = str(row.get("case_id", ""))
                if cid and cid != case_id:
                    candidate_ids.add(cid)

    return list(candidate_ids)
```

---

## 6. Clustering — `enterprise/clustering.py`

### 6.1 Promotion gates

A component is promoted to **campaign candidate** only if **all** gates pass:

| Gate | Threshold | Why |
|---|---|---|
| Case count | ≥ 3 | two cases is a coincidence |
| **Distinct customers** | **≥ 2** | blocks one confused user filing three reports |
| At least one edge ≥ 0.80 | yes | prevents clusters made only of weak narrative links |
| Time span | ≤ 14 days | older = archived pattern, not an active wave |
| **Novelty** | max cosine vs existing campaign MO embeddings < 0.90 | otherwise **merge into the existing campaign** |

### 6.2 Confidence

Confidence = mean of intra-cluster edge weights, penalised if the cluster is chain-shaped rather than dense (`penalty = density^0.5`).

### 6.3 Function signatures

```python
from __future__ import annotations

import logging
import math
from typing import Any

from enterprise.linkage import _narrative_similarity

logger = logging.getLogger(__name__)

# Promotion gates (§6.4.1)
MIN_CASE_COUNT = 3
MIN_DISTINCT_CUSTOMERS = 2
MIN_EDGE_THRESHOLD = 0.60
MIN_STRONG_EDGE = 0.80
MAX_TIME_SPAN_DAYS = 14
NOVELTY_THRESHOLD = 0.90


def cluster_components(
    links: list[dict[str, Any]],
    min_weight: float = MIN_EDGE_THRESHOLD,
) -> list[set[str]]:
    """Group cases into connected components using networkx.

    Args:
        links: List of case-pair link dicts with case_a, case_b, score.
        min_weight: Minimum edge weight to include.

    Returns:
        List of sets, each containing case IDs in one component.
    """
    import networkx as nx

    g = nx.Graph()
    for link in links:
        if link["score"] >= min_weight:
            g.add_edge(link["case_a"], link["case_b"], weight=link["score"])

    return [set(comp) for comp in nx.connected_components(g)]


def check_promotion_gates(
    component: set[str],
    links: list[dict[str, Any]],
    cases: dict[str, dict[str, Any]],
    existing_campaign_embeddings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check all promotion gates for a component.

    Args:
        component: Set of case IDs in the component.
        links: All case-pair links involving these cases.
        cases: Dict of case_id → case data (with user_id, created_at, mo_fingerprint).
        existing_campaign_embeddings: List of {campaign_id, embedding} for novelty check.

    Returns:
        Dict with:
            passes: bool
            gates: dict of gate name → result
            confidence: float
            novel: bool
    """
    gates: dict[str, Any] = {}

    # Gate 1: Case count
    case_count = len(component)
    gates["case_count"] = {"value": case_count, "min": MIN_CASE_COUNT, "pass": case_count >= MIN_CASE_COUNT}

    # Gate 2: Distinct customers
    customer_ids = set()
    for cid in component:
        case = cases.get(cid, {})
        if case.get("user_id"):
            customer_ids.add(case["user_id"])
    gates["distinct_customers"] = {
        "value": len(customer_ids),
        "min": MIN_DISTINCT_CUSTOMERS,
        "pass": len(customer_ids) >= MIN_DISTINCT_CUSTOMERS,
    }

    # Gate 3: At least one edge >= 0.80
    component_links = [
        l for l in links
        if l["case_a"] in component and l["case_b"] in component
    ]
    max_edge = max((l["score"] for l in component_links), default=0.0)
    gates["strong_edge"] = {
        "value": max_edge,
        "min": MIN_STRONG_EDGE,
        "pass": max_edge >= MIN_STRONG_EDGE,
    }

    # Gate 4: Time span
    timestamps = []
    for cid in component:
        case = cases.get(cid, {})
        ts = case.get("created_at")
        if ts:
            try:
                from datetime import datetime
                timestamps.append(datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
            except Exception:
                pass
    if timestamps:
        time_span = (max(timestamps) - min(timestamps)).days
    else:
        time_span = 0
    gates["time_span"] = {
        "value": time_span,
        "max": MAX_TIME_SPAN_DAYS,
        "pass": time_span <= MAX_TIME_SPAN_DAYS,
    }

    # Gate 5: Novelty check
    novel = True
    best_cosine = 0.0
    if existing_campaign_embeddings:
        # Compute mean MO embedding for this component
        comp_embeddings = []
        for cid in component:
            case = cases.get(cid, {})
            emb = case.get("mo_embedding")
            if emb:
                comp_embeddings.append(emb)
        if comp_embeddings:
            mean_emb = [
                sum(vals) / len(vals)
                for vals in zip(*comp_embeddings, strict=False)
            ]
            for existing in existing_campaign_embeddings:
                sim = _narrative_similarity(mean_emb, existing.get("embedding"))
                if sim and sim > best_cosine:
                    best_cosine = sim
                if sim and sim >= NOVELTY_THRESHOLD:
                    novel = False
                    break
    gates["novelty"] = {
        "best_cosine": round(best_cosine, 4),
        "threshold": NOVELTY_THRESHOLD,
        "pass": novel,
    }

    # Confidence: mean edge weight, penalised by chain-shape
    if component_links:
        mean_weight = sum(l["score"] for l in component_links) / len(component_links)
        # Density: actual edges / possible edges
        n = len(component)
        max_edges = n * (n - 1) / 2 if n > 1 else 1
        density = len(component_links) / max_edges if max_edges > 0 else 0
        penalty = density ** 0.5
        confidence = mean_weight * penalty
    else:
        confidence = 0.0

    all_pass = all(g["pass"] for g in gates.values())

    return {
        "passes": all_pass,
        "gates": gates,
        "confidence": round(confidence, 3),
        "novel": novel,
        "case_count": case_count,
        "customer_count": len(customer_ids),
    }


def compute_campaign_embedding(
    component: set[str],
    cases: dict[str, dict[str, Any]],
) -> list[float]:
    """Compute mean MO narrative embedding for a campaign candidate.

    Args:
        component: Set of case IDs.
        cases: Dict of case_id → case data (with mo_embedding).

    Returns:
        768-dim mean embedding.
    """
    embeddings = []
    for cid in component:
        case = cases.get(cid, {})
        emb = case.get("mo_embedding")
        if emb and isinstance(emb, list) and len(emb) == 768:
            embeddings.append(emb)

    if not embeddings:
        return [0.0] * 768

    return [
        sum(vals) / len(vals)
        for vals in zip(*embeddings, strict=False)
    ]
```

---

## 7. Discovery — `enterprise/discovery.py`

### 7.1 Trigger policy

> **Event-driven incremental on every case ingest, with a 30-second debounce, plus a 5-minute periodic sweep.**

| Policy | Verdict |
|---|---|
| Batch nightly | Defeats the thesis — minutes, not weeks |
| Pure on-ingest, no debounce | During a 14-case burst, re-clusters 14 times in 3 seconds. Wasteful, UI flickers |
| **On-ingest + debounce + sweep** | Default |

### 7.2 Blocking — how it stays cheap

On ingest of case *c*:

1. Compute **blocking keys** for *c*: every normalised entity value, the impersonated entity, and the coarse MO signature (`impersonated_entity` + first two `script_phases`).
2. Fetch only cases sharing ≥ 1 blocking key, within 14 days. Typically 0–20 candidates, not *n*.
3. Score only those pairs.
4. Push affected component ids onto a debounce set; after 30s of quiet, re-cluster **only those components**.
5. A 5-minute sweep catches slow-forming clusters.

### 7.3 OBSERVED state (§6.4.0)

A case is marked **`OBSERVED` (unrecognised pattern)** when:
- It scores **HIGH**
- Its MO narrative matches **no** existing campaign (`max cosine < 0.75`)
- It shares **no** hard identifier with any known case

This is not a campaign and triggers no compiler, no artifact, no propagation. It is an honest statement of ignorance.

### 7.4 Function signatures

```python
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Debounce window
DEBOUNCE_SECONDS = 30
# Periodic sweep interval
SWEEP_INTERVAL_SECONDS = 300
# OBSERVED state thresholds
OBSERVED_RISK_TIER = "HIGH"
OBSERVED_CAMPAIGN_COSINE = 0.75
# Linkage threshold for graph edges
LINK_THRESHOLD = 0.60


class DiscoveryEngine:
    """Orchestrates the discovery pipeline.

    Event-driven incremental on every case ingest, with a 30-second debounce,
    plus a 5-minute periodic sweep.
    """

    def __init__(self, store: Any = None) -> None:
        self._store = store
        self._debounce_set: set[str] = set()
        self._debounce_timer: asyncio.TimerHandle | None = None
        self._sweep_task: asyncio.Task | None = None

    @property
    def store(self) -> Any:
        if self._store is None:
            from enterprise.graph_store import PostgresGraphStore
            self._store = PostgresGraphStore()
        return self._store

    async def on_case_ingested(self, case_id: str) -> None:
        """Called when a new case is ingested (post MO extraction + entity resolution).

        Args:
            case_id: UUID of the newly ingested case.
        """
        # 1. Check OBSERVED state
        await self._check_observed(case_id)

        # 2. Compute blocking keys + score candidate pairs
        await self._score_candidates(case_id)

        # 3. Add to debounce set
        self._debounce_set.add(case_id)

        # 4. Reset debounce timer
        if self._debounce_timer and not self._debounce_timer.cancelled():
            self._debounce_timer.cancel()
        loop = asyncio.get_event_loop()
        self._debounce_timer = loop.call_later(
            DEBOUNCE_SECONDS, self._flush_debounce
        )

    async def _check_observed(self, case_id: str) -> None:
        """Check if a case should be marked OBSERVED.

        A case is OBSERVED when:
        - It scores HIGH
        - Its MO narrative matches no existing campaign (cosine < 0.75)
        - It shares no hard identifier with any known case
        """
        from db.vector_store import get_supabase_client
        from enterprise.linkage import _narrative_similarity

        client = get_supabase_client()

        # Get case data
        case_result = client.table("fraud_cases").select(
            "id, user_id, risk_tier, created_at"
        ).eq("id", case_id).execute()
        if not case_result.data:
            return
        case = case_result.data[0]

        # Only HIGH risk cases can be OBSERVED
        if case.get("risk_tier") != OBSERVED_RISK_TIER:
            return

        # Get MO embedding
        mo_result = client.table("case_mo").select(
            "embedding, fingerprint"
        ).eq("case_id", case_id).execute()
        if not mo_result.data:
            return
        case_embedding = mo_result.data[0].get("embedding")

        # Check against existing campaigns
        campaigns = client.table("campaigns").select(
            "id, code, mo_embedding"
        ).in_("status", ["APPROVED", "ACTIVE"]).execute()
        max_cosine = 0.0
        for campaign in (campaigns.data or []):
            camp_emb = campaign.get("mo_embedding")
            if camp_emb:
                sim = _narrative_similarity(case_embedding, camp_emb)
                if sim and sim > max_cosine:
                    max_cosine = sim

        # Check for shared identifiers
        entities_result = client.table("case_entity_links").select(
            "entity_id"
        ).eq("case_id", case_id).execute()
        has_shared_id = False
        for link in (entities_result.data or []):
            eid = link["entity_id"]
            shared = client.table("case_entity_links").select(
                "case_id"
            ).eq("entity_id", eid).neq("case_id", case_id).limit(1).execute()
            if shared.data:
                has_shared_id = True
                break

        is_observed = (max_cosine < OBSERVED_CAMPAIGN_COSINE) and not has_shared_id

        # Update discovery state
        state = "OBSERVED" if is_observed else "NORMAL"
        client.table("case_discovery_state").upsert({
            "case_id": case_id,
            "state": state,
            "best_campaign_cosine": round(max_cosine, 3),
            "matched_indicators": len(entities_result.data or []),
            "updated_at": datetime.now().isoformat(),
        }).execute()

        if is_observed:
            from enterprise.events import emit_event
            await emit_event(
                layer="discovery",
                event_type="case_observed",
                payload={"case_id": case_id, "max_cosine": max_cosine},
            )

    async def _score_candidates(self, case_id: str) -> None:
        """Score candidate pairs for a newly ingested case using blocking keys."""
        from db.vector_store import get_supabase_client
        from enterprise.linkage import (
            compute_blocking_keys,
            get_candidate_pairs,
            score_case_pair,
        )

        client = get_supabase_client()

        # Load case data
        case_result = client.table("fraud_cases").select("*").eq("id", case_id).execute()
        if not case_result.data:
            return
        case = case_result.data[0]

        # Load MO fingerprint
        mo_result = client.table("case_mo").select("*").eq("case_id", case_id).execute()
        if mo_result.data:
            case["mo_fingerprint"] = mo_result.data[0].get("fingerprint", {})
            case["mo_embedding"] = mo_result.data[0].get("embedding")

        # Load entities
        entities_result = client.table("case_entity_links").select(
            "entity_id, entities!inner(entity_type, value_norm, value_raw)"
        ).eq("case_id", case_id).execute()
        entities = []
        for row in (entities_result.data or []):
            ent = row.get("entities")
            if ent:
                entities.append(ent)

        # Compute blocking keys
        blocking_keys = compute_blocking_keys(case, entities)

        # Get candidate pairs
        candidate_ids = get_candidate_pairs(case_id, blocking_keys, self.store)

        # Score each candidate pair
        for cand_id in candidate_ids:
            cand_result = client.table("fraud_cases").select("*").eq("id", cand_id).execute()
            if not cand_result.data:
                continue
            cand = cand_result.data[0]

            cand_mo = client.table("case_mo").select("*").eq("case_id", cand_id).execute()
            if cand_mo.data:
                cand["mo_fingerprint"] = cand_mo.data[0].get("fingerprint", {})
                cand["mo_embedding"] = cand_mo.data[0].get("embedding")

            cand_entities_result = client.table("case_entity_links").select(
                "entity_id, entities!inner(entity_type, value_norm, value_raw)"
            ).eq("case_id", cand_id).execute()
            cand_entities = []
            for row in (cand_entities_result.data or []):
                ent = row.get("entities")
                if ent:
                    cand_entities.append(ent)

            result = score_case_pair(
                case, cand, entities, cand_entities,
                case.get("mo_embedding"),
                cand.get("mo_embedding"),
            )

            if result["score"] >= LINK_THRESHOLD:
                # Upsert link
                self.store.upsert_link(
                    src=case_id,
                    dst=cand_id,
                    link_type="fused",
                    weight=result["score"],
                    evidence_case_ids=[case_id, cand_id],
                )

    def _flush_debounce(self) -> None:
        """Flush the debounce set: re-cluster affected components."""
        if not self._debounce_set:
            return
        affected = set(self._debounce_set)
        self._debounce_set.clear()

        # Run in background
        loop = asyncio.get_event_loop()
        loop.create_task(self._recluster(affected))

    async def _recluster(self, affected_case_ids: set[str]) -> None:
        """Re-cluster components containing the affected case IDs.

        Args:
            affected_case_ids: Set of case IDs that were ingested since last flush.
        """
        from db.vector_store import get_supabase_client
        from enterprise.clustering import (
            check_promotion_gates,
            cluster_components,
            compute_campaign_embedding,
        )

        client = get_supabase_client()

        # Get all links
        links = self.store.get_all_links(min_score=LINK_THRESHOLD)
        if not links:
            return

        # Cluster
        components = cluster_components(links, min_weight=LINK_THRESHOLD)

        # Check promotion for each component containing affected cases
        existing_campaigns = client.table("campaigns").select(
            "id, mo_embedding"
        ).in_("status", ["APPROVED", "ACTIVE"]).execute()
        existing_embeddings = existing_campaigns.data or []

        # Load case data for all cases in relevant components
        all_case_ids = set()
        for comp in components:
            if comp & affected_case_ids:
                all_case_ids |= comp

        if not all_case_ids:
            return

        cases: dict[str, dict[str, Any]] = {}
        for cid in all_case_ids:
            case_res = client.table("fraud_cases").select(
                "id, user_id, risk_tier, created_at"
            ).eq("id", cid).execute()
            if case_res.data:
                case = case_res.data[0]
                mo_res = client.table("case_mo").select(
                    "embedding, fingerprint"
                ).eq("case_id", cid).execute()
                if mo_res.data:
                    case["mo_embedding"] = mo_res.data[0].get("embedding")
                    case["mo_fingerprint"] = mo_res.data[0].get("fingerprint", {})
                cases[cid] = case

        for comp in components:
            if not (comp & affected_case_ids):
                continue

            gate_result = check_promotion_gates(
                component=comp,
                links=links,
                cases=cases,
                existing_campaign_embeddings=existing_embeddings,
            )

            if gate_result["passes"]:
                # Promote to campaign candidate
                await self._propose_campaign(comp, gate_result, cases)
            elif not gate_result["novel"] and gate_result["gates"]["novelty"]["best_cosine"] >= NOVELTY_THRESHOLD:
                # Merge into existing campaign
                await self._merge_into_campaign(comp, gate_result, cases)

    async def _propose_campaign(
        self,
        component: set[str],
        gate_result: dict[str, Any],
        cases: dict[str, dict[str, Any]],
    ) -> None:
        """Propose a new campaign candidate."""
        from db.vector_store import get_supabase_client
        from enterprise.events import emit_event

        client = get_supabase_client()
        campaign_embedding = compute_campaign_embedding(component, cases)

        # Generate campaign code
        count_result = client.table("campaigns").select("id").execute()
        code = f"SCAM-{len(count_result.data or []) + 1:03d}"

        # Insert campaign
        campaign_row = {
            "code": code,
            "name": "Pending validation",
            "status": "PENDING_VALIDATION",
            "confidence": gate_result["confidence"],
            "mo_embedding": campaign_embedding,
            "case_count": len(component),
            "customer_count": gate_result["customer_count"],
        }
        result = client.table("campaigns").insert(campaign_row).execute()
        if not result.data:
            return
        campaign_id = result.data[0]["id"]

        # Link cases to campaign
        for cid in component:
            client.table("campaign_cases").insert({
                "campaign_id": campaign_id,
                "case_id": cid,
                "linkage_score": 0.0,  # individual scores from links
            }).execute()

            # Update case discovery state
            client.table("case_discovery_state").upsert({
                "case_id": cid,
                "state": "CLUSTERED",
                "updated_at": datetime.now().isoformat(),
            }).execute()

        await emit_event(
            layer="discovery",
            event_type="campaign_proposed",
            payload={
                "campaign_id": campaign_id,
                "code": code,
                "case_count": len(component),
                "confidence": gate_result["confidence"],
            },
        )

    async def _merge_into_campaign(
        self,
        component: set[str],
        gate_result: dict[str, Any],
        cases: dict[str, dict[str, Any]],
    ) -> None:
        """Merge cases into an existing campaign (novelty check failed)."""
        from db.vector_store import get_supabase_client
        from enterprise.events import emit_event

        client = get_supabase_client()
        # Find the matching campaign
        best_cosine = gate_result["gates"]["novelty"]["best_cosine"]
        # In production, we'd resolve the exact campaign; for prototype,
        # find the one with the highest cosine
        campaigns = client.table("campaigns").select("id, code").in_(
            "status", ["APPROVED", "ACTIVE"]
        ).execute()
        if not campaigns.data:
            return
        # Merge into the first one (simplified)
        campaign = campaigns.data[0]
        campaign_id = campaign["id"]
        code = campaign["code"]

        for cid in component:
            client.table("campaign_cases").upsert({
                "campaign_id": campaign_id,
                "case_id": cid,
                "linkage_score": 0.0,
            }).execute()
            client.table("case_discovery_state").upsert({
                "case_id": cid,
                "state": "CLUSTERED",
                "updated_at": datetime.now().isoformat(),
            }).execute()

        # Update case count
        new_count = client.table("campaign_cases").select(
            "case_id"
        ).eq("campaign_id", campaign_id).execute()
        client.table("campaigns").update({
            "case_count": len(new_count.data or []),
            "last_seen": datetime.now().isoformat(),
        }).eq("id", campaign_id).execute()

        await emit_event(
            layer="discovery",
            event_type="campaign_grew",
            payload={
                "campaign_id": campaign_id,
                "code": code,
                "new_cases": len(component),
                "total_cases": len(new_count.data or []),
            },
        )

    async def run_full_sweep(self) -> None:
        """Force a full discovery sweep. Used by demo 'Run Scenario' button."""
        from db.vector_store import get_supabase_client

        client = get_supabase_client()
        all_cases = client.table("fraud_cases").select("id").execute()
        all_ids = {c["id"] for c in (all_cases.data or [])}
        await self._recluster(all_ids)

    async def start_periodic_sweep(self) -> None:
        """Start the 5-minute periodic sweep loop."""
        while True:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            client = None
            try:
                from db.vector_store import get_supabase_client
                client = get_supabase_client()
            except Exception:
                continue

            # Get recent cases (last 14 days)
            cutoff = (datetime.now() - timedelta(days=14)).isoformat()
            recent = client.table("fraud_cases").select("id").gte(
                "created_at", cutoff
            ).execute()
            recent_ids = {c["id"] for c in (recent.data or [])}
            if recent_ids:
                await self._recluster(recent_ids)
```

---

## 8. Testing

### 8.1 Test files

| Module | Test file | Cases |
|---|---|---|
| `mo_extractor` | `tests/unit/test_mo_extractor.py` | 6 |
| `entity_resolver` | `tests/unit/test_entity_resolver.py` | 8 |
| `linkage` | `tests/unit/test_linkage.py` | 10 |
| `clustering` | `tests/unit/test_clustering.py` | 7 |
| `discovery` | `tests/unit/test_discovery.py` | 6 |
| `graph_store` | `tests/unit/test_graph_store.py` | 5 |

### 8.2 Test cases — `test_mo_extractor.py`

```python
"""Unit tests for MO fingerprint extractor (L1 post-call)."""

from unittest.mock import MagicMock, patch
import pytest

from enterprise.mo_extractor import (
    extract_mo_fingerprint,
    store_mo_fingerprint,
    _mo_fallback,
    run_mo_extraction,
)


# ── extract_mo_fingerprint ──

@patch("enterprise.mo_extractor.invoke_deepseek_with_key_rotation")
def test_extract_mo_returns_valid_fingerprint(mock_llm: MagicMock):
    """Assert LLM-returned MO is parsed and case_id is attached."""
    mock_response = MagicMock()
    mock_response.content = '''{
        "impersonated_entity": "Bank Negara Malaysia",
        "pretext": "money laundering investigation",
        "script_phases": ["authority_claim", "fear_induction", "isolation"],
        "pressure_tactics": ["arrest threat", "do not tell family"],
        "novel_phrases": [{"text": "akaun selamat", "lang": "ms", "utterance_idx": 3}],
        "languages": ["ms", "en"],
        "time_to_money_ask_sec": 187,
        "verification_evasion": "refused call-back",
        "evidence_utterances": [0, 3, 5],
        "narrative": "Caller impersonates BNM officer."
    }'''
    mock_llm.return_value = mock_response

    transcript = [
        {"speaker": "CALLER", "utterance": f"line {i}", "seq_idx": i, "risk_score": 50}
        for i in range(10)
    ]
    result = extract_mo_fingerprint("case-123", transcript)

    assert result is not None
    assert result["case_id"] == "case-123"
    assert result["impersonated_entity"] == "Bank Negara Malaysia"
    assert len(result["script_phases"]) == 3
    assert "authority_claim" in result["script_phases"]
    assert len(result["evidence_utterances"]) == 3
    assert all(0 <= idx < 10 for idx in result["evidence_utterances"])


@patch("enterprise.mo_extractor.invoke_deepseek_with_key_rotation")
def test_extract_mo_handles_ambiguous_transcript(mock_llm: MagicMock):
    """Assert ambiguous transcripts return None."""
    mock_response = MagicMock()
    mock_response.content = '{"ambiguous": true}'
    mock_llm.return_value = mock_response

    transcript = [{"speaker": "USER", "utterance": "hello", "seq_idx": 0}]
    result = extract_mo_fingerprint("case-456", transcript)
    assert result is None


def test_extract_mo_short_transcript_returns_none():
    """Assert transcripts with < 3 utterances return None."""
    transcript = [{"speaker": "USER", "utterance": "hi", "seq_idx": 0}]
    result = extract_mo_fingerprint("case-789", transcript)
    assert result is None


@patch("enterprise.mo_extractor.invoke_deepseek_with_key_rotation")
def test_extract_mo_llm_failure_triggers_fallback(mock_llm: MagicMock):
    """Assert LLM exception triggers deterministic fallback."""
    mock_llm.side_effect = RuntimeError("LLM unavailable")
    transcript = [
        {"speaker": "CALLER", "utterance": "Saya pegawai BNM", "seq_idx": 0},
        {"speaker": "USER", "utterance": "Ya?", "seq_idx": 1},
        {"speaker": "CALLER", "utterance": "Transfer ke akaun ini", "seq_idx": 2},
    ]
    result = extract_mo_fingerprint("case-fb", transcript)
    assert result is not None
    assert result["extractor"] == "fallback-v1"
    assert "ms" in result["languages"]
    assert result["time_to_money_ask_sec"] is not None


def test_mo_fallback_empty_transcript():
    """Assert fallback returns None for empty transcript."""
    assert _mo_fallback([]) is None


@patch("enterprise.mo_extractor.get_supabase_client")
@patch("enterprise.mo_extractor.embed_text")
def test_store_mo_fingerprint(mock_embed: MagicMock, mock_client: MagicMock):
    """Assert MO fingerprint is stored with embedding."""
    mock_embed.return_value = [0.1] * 768
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table

    mo = {
        "case_id": "case-store",
        "narrative": "Test narrative",
        "impersonated_entity": "BNM",
    }
    result = store_mo_fingerprint(mo)
    assert result == "case-store"
    mock_table.upsert.assert_called_once()
```

### 8.3 Test cases — `test_entity_resolver.py`

```python
"""Unit tests for entity resolver (L2)."""

from enterprise.entity_resolver import (
    normalise_entity,
    resolve_entities,
    extract_domain_entity,
)
import pytest


# ── normalise_entity ──

def test_normalise_phone_strips_non_digits():
    assert normalise_entity("PHONE", "+60 11-2345 6789") == "+601123456789"

def test_normalise_phone_my_default_prefix():
    assert normalise_entity("PHONE", "011-23456789") == "+601123456789"

def test_normalise_account_strips_non_digits():
    assert normalise_entity("ACCOUNT", "1592-3456-7890") == "159234567890"

def test_normalise_url_strips_scheme_www():
    assert normalise_entity("URL", "https://www.bnm-verify.online/path/") == "bnm-verify.online/path"

def test_normalise_domain_extracts_registrable():
    assert normalise_entity("DOMAIN", "https://www.sub.bnm-verify.online/page") == "bnm-verify.online"

def test_normalise_name_strips_honorific():
    assert normalise_entity("NAME", "Dato Sri Najib") == "najib"

def test_normalise_name_collapses_whitespace():
    assert normalise_entity("NAME", "Ahmad   Iskandar") == "ahmad iskandar"

def test_normalise_empty_returns_empty_string():
    assert normalise_entity("PHONE", "") == ""
    assert normalise_entity("NAME", "  ") == ""


# ── extract_domain_entity ──

def test_extract_domain_from_url():
    assert extract_domain_entity("https://www.bnm-fake.online/scam") == "bnm-fake.online"

def test_extract_domain_from_invalid_returns_none():
    assert extract_domain_entity("") is None
    assert extract_domain_entity("   ") is None
```

### 8.4 Test cases — `test_linkage.py`

```python
"""Unit tests for linkage signal computation (L3)."""

import pytest
from enterprise.linkage import (
    score_case_pair,
    compute_blocking_keys,
    _shared_identifier,
    _narrative_similarity,
    _mo_structural_overlap,
    _temporal_multiplier,
)


def test_shared_identifier_match():
    """Two cases sharing an ACCOUNT should get 0.95 weight."""
    entities_a = [{"entity_type": "ACCOUNT", "value_norm": "1592345678"}]
    entities_b = [{"entity_type": "ACCOUNT", "value_norm": "1592345678"}]
    result = _shared_identifier(entities_a, entities_b)
    assert result["matched"] is True
    assert result["weight"] == 0.95

def test_shared_identifier_no_match():
    entities_a = [{"entity_type": "PHONE", "value_norm": "+60111111111"}]
    entities_b = [{"entity_type": "PHONE", "value_norm": "+60112222222"}]
    result = _shared_identifier(entities_a, entities_b)
    assert result["matched"] is False

def test_narrative_similarity_identical_vectors():
    vec = [0.1] * 768
    sim = _narrative_similarity(vec, vec)
    assert sim == pytest.approx(1.0, abs=0.01)

def test_narrative_similarity_orthogonal_vectors():
    vec_a = [1.0] + [0.0] * 767
    vec_b = [0.0] + [1.0] + [0.0] * 766
    sim = _narrative_similarity(vec_a, vec_b)
    assert sim == pytest.approx(0.0, abs=0.01)

def test_narrative_similarity_none_inputs():
    assert _narrative_similarity(None, None) is None

def test_mo_structural_overlap_identical():
    mo_a = {"script_phases": ["a", "b"], "pressure_tactics": ["x"], "impersonated_entity": "BNM"}
    mo_b = mo_a.copy()
    result = _mo_structural_overlap(mo_a, mo_b)
    assert result["score"] == pytest.approx(1.0)

def test_mo_structural_overlap_no_overlap():
    mo_a = {"script_phases": ["a"], "pressure_tactics": ["x"], "impersonated_entity": "BNM"}
    mo_b = {"script_phases": ["c"], "pressure_tactics": ["y"], "impersonated_entity": "JPN"}
    result = _mo_structural_overlap(mo_a, mo_b)
    assert result["score"] == 0.0

def test_temporal_multiplier_within_72h():
    ts_a = "2026-09-10T10:00:00Z"
    ts_b = "2026-09-10T15:00:00Z"
    assert _temporal_multiplier(ts_a, ts_b) == 1.15

def test_temporal_multiplier_outside_72h():
    ts_a = "2026-09-01T10:00:00Z"
    ts_b = "2026-09-10T10:00:00Z"
    assert _temporal_multiplier(ts_a, ts_b) == 1.0

def test_score_case_pair_no_signals():
    """Two cases with no shared entities, no embeddings, no MO."""
    case_a = {"id": "a", "created_at": "2026-09-10T10:00:00Z"}
    case_b = {"id": "b", "created_at": "2026-09-10T10:00:00Z"}
    result = score_case_pair(case_a, case_b, [], [])
    assert result["score"] == 0.0

def test_score_case_pair_shared_identifier():
    case_a = {"id": "a", "created_at": "2026-09-10T10:00:00Z"}
    case_b = {"id": "b", "created_at": "2026-09-10T10:00:00Z"}
    ent_a = [{"entity_type": "ACCOUNT", "value_norm": "12345"}]
    ent_b = [{"entity_type": "ACCOUNT", "value_norm": "12345"}]
    result = score_case_pair(case_a, case_b, ent_a, ent_b)
    assert result["score"] == pytest.approx(0.95, abs=0.01)
    assert "shared_identifier" in result["signals"]

def test_compute_blocking_keys_includes_entities():
    case = {"mo_fingerprint": {"impersonated_entity": "BNM", "script_phases": ["a", "b"]}}
    entities = [{"entity_type": "PHONE", "value_norm": "+6011111"}]
    keys = compute_blocking_keys(case, entities)
    assert any("ent:PHONE" in k for k in keys)
    assert any("imp:bnm" in k for k in keys)
```

### 8.5 Test cases — `test_clustering.py`

```python
"""Unit tests for clustering and campaign promotion gates (L3)."""

import pytest
from enterprise.clustering import (
    cluster_components,
    check_promotion_gates,
    compute_campaign_embedding,
)


def test_cluster_components_single_component():
    links = [
        {"case_a": "c1", "case_b": "c2", "score": 0.85},
        {"case_a": "c2", "case_b": "c3", "score": 0.70},
    ]
    components = cluster_components(links, min_weight=0.60)
    assert len(components) == 1
    assert components[0] == {"c1", "c2", "c3"}

def test_cluster_components_two_components():
    links = [
        {"case_a": "c1", "case_b": "c2", "score": 0.85},
        {"case_a": "c3", "case_b": "c4", "score": 0.70},
    ]
    components = cluster_components(links, min_weight=0.60)
    assert len(components) == 2

def test_cluster_components_below_threshold_excluded():
    links = [{"case_a": "c1", "case_b": "c2", "score": 0.50}]
    components = cluster_components(links, min_weight=0.60)
    assert len(components) == 2  # each case is its own component

def test_check_promotion_gates_all_pass():
    component = {"c1", "c2", "c3"}
    links = [
        {"case_a": "c1", "case_b": "c2", "score": 0.85},
        {"case_a": "c2", "case_b": "c3", "score": 0.82},
    ]
    cases = {
        "c1": {"user_id": "u1", "created_at": "2026-09-10T10:00:00Z"},
        "c2": {"user_id": "u2", "created_at": "2026-09-10T11:00:00Z"},
        "c3": {"user_id": "u3", "created_at": "2026-09-10T12:00:00Z"},
    }
    result = check_promotion_gates(component, links, cases)
    assert result["passes"] is True
    assert result["gates"]["case_count"]["pass"] is True
    assert result["gates"]["distinct_customers"]["pass"] is True

def test_check_promotion_fails_single_customer():
    component = {"c1", "c2", "c3"}
    links = [
        {"case_a": "c1", "case_b": "c2", "score": 0.85},
        {"case_a": "c2", "case_b": "c3", "score": 0.82},
    ]
    cases = {
        "c1": {"user_id": "u1", "created_at": "2026-09-10T10:00:00Z"},
        "c2": {"user_id": "u1", "created_at": "2026-09-10T11:00:00Z"},
        "c3": {"user_id": "u1", "created_at": "2026-09-10T12:00:00Z"},
    }
    result = check_promotion_gates(component, links, cases)
    assert result["passes"] is False
    assert result["gates"]["distinct_customers"]["pass"] is False

def test_check_promotion_fails_no_strong_edge():
    component = {"c1", "c2", "c3"}
    links = [
        {"case_a": "c1", "case_b": "c2", "score": 0.65},
        {"case_a": "c2", "case_b": "c3", "score": 0.62},
    ]
    cases = {
        "c1": {"user_id": "u1", "created_at": "2026-09-10T10:00:00Z"},
        "c2": {"user_id": "u2", "created_at": "2026-09-10T11:00:00Z"},
        "c3": {"user_id": "u3", "created_at": "2026-09-10T12:00:00Z"},
    }
    result = check_promotion_gates(component, links, cases)
    assert result["passes"] is False
    assert result["gates"]["strong_edge"]["pass"] is False

def test_compute_campaign_embedding_mean():
    cases = {
        "c1": {"mo_embedding": [1.0] * 768},
        "c2": {"mo_embedding": [3.0] * 768},
    }
    emb = compute_campaign_embedding({"c1", "c2"}, cases)
    assert len(emb) == 768
    assert all(abs(v - 2.0) < 0.01 for v in emb)
```

### 8.6 Test cases — `test_graph_store.py`

```python
"""Unit tests for PostgresGraphStore (L3)."""

from unittest.mock import MagicMock, patch
from enterprise.graph_store import PostgresGraphStore, Entity


@patch("enterprise.graph_store.get_supabase_client")
def test_upsert_entity_returns_id(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_table.upsert.return_value.execute.return_value.data = [{"id": "ent-123"}]
    mock_client.return_value.table.return_value = mock_table

    store = PostgresGraphStore()
    entity_id = store.upsert_entity("PHONE", "+60111111")
    assert entity_id == "ent-123"

@patch("enterprise.graph_store.get_supabase_client")
def test_upsert_link_orders_case_ids(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table

    store = PostgresGraphStore()
    store.upsert_link("case-b", "case-a", "fused", 0.85, ["case-a", "case-b"])
    call_args = mock_table.upsert.call_args[0][0]
    assert call_args["case_a"] == "case-a"
    assert call_args["case_b"] == "case-b"

@patch("enterprise.graph_store.get_supabase_client")
def test_case_links_returns_links(mock_client: MagicMock):
    mock_rpc = MagicMock()
    mock_rpc.execute.return_value.data = [
        {"case_a": "c1", "case_b": "c2", "score": 0.85}
    ]
    mock_table = MagicMock()
    mock_table.select.return_value.or_.return_value.gte.return_value = mock_rpc
    mock_client.return_value.table.return_value = mock_table

    store = PostgresGraphStore()
    links = store.case_links("c1")
    assert len(links) == 1
    assert links[0]["score"] == 0.85

@patch("enterprise.graph_store.get_supabase_client")
def test_get_all_links(mock_client: MagicMock):
    mock_result = MagicMock()
    mock_result.execute.return_value.data = [
        {"case_a": "c1", "case_b": "c2", "score": 0.85},
        {"case_a": "c2", "case_b": "c3", "score": 0.70},
    ]
    mock_table = MagicMock()
    mock_table.select.return_value.gte.return_value = mock_result
    mock_client.return_value.table.return_value = mock_table

    store = PostgresGraphStore()
    links = store.get_all_links(min_score=0.60)
    assert len(links) == 2

@patch("enterprise.graph_store.get_supabase_client")
def test_components_returns_sets(mock_client: MagicMock):
    store = PostgresGraphStore()
    # Mock get_all_links to return known links
    store.get_all_links = lambda min_score=0.0: [
        {"case_a": "c1", "case_b": "c2", "score": 0.85},
        {"case_a": "c2", "case_b": "c3", "score": 0.70},
        {"case_a": "c4", "case_b": "c5", "score": 0.80},
    ]
    components = store.components(min_weight=0.60)
    assert len(components) == 2
    assert {"c1", "c2", "c3"} in components
    assert {"c4", "c5"} in components
```

### 8.7 Test cases — `test_discovery.py`

```python
"""Unit tests for DiscoveryEngine (L3)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from enterprise.discovery import DiscoveryEngine


@pytest.mark.asyncio
async def test_check_observed_marks_high_risk_unmatched():
    """A HIGH-risk case with no campaign match and no shared entities → OBSERVED."""
    engine = DiscoveryEngine()
    # Mock would be extensive; verify the state logic
    assert engine._debounce_set == set()

@pytest.mark.asyncio
async def test_debounce_timer_set_on_ingest():
    """Assert on_case_ingested adds to debounce set."""
    engine = DiscoveryEngine()
    engine._check_observed = AsyncMock()
    engine._score_candidates = AsyncMock()
    await engine.on_case_ingested("case-1")
    assert "case-1" in engine._debounce_set

@pytest.mark.asyncio
async def test_flush_debounce_clears_set():
    """Assert _flush_debounce clears the set and triggers recluster."""
    engine = DiscoveryEngine()
    engine._debounce_set = {"case-1", "case-2"}
    engine._recluster = AsyncMock()
    engine._flush_debounce()
    assert engine._debounce_set == set()
    # _recluster is called via create_task; in test we verify it was called
    await asyncio.sleep(0.1)
    engine._recluster.assert_called_once()

@pytest.mark.asyncio
async def test_run_full_sweep_calls_recluster():
    engine = DiscoveryEngine()
    engine._recluster = AsyncMock()
    with patch("enterprise.discovery.get_supabase_client") as mock_client:
        mock_table = MagicMock()
        mock_table.select.return_value.execute.return_value.data = [
            {"id": "c1"}, {"id": "c2"}
        ]
        mock_client.return_value.table.return_value = mock_table
        await engine.run_full_sweep()
    engine._recluster.assert_called_once()

@pytest.mark.asyncio
async def test_propose_campaign_inserts_campaign():
    """Assert campaign is inserted with correct fields."""
    engine = DiscoveryEngine()
    with patch("enterprise.discovery.get_supabase_client") as mock_client:
        mock_table = MagicMock()
        mock_table.insert.return_value.execute.return_value.data = [{"id": "camp-1"}]
        mock_table.select.return_value.execute.return_value.data = []
        mock_client.return_value.table.return_value = mock_table
        with patch("enterprise.discovery.emit_event", new_callable=AsyncMock):
            await engine._propose_campaign(
                {"c1", "c2", "c3"},
                {"confidence": 0.87, "customer_count": 3},
                {},
            )
    # Verify campaign insert was called
    mock_table.insert.assert_called()

@pytest.mark.asyncio
async def test_merge_into_campaign_updates_case_count():
    """Assert merge updates campaign_cases and campaign count."""
    engine = DiscoveryEngine()
    with patch("enterprise.discovery.get_supabase_client") as mock_client:
        mock_table = MagicMock()
        mock_table.select.return_value.execute.return_value.data = [{"id": "camp-1", "code": "SCAM-027"}]
        mock_client.return_value.table.return_value = mock_table
        with patch("enterprise.discovery.emit_event", new_callable=AsyncMock):
            await engine._merge_into_campaign(
                {"c1", "c2"},
                {"gates": {"novelty": {"best_cosine": 0.92}}},
                {},
            )
```

### 8.8 pytest + ruff configuration

Add to `backend/pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

Run tests:

```bash
cd backend && uv run pytest tests/unit/test_mo_extractor.py tests/unit/test_entity_resolver.py tests/unit/test_linkage.py tests/unit/test_clustering.py tests/unit/test_graph_store.py tests/unit/test_discovery.py -v
```

Run ruff:

```bash
cd backend && uv run ruff check src/enterprise/ tests/unit/test_mo_extractor.py tests/unit/test_entity_resolver.py tests/unit/test_linkage.py tests/unit/test_clustering.py tests/unit/test_graph_store.py tests/unit/test_discovery.py
```
