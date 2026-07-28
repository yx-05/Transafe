"""Tavily search service targeting Malaysian fraud & banking portals."""

import os
from typing import Any

from tavily import TavilyClient  # type: ignore[import-untyped]

TARGET_DOMAINS: list[str] = [
    "semak.my",
    "rmp.gov.my",
    "bnm.gov.my",
    "lowyat.net",
]


def tavily_search(entities: list[str]) -> list[dict[str, Any]]:
    """Query Tavily Search API targeting Malaysian scam/banking domains."""
    if not entities:
        return []

    clean_entities = [e.strip() for e in entities if e and e.strip()]
    if not clean_entities:
        return []

    query = " ".join(clean_entities)
    api_key = os.getenv("TAVILY_API_KEY", "tvly_dummy")
    client = TavilyClient(api_key=api_key)

    response = client.search(
        query=query,
        include_domains=TARGET_DOMAINS,
    )

    results: list[dict[str, Any]] = response.get("results", [])
    filtered_results = [
        item
        for item in results
        if any(domain in item.get("url", "").lower() for domain in TARGET_DOMAINS)
    ]
    return filtered_results
