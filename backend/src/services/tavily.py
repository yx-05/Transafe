"""Tavily search service targeting Malaysian fraud & banking portals."""

import os
from typing import Any

from tavily import TavilyClient  # type: ignore[import-untyped]

REGULATORY_DOMAINS: list[str] = [
    "bnm.gov.my",  # Bank Negara Malaysia Financial Consumer Alert List
    "sc.com.my",   # Securities Commission Malaysia Investor Alert List
]

ENFORCEMENT_DOMAINS: list[str] = [
    "rmp.gov.my",  # Royal Malaysia Police (PDRM CCID)
    "semak.my",    # PDRM SemakMule
    "lowyat.net",  # Lowyat Forum Scam Reports
]

TARGET_DOMAINS: list[str] = REGULATORY_DOMAINS + ENFORCEMENT_DOMAINS


GENERIC_TERMS: set[str] = {
    "standard transfer account",
    "standard account",
    "personal transfer",
    "utility provider",
    "unknown account",
    "savings account",
    "current account",
    "retail transfer",
}


def tavily_search(entities: list[str]) -> list[dict[str, Any]]:
    """Query Tavily Search API with multi-tiered domain scanning for BNM/SC and community forums."""
    if not entities:
        return []

    clean_entities = [
        e.strip()
        for e in entities
        if e and e.strip() and e.strip().lower() not in GENERIC_TERMS
    ]
    if not clean_entities:
        return []

    query = " ".join(clean_entities)
    api_key = os.getenv("TAVILY_API_KEY", "tvly_dummy")
    client = TavilyClient(api_key=api_key)

    combined_results: list[dict[str, Any]] = []
    seen_urls = set()

    # Determine if query contains specific non-numeric corporate/scheme brand terms
    has_brand_term = any(not token.replace("-", "").isdigit() for token in clean_entities)

    # Tier 1: Query Official Regulatory Alert Lists (BNM & SC)
    try:
        reg_query = f"{query} Financial Consumer Alert List Investor Alert List" if has_brand_term else query
        reg_response = client.search(
            query=reg_query,
            include_domains=REGULATORY_DOMAINS,
            search_depth="advanced",
            max_results=3,
        )
        for item in reg_response.get("results", []):
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                snippet_text = item.get("snippet") or item.get("content") or ""
                item["snippet"] = str(snippet_text)[:800]
                item["content"] = str(snippet_text)[:800]
                combined_results.append(item)
    except Exception:
        pass

    # Tier 2: Query Police Registries & Community Scam Forums (PDRM & Lowyat)
    try:
        enf_response = client.search(
            query=query,
            include_domains=ENFORCEMENT_DOMAINS,
            search_depth="advanced",
            max_results=3,
        )
        for item in enf_response.get("results", []):
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                snippet_text = item.get("snippet") or item.get("content") or ""
                item["snippet"] = str(snippet_text)[:800]
                item["content"] = str(snippet_text)[:800]
                combined_results.append(item)
    except Exception:
        pass

    # Tier 3: Unconstrained general search if domain-restricted searches returned no results OR low entity relevance
    entity_tokens = [
        t.lower()
        for ent in clean_entities
        for t in ent.split()
        if len(t) > 2 and not t.replace("-", "").isdigit() and t.lower() not in GENERIC_TERMS
    ]

    has_entity_hit = any(
        any(tok in f"{item.get('title', '')} {item.get('snippet', '')}".lower() for tok in entity_tokens)
        for item in combined_results
    )

    if not combined_results or not has_entity_hit:
        try:
            gen_response = client.search(
                query=f"{query} scam investment Malaysia",
                max_results=3,
            )
            for item in gen_response.get("results", []):
                url = item.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    snippet_text = item.get("snippet") or item.get("content") or ""
                    item["snippet"] = str(snippet_text)[:800]
                    item["content"] = str(snippet_text)[:800]
                    combined_results.append(item)
        except Exception:
            pass

    # Sort and structure final payload: Guarantee Slot 1 = Official Regulator Hit (BNM/SC) if available, followed by top news/investigations
    entity_tokens = [
        t.lower()
        for ent in clean_entities
        for t in ent.split()
        if len(t) > 2 and not t.replace("-", "").isdigit()
    ]

    def hit_relevance_score(item: dict[str, Any]) -> int:
        text = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
        score = 0
        for token in entity_tokens:
            if token in text:
                score += 10
        if any(tok in text for tok in ("scam", "ponzi", "fraud", "pyramid", "illegal", "alert")):
            score += 5
        return score

    combined_results.sort(key=hit_relevance_score, reverse=True)

    # Separate regulatory hits (bnm.gov.my, sc.com.my) from news/forum hits
    reg_hits = [h for h in combined_results if any(dom in h.get("url", "").lower() for dom in REGULATORY_DOMAINS)]
    other_hits = [h for h in combined_results if h not in reg_hits]

    final_hits: list[dict[str, Any]] = []
    if reg_hits:
        final_hits.append(reg_hits[0])  # Slot 1: Official Regulatory Alert Notice
    for h in (other_hits + reg_hits[1:]):
        if h not in final_hits:
            final_hits.append(h)
        if len(final_hits) >= 3:
            break

    return final_hits
