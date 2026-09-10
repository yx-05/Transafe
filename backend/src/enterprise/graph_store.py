"""Graph store — L3.

The Scam Graph is a knowledge graph stored in **Postgres**, behind a
``GraphStore`` interface. Not Neo4j: at ~200-400 nodes and ~500-1,500 edges,
Postgres + in-memory ``networkx`` is ~1 ms, while a graph DB adds a network hop
and dual-write consistency for zero gain. The seam stays open for a Neo4j
adapter (~120 lines) if volume ever justifies it.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from src.db.vector_store import get_supabase_client

logger = logging.getLogger(__name__)


class Entity:
    """A resolved graph node."""

    def __init__(
        self,
        id: str,  # noqa: A002 - matches the documented public API
        entity_type: str,
        value_norm: str,
        value_raw: str = "",
        case_count: int = 0,
    ) -> None:
        self.id = id
        self.entity_type = entity_type
        self.value_norm = value_norm
        self.value_raw = value_raw
        self.case_count = case_count

    def to_dict(self) -> dict[str, Any]:
        """Serialise the node for API responses."""
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "value_norm": self.value_norm,
            "value_raw": self.value_raw,
            "case_count": self.case_count,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Entity({self.entity_type}:{self.value_norm})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entity):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


class GraphStore(Protocol):
    """Storage interface for the Scam Graph."""

    def upsert_entity(self, entity_type: str, value_norm: str, value_raw: str = "") -> str:
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
        """Upsert a typed, weighted edge between two case nodes."""
        ...

    def neighbours(self, entity_id: str, depth: int = 1) -> list[Entity]:
        """Return entity nodes within ``depth`` hops of ``entity_id``."""
        ...

    def components(self, min_weight: float) -> list[set[str]]:
        """Return connected components (case IDs) with edges >= ``min_weight``."""
        ...

    def case_links(self, case_id: str, min_score: float = 0.0) -> list[dict[str, Any]]:
        """Return all case-pair links involving ``case_id``."""
        ...

    def get_all_links(self, min_score: float = 0.0) -> list[dict[str, Any]]:
        """Return all case-pair links above threshold."""
        ...


class PostgresGraphStore:
    """``GraphStore`` implementation backed by Supabase/Postgres."""

    def __init__(self, client: Any = None) -> None:
        self._client = client if client is not None else get_supabase_client()

    # ── Nodes ────────────────────────────────────────────────────────────────
    def upsert_entity(self, entity_type: str, value_norm: str, value_raw: str = "") -> str:
        """Upsert an entity node and return its UUID (``""`` on failure)."""
        result = (
            self._client.table("entities")
            .upsert(
                {
                    "entity_type": entity_type,
                    "value_norm": value_norm,
                    "value_raw": value_raw or value_norm,
                },
                on_conflict="entity_type,value_norm",
            )
            .execute()
        )
        data = getattr(result, "data", None)
        return data[0]["id"] if data else ""

    # ── Edges ────────────────────────────────────────────────────────────────
    def upsert_link(
        self,
        src: str,
        dst: str,
        link_type: str,
        weight: float,
        evidence_case_ids: list[str],
        signals: dict[str, Any] | None = None,
    ) -> None:
        """Upsert a case-pair edge.

        ``case_a < case_b`` is enforced (the table has a CHECK constraint), so
        an edge is stored exactly once regardless of argument order.
        """
        payload_signals: dict[str, Any] = {
            "link_type": link_type,
            "evidence_case_ids": evidence_case_ids,
        }
        if signals:
            payload_signals.update(signals)

        self._client.table("case_links").upsert(
            {
                "case_a": min(src, dst),
                "case_b": max(src, dst),
                "score": weight,
                "signals": payload_signals,
            },
            on_conflict="case_a,case_b",
        ).execute()

    def neighbours(self, entity_id: str, depth: int = 1) -> list[Entity]:
        """Return entity nodes within ``depth`` hops via the ``graph_neighbours`` RPC."""
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
            for r in (getattr(result, "data", None) or [])
        ]

    def components(self, min_weight: float) -> list[set[str]]:
        """Compute connected components in memory via ``networkx``."""
        import networkx as nx

        links = self.get_all_links(min_score=min_weight)
        graph = nx.Graph()
        for link in links:
            graph.add_edge(link["case_a"], link["case_b"], weight=link["score"])
        return [set(comp) for comp in nx.connected_components(graph)]

    def case_links(self, case_id: str, min_score: float = 0.0) -> list[dict[str, Any]]:
        """Return all case-pair links involving ``case_id``."""
        result = (
            self._client.table("case_links")
            .select("*")
            .or_(f"case_a.eq.{case_id},case_b.eq.{case_id}")
            .gte("score", min_score)
            .execute()
        )
        return list(getattr(result, "data", None) or [])

    def get_all_links(self, min_score: float = 0.0) -> list[dict[str, Any]]:
        """Return every case-pair link scoring at or above ``min_score``."""
        result = (
            self._client.table("case_links").select("*").gte("score", min_score).execute()
        )
        return list(getattr(result, "data", None) or [])

    # ── Read helpers used by the API layer ───────────────────────────────────
    def get_entities(self, limit: int = 500) -> list[Entity]:
        """Return entity nodes for the graph visualiser."""
        result = (
            self._client.table("entities")
            .select("id, entity_type, value_norm, value_raw, case_count")
            .limit(limit)
            .execute()
        )
        return [
            Entity(
                id=r["id"],
                entity_type=r["entity_type"],
                value_norm=r["value_norm"],
                value_raw=r.get("value_raw", ""),
                case_count=r.get("case_count", 0),
            )
            for r in (getattr(result, "data", None) or [])
        ]

    def get_case_entity_links(self, case_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Return case→entity membership rows, optionally filtered by case."""
        query = self._client.table("case_entity_links").select("case_id, entity_id, source")
        if case_ids:
            query = query.in_("case_id", case_ids)
        result = query.execute()
        return list(getattr(result, "data", None) or [])
