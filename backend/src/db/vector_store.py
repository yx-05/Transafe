"""pgvector Vector Store Helper for TranSafe Fraud Memory.

Uses Alibaba Cloud DashScope for embeddings (China-accessible, 768-dim compatible).
DeepSeek API does not offer an embeddings endpoint, so DashScope's text-embedding-v3
is used instead — it supports 768-dimensional output to match the existing pgvector schema.
"""

import logging
import os
import threading
from typing import Any, cast

from pydantic import BaseModel
from supabase import Client, create_client

logger = logging.getLogger(__name__)

# Lazy-initialized clients
_dashscope_client: Any | None = None


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


#: An explicitly injected client (tests, or a caller building its own).
#: When set, it is returned as-is and nothing thread-local is created.
supabase_client: Client | None = None

#: One Supabase client per thread.
#:
#: ``supabase.Client`` wraps a **synchronous** httpx client, and httpx sync
#: clients are not safe for concurrent use. The enterprise API runs every query
#: in an ``asyncio.to_thread`` worker — 25 call sites in
#: ``src/api/enterprise/router.py`` alone — so a single module-level client was
#: being driven from many threads at once. Under that load the HTTP/2 stream
#: corrupts and the peer terminates the connection, which surfaces as
#: ``httpx.ReadError: [Errno 35] Resource temporarily unavailable`` and
#: ``httpcore.RemoteProtocolError: <ConnectionTerminated ...>``.
#:
#: It went unnoticed because the failure is *survivable*: the API degrades to an
#: empty result rather than erroring, so the console rendered zeroed counters
#: instead of reporting a fault. A per-thread client removes the shared mutable
#: state that made concurrency unsafe in the first place.
_thread_local = threading.local()


def _client_from_env() -> Client | None:
    """Build a fresh Supabase client from the environment, or None if unset."""
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if supabase_url and supabase_key:
        return create_client(supabase_url, supabase_key)
    return None


def init_vector_store() -> None:
    """Initialize the DashScope and Supabase clients.

    Retained for callers that want one eagerly-built client. Prefer
    :func:`get_supabase_client`, which hands each thread its own.
    """
    global _dashscope_client, supabase_client
    client = _client_from_env()
    if client is not None:
        supabase_client = client


def get_supabase_client() -> Client:
    """Return a Supabase client that is safe to use from the calling thread.

    An explicitly set module-level ``supabase_client`` wins, so tests and
    callers that inject their own are unaffected. Otherwise each thread lazily
    builds and keeps its own client.

    Returns:
        A Supabase client bound to this thread.

    Raises:
        RuntimeError: If Supabase has not been configured.
    """
    if supabase_client is not None:
        return supabase_client

    client = getattr(_thread_local, "client", None)
    if client is None:
        client = _client_from_env()
        if client is None:
            raise RuntimeError("Supabase client is not initialized.")
        _thread_local.client = client
    return client


def embed_text(text: str) -> list[float]:
    """Generate 768-dimensional text embedding via Alibaba DashScope text-embedding-v3.

    Falls back to a deterministic dummy vector for offline / mock testing when
    no DashScope API key is available.

    Args:
        text: Input string to embed.

    Returns:
        List of 768 float values.
    """
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        # Fallback to 768-dimensional deterministic dummy vector for offline / mock testing
        import hashlib
        import random
        seed = int(hashlib.md5(text.encode()).hexdigest(), 16)
        r = random.Random(seed)
        return [round(r.uniform(-0.1, 0.1), 4) for _ in range(768)]

    try:
        import httpx
        base_url = os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        response = httpx.post(
            f"{base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.getenv("DASHSCOPE_EMBEDDING_MODEL", "qwen3.7-text-embedding"),
                "input": text,
                "dimensions": 768,
                "encoding_format": "float",
            },
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        raw_embedding = data["data"][0]["embedding"]
        if isinstance(raw_embedding, list):
            return [float(x) for x in raw_embedding]
    except Exception:  # noqa: BLE001
        # Fallback to 768-dimensional deterministic dummy vector
        import hashlib
        import random
        seed = int(hashlib.md5(text.encode()).hexdigest(), 16)
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
            Queries public.fraud_memory using 768-dim embeddings.
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
        fraud_type: Type of fraud (e.g. macau_scam, phishing, investment_scam).
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
