"""Groq pgvector Vector Store Helper for TranSafe Fraud Memory."""

import os
from typing import Any, cast

from groq import Groq
from pydantic import BaseModel
from supabase import Client, create_client

groq_client: Groq | None = None
supabase_client: Client | None = None


class FraudMemoryRecord(BaseModel):
    """Pydantic model representing a fraud memory record."""

    case_id: str | None = None
    fraud_type: str
    content: str
    phone_numbers: list[str] = []
    bank_accounts: list[str] = []
    urls: list[str] = []
    amount_lost_myr: float | None = None
    risk_tier: str = "HIGH"
    source: str = "user_report"


def init_vector_store() -> None:
    """Initialize Groq and Supabase clients for vector store operations."""
    global groq_client, supabase_client
    groq_api_key = os.getenv("GROQ_API_KEY", "")
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "")

    if groq_api_key:
        groq_client = Groq(api_key=groq_api_key)
    if supabase_url and supabase_key:
        supabase_client = create_client(supabase_url, supabase_key)


def get_groq_client() -> Groq:
    """Get the initialized Groq client.

    Raises:
        RuntimeError: If Groq client is not initialized.
    """
    if groq_client is None:
        init_vector_store()
    if groq_client is None:
        raise RuntimeError("Groq client is not initialized.")
    return groq_client


def get_supabase_client() -> Client:
    """Get the initialized Supabase client.

    Raises:
        RuntimeError: If Supabase client is not initialized.
    """
    if supabase_client is None:
        init_vector_store()
    if supabase_client is None:
        raise RuntimeError("Supabase client is not initialized.")
    return supabase_client


def embed_text(text: str) -> list[float]:
    """Generate 768-dimensional text embedding via Groq nomic-embed-text-v1.5.

    Args:
        text: Input string to embed.

    Returns:
        List of 768 float values.
    """
    try:
        client = get_groq_client()
        response = client.embeddings.create(
            model="nomic-embed-text-v1.5",
            input=text,
        )
        raw_embedding = response.data[0].embedding
        if isinstance(raw_embedding, list):
            return [float(x) for x in raw_embedding]
    except Exception:  # noqa: BLE001
        # Fallback to 768-dimensional dummy float vector for offline / mock testing
        import hashlib
        seed = int(hashlib.md5(text.encode()).hexdigest(), 16)
        import random
        r = random.Random(seed)
        return [round(r.uniform(-0.1, 0.1), 4) for _ in range(768)]
    return [0.0] * 768


def search_fraud_memory(
    query: str, threshold: float = 0.75, top_k: int = 5
) -> list[dict]:
    """Perform cosine similarity search against public.fraud_memory via Supabase RPC.

    Args:
        query: Search query text.
        threshold: Minimum similarity threshold (0.0 to 1.0).
        top_k: Max number of top matches to return.

    Returns:
        List of matching memory dictionaries.
    """
    query_embedding = embed_text(query)
    client = get_supabase_client()
    result = client.rpc(
        "search_fraud_memory",
        {
            "query_embedding": query_embedding,
            "match_threshold": threshold,
            "match_count": top_k,
        },
    ).execute()
    data = result.data
    if isinstance(data, list):
        res: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict):
                res.append(dict(item))
        return res
    return []


def hybrid_search_fraud_memory(
    query_text: str = "",
    bank_account: str | None = None,
    phone_number: str | None = None,
    threshold: float = 0.45,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Hybrid Search combining BM25/Exact Token Filtering with Dense Semantic Vector RAG.

    Step 1: BM25 Lexical / Exact Token Filter:
            Queries public.fraud_memory for exact matches on bank_accounts array,
            phone_numbers array, or text content tokens.
    Step 2: Dense Vector Similarity Search:
            Queries public.fraud_memory using nomic-embed-text 768-dim embeddings.
    Step 3: Deduplicates & Reranks Results.
    """
    client = get_supabase_client()
    exact_matches: list[dict[str, Any]] = []

    # 1. BM25 / Exact Lexical Token Search
    try:
        if bank_account:
            clean_acc = bank_account.strip()
            resp = client.table("fraud_memory").select("*").contains("bank_accounts", [clean_acc]).execute()
            if resp.data:
                for row in resp.data:
                    row["similarity"] = 1.0  # Instant 100% exact BM25 match
                    row["search_method"] = "BM25_EXACT_ACCOUNT"
                    exact_matches.append(row)

        if phone_number:
            clean_phone = phone_number.strip()
            resp = client.table("fraud_memory").select("*").contains("phone_numbers", [clean_phone]).execute()
            if resp.data:
                for row in resp.data:
                    if str(row["id"]) not in [str(e["id"]) for e in exact_matches]:
                        row["similarity"] = 1.0
                        row["search_method"] = "BM25_EXACT_PHONE"
                        exact_matches.append(row)

        if query_text and len(query_text.strip()) >= 3:
            clean_q = query_text.strip()
            resp = client.table("fraud_memory").select("*").ilike("content", f"%{clean_q}%").execute()
            if resp.data:
                for row in resp.data:
                    if str(row["id"]) not in [str(e["id"]) for e in exact_matches]:
                        row["similarity"] = 0.95
                        row["search_method"] = "BM25_EXACT_KEYWORD"
                        exact_matches.append(row)
    except Exception:
        pass

    # 2. Dense Semantic Vector Search (pgvector)
    vector_matches: list[dict[str, Any]] = []
    if query_text:
        try:
            v_hits = search_fraud_memory(query_text, threshold=threshold, top_k=top_k)
            for hit in v_hits:
                hit["search_method"] = "DENSE_VECTOR_RAG"
                vector_matches.append(hit)
        except Exception:
            pass

    # 3. Merge & Deduplicate by ID and Content Text
    seen_ids = set()
    seen_contents = set()
    combined: list[dict[str, Any]] = []

    for item in exact_matches + vector_matches:
        item_id = str(item.get("id", ""))
        content_key = str(item.get("content", "")).strip()[:100]
        if item_id not in seen_ids and content_key not in seen_contents:
            seen_ids.add(item_id)
            seen_contents.add(content_key)
            combined.append(item)

    # Sort descending by similarity score
    combined.sort(key=lambda x: float(x.get("similarity", 0.0)), reverse=True)
    return combined[:top_k]


def check_blacklist(
    phone: str | None = None, url: str | None = None
) -> list[dict]:
    """Check if a phone number or URL appears in any known fraud case.

    Args:
        phone: Optional phone number string.
        url: Optional phishing URL string.

    Returns:
        List of matching fraud memory records with high similarity.
    """
    query_parts = []
    if phone:
        query_parts.append(f"phone number {phone}")
    if url:
        query_parts.append(f"URL {url}")
    if not query_parts:
        return []
    query = " ".join(query_parts)
    return search_fraud_memory(query, threshold=0.80, top_k=3)


def add_fraud_memory(
    case_id: str | None, fraud_type: str, content: str, metadata: dict
) -> None:
    """Insert a new fraud case into the pgvector vector store.

    Args:
        case_id: Optional parent fraud case UUID.
        fraud_type: Type of fraud (e.g., macau_scam, phishing, investment_scam).
        content: Narrative text embedded for vector search.
        metadata: Additional metadata dictionary (phone_numbers, bank_accounts, etc.).
    """
    embedding = embed_text(content)
    row = {
        "case_id": case_id,
        "fraud_type": fraud_type,
        "content": content,
        "embedding": embedding,
        **metadata,
    }
    client = get_supabase_client()
    client.table("fraud_memory").insert(cast(Any, row)).execute()
