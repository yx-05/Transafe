"""Discovery orchestrator — L3.

Trigger policy: **event-driven incremental on every case ingest, with a
30-second debounce, plus a 5-minute periodic sweep.**

* Batch-nightly would defeat the thesis — the promise is minutes, not weeks.
* Pure on-ingest with no debounce re-clusters 14 times during a 14-case burst.
* On-ingest + debounce + sweep is the default.

Everything here runs downstream of the v1 pipeline. Nothing in this module may
be awaited on the live call path.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from src.db.vector_store import get_supabase_client
from src.enterprise.clustering import (
    NOVELTY_THRESHOLD,
    check_promotion_gates,
    cluster_components,
    compute_campaign_embedding,
    summarise_component,
)
from src.enterprise.events import emit_event
from src.enterprise.linkage import (
    _narrative_similarity,
    compute_blocking_keys,
    get_candidate_pairs,
    score_case_pair,
)

logger = logging.getLogger(__name__)

# Debounce window after the last ingest before re-clustering.
DEBOUNCE_SECONDS = 30
# Periodic sweep interval — catches slow-forming clusters.
SWEEP_INTERVAL_SECONDS = 300
# OBSERVED state thresholds (§6.4.0).
OBSERVED_RISK_TIER = "HIGH"
OBSERVED_CAMPAIGN_COSINE = 0.75
# Linkage threshold for graph edges.
LINK_THRESHOLD = 0.60
# Candidate lookup window.
CANDIDATE_WINDOW_DAYS = 14


class DiscoveryEngine:
    """Orchestrates the discovery pipeline."""

    def __init__(self, store: Any = None) -> None:
        self._store = store
        self._debounce_set: set[str] = set()
        self._debounce_timer: asyncio.TimerHandle | None = None
        self._sweep_task: asyncio.Task[None] | None = None

    @property
    def store(self) -> Any:
        """Lazily construct the GraphStore so import never touches Supabase."""
        if self._store is None:
            from src.enterprise.graph_store import PostgresGraphStore

            self._store = PostgresGraphStore()
        return self._store

    # ── Ingest path ─────────────────────────────────────────────────────────
    async def on_case_ingested(self, case_id: str) -> None:
        """Handle a newly ingested case (post MO extraction + entity resolution).

        Args:
            case_id: UUID of the newly ingested case.
        """
        try:
            await self._check_observed(case_id)
        except Exception:
            logger.exception("discovery: OBSERVED check failed for case %s", case_id)

        try:
            await self._score_candidates(case_id)
        except Exception:
            logger.exception("discovery: candidate scoring failed for case %s", case_id)

        self._debounce_set.add(case_id)

        if self._debounce_timer is not None and not self._debounce_timer.cancelled():
            self._debounce_timer.cancel()
        loop = asyncio.get_running_loop()
        self._debounce_timer = loop.call_later(DEBOUNCE_SECONDS, self._flush_debounce)

    async def _check_observed(self, case_id: str) -> None:
        """Mark a case ``OBSERVED`` when it is high-risk but unexplained.

        A case is OBSERVED when it scores HIGH, its MO narrative matches no
        existing campaign (cosine < 0.75), and it shares no hard identifier
        with any known case. This is not a campaign — it triggers no compiler,
        no artifact, no propagation. It is an honest statement of ignorance.
        """
        client = get_supabase_client()

        case_result = (
            client.table("fraud_cases")
            .select("id, user_id, risk_tier, created_at")
            .eq("id", case_id)
            .execute()
        )
        if not getattr(case_result, "data", None):
            return
        case = case_result.data[0]

        if case.get("risk_tier") != OBSERVED_RISK_TIER:
            return

        mo_result = (
            client.table("case_mo")
            .select("embedding, fingerprint")
            .eq("case_id", case_id)
            .execute()
        )
        if not getattr(mo_result, "data", None):
            return
        case_embedding = mo_result.data[0].get("embedding")

        campaigns = (
            client.table("campaigns")
            .select("id, code, mo_embedding")
            .in_("status", ["APPROVED", "ACTIVE"])
            .execute()
        )
        max_cosine = 0.0
        for campaign in getattr(campaigns, "data", None) or []:
            sim = _narrative_similarity(case_embedding, campaign.get("mo_embedding"))
            if sim and sim > max_cosine:
                max_cosine = sim

        entities_result = (
            client.table("case_entity_links").select("entity_id").eq("case_id", case_id).execute()
        )
        entity_rows = getattr(entities_result, "data", None) or []
        has_shared_id = False
        for link in entity_rows:
            shared = (
                client.table("case_entity_links")
                .select("case_id")
                .eq("entity_id", link["entity_id"])
                .neq("case_id", case_id)
                .limit(1)
                .execute()
            )
            if getattr(shared, "data", None):
                has_shared_id = True
                break

        is_observed = (max_cosine < OBSERVED_CAMPAIGN_COSINE) and not has_shared_id

        client.table("case_discovery_state").upsert(
            {
                "case_id": case_id,
                "state": "OBSERVED" if is_observed else "NORMAL",
                "best_campaign_cosine": round(max_cosine, 3),
                "matched_indicators": len(entity_rows),
                "updated_at": datetime.now(UTC).isoformat(),
            }
        ).execute()

        if is_observed:
            await emit_event(
                layer="discovery",
                event_type="case_observed",
                severity="warning",
                payload={"case_id": case_id, "max_cosine": round(max_cosine, 3)},
            )

    async def _score_candidates(self, case_id: str) -> None:
        """Score blocking-key candidates against a newly ingested case."""
        client = get_supabase_client()

        case_result = client.table("fraud_cases").select("*").eq("id", case_id).execute()
        if not getattr(case_result, "data", None):
            return
        case = case_result.data[0]
        self._attach_mo(client, case, case_id)

        entities = self._load_entities(client, case_id)
        blocking_keys = compute_blocking_keys(case, entities)
        if not blocking_keys:
            return

        candidate_ids = get_candidate_pairs(
            case_id, blocking_keys, self._store, window_days=CANDIDATE_WINDOW_DAYS
        )

        linked = 0
        for cand_id in candidate_ids:
            cand_result = client.table("fraud_cases").select("*").eq("id", cand_id).execute()
            if not getattr(cand_result, "data", None):
                continue
            cand = cand_result.data[0]
            self._attach_mo(client, cand, cand_id)
            cand_entities = self._load_entities(client, cand_id)

            result = score_case_pair(
                case,
                cand,
                entities,
                cand_entities,
                case.get("mo_embedding"),
                cand.get("mo_embedding"),
            )

            if result["score"] >= LINK_THRESHOLD:
                self.store.upsert_link(
                    src=case_id,
                    dst=cand_id,
                    link_type="fused",
                    weight=result["score"],
                    evidence_case_ids=[case_id, cand_id],
                    signals=result["signals"],
                )
                linked += 1
                await emit_event(
                    layer="discovery",
                    event_type="cases_linked",
                    payload={
                        "case_a": min(case_id, cand_id),
                        "case_b": max(case_id, cand_id),
                        "score": result["score"],
                        "signals": list(result["signals"].keys()),
                    },
                )

        if linked:
            logger.info("discovery: case %s linked to %d candidate(s)", case_id, linked)

    @staticmethod
    def _attach_mo(client: Any, case: dict[str, Any], case_id: str) -> None:
        """Attach ``mo_fingerprint`` and ``mo_embedding`` onto a case dict."""
        mo_result = client.table("case_mo").select("*").eq("case_id", case_id).execute()
        rows = getattr(mo_result, "data", None)
        if rows:
            case["mo_fingerprint"] = rows[0].get("fingerprint", {})
            case["mo_embedding"] = rows[0].get("embedding")

    @staticmethod
    def _load_entities(client: Any, case_id: str) -> list[dict[str, Any]]:
        """Load resolved entities for a case."""
        result = (
            client.table("case_entity_links")
            .select("entity_id, entities!inner(entity_type, value_norm, value_raw)")
            .eq("case_id", case_id)
            .execute()
        )
        entities: list[dict[str, Any]] = []
        for row in getattr(result, "data", None) or []:
            ent = row.get("entities")
            if ent:
                entities.append(ent)
        return entities

    # ── Debounce + clustering ───────────────────────────────────────────────
    def _flush_debounce(self) -> None:
        """Flush the debounce set: re-cluster only the affected components."""
        if not self._debounce_set:
            return
        affected = set(self._debounce_set)
        self._debounce_set.clear()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - no loop, nothing to schedule on
            logger.warning("discovery: no running loop to flush debounce set")
            return
        loop.create_task(self._recluster(affected))

    async def _recluster(self, affected_case_ids: set[str]) -> None:
        """Re-cluster the components containing the affected case IDs.

        Args:
            affected_case_ids: Case IDs ingested since the last flush.
        """
        client = get_supabase_client()

        links = self.store.get_all_links(min_score=LINK_THRESHOLD)
        if not links:
            return

        components = cluster_components(links, min_weight=LINK_THRESHOLD)

        existing_campaigns = (
            client.table("campaigns")
            .select("id, mo_embedding")
            .in_("status", ["APPROVED", "ACTIVE"])
            .execute()
        )
        existing_embeddings = getattr(existing_campaigns, "data", None) or []

        target_components = [comp for comp in components if comp & affected_case_ids]
        if not target_components:
            return

        all_case_ids: set[str] = set()
        for comp in target_components:
            all_case_ids |= comp

        cases = self._load_cases(client, all_case_ids)

        for comp in target_components:
            if await self._is_already_clustered(client, comp):
                continue

            gate_result = check_promotion_gates(
                component=comp,
                links=links,
                cases=cases,
                existing_campaign_embeddings=existing_embeddings,
            )

            if gate_result["passes"]:
                await self._propose_campaign(comp, gate_result, cases)
            elif (
                not gate_result["novel"]
                and gate_result["gates"]["novelty"]["best_cosine"] >= NOVELTY_THRESHOLD
            ):
                await self._merge_into_campaign(comp, gate_result, cases)

    @staticmethod
    def _load_cases(client: Any, case_ids: set[str]) -> dict[str, dict[str, Any]]:
        """Load case rows plus their MO fingerprint/embedding."""
        cases: dict[str, dict[str, Any]] = {}
        for cid in sorted(case_ids):
            case_res = (
                client.table("fraud_cases")
                .select("id, user_id, risk_tier, created_at")
                .eq("id", cid)
                .execute()
            )
            rows = getattr(case_res, "data", None)
            if not rows:
                continue
            case = rows[0]
            mo_res = (
                client.table("case_mo")
                .select("embedding, fingerprint")
                .eq("case_id", cid)
                .execute()
            )
            mo_rows = getattr(mo_res, "data", None)
            if mo_rows:
                case["mo_embedding"] = mo_rows[0].get("embedding")
                case["mo_fingerprint"] = mo_rows[0].get("fingerprint", {})
            cases[cid] = case
        return cases

    @staticmethod
    async def _is_already_clustered(client: Any, component: set[str]) -> bool:
        """Return True when every case in the component already sits in a campaign."""
        try:
            result = (
                client.table("campaign_cases")
                .select("case_id")
                .in_("case_id", sorted(component))
                .execute()
            )
        except Exception:
            return False
        rows = getattr(result, "data", None) or []
        try:
            existing = {str(r["case_id"]) for r in rows}
        except (TypeError, KeyError):
            return False
        return bool(existing) and component <= existing

    # ── Campaign lifecycle ──────────────────────────────────────────────────
    async def _propose_campaign(
        self,
        component: set[str],
        gate_result: dict[str, Any],
        cases: dict[str, dict[str, Any]],
    ) -> None:
        """Propose a new campaign candidate for human validation."""
        client = get_supabase_client()
        campaign_embedding = compute_campaign_embedding(component, cases)
        summary = summarise_component(component, cases)

        count_result = client.table("campaigns").select("id").execute()
        existing = getattr(count_result, "data", None) or []
        code = f"SCAM-{len(existing) + 1:03d}"

        name = summary["impersonated_entity"] or "Unnamed pattern"
        campaign_row: dict[str, Any] = {
            "code": code,
            "name": f"{name} — pending validation",
            "status": "PENDING_VALIDATION",
            "confidence": gate_result["confidence"],
            "mo_summary": summary["impersonated_entity"],
            "mo_embedding": campaign_embedding,
            "indicators": summary["script_phases"],
            "case_count": len(component),
            "customer_count": gate_result.get("customer_count", 0),
            "first_seen": summary["first_seen"],
            "last_seen": summary["last_seen"],
        }
        result = client.table("campaigns").insert(campaign_row).execute()
        rows = getattr(result, "data", None)
        if not rows:
            logger.error("discovery: campaign insert returned no row for %s", code)
            return
        campaign_id = rows[0]["id"]

        now = datetime.now(UTC).isoformat()
        for cid in sorted(component):
            client.table("campaign_cases").upsert(
                {
                    "campaign_id": campaign_id,
                    "case_id": cid,
                    "linkage_score": gate_result["confidence"],
                }
            ).execute()
            client.table("case_discovery_state").upsert(
                {"case_id": cid, "state": "CLUSTERED", "updated_at": now}
            ).execute()

        await emit_event(
            layer="discovery",
            event_type="campaign_proposed",
            severity="critical",
            payload={
                "campaign_id": campaign_id,
                "code": code,
                "case_count": len(component),
                "customer_count": gate_result.get("customer_count", 0),
                "confidence": gate_result["confidence"],
                "gates": gate_result.get("gates", {}),
            },
        )

    async def _merge_into_campaign(
        self,
        component: set[str],
        gate_result: dict[str, Any],
        cases: dict[str, dict[str, Any]],
    ) -> None:
        """Merge cases into the existing campaign they duplicate (novelty gate failed)."""
        del cases  # Case bodies are not needed for a merge; membership is.

        client = get_supabase_client()
        novelty = gate_result.get("gates", {}).get("novelty", {})
        matched_id = novelty.get("matched_campaign_id") or gate_result.get("matched_campaign_id")

        campaign: dict[str, Any] | None = None
        if matched_id:
            res = client.table("campaigns").select("id, code").eq("id", matched_id).execute()
            rows = getattr(res, "data", None)
            if rows:
                campaign = rows[0]

        if campaign is None:
            campaigns = (
                client.table("campaigns")
                .select("id, code")
                .in_("status", ["APPROVED", "ACTIVE"])
                .execute()
            )
            rows = getattr(campaigns, "data", None)
            if not rows:
                return
            campaign = rows[0]

        campaign_id = campaign["id"]
        code = campaign.get("code") if hasattr(campaign, "get") else None

        now = datetime.now(UTC).isoformat()
        for cid in sorted(component):
            client.table("campaign_cases").upsert(
                {
                    "campaign_id": campaign_id,
                    "case_id": cid,
                    "linkage_score": gate_result.get("confidence", 0.0),
                }
            ).execute()
            client.table("case_discovery_state").upsert(
                {"case_id": cid, "state": "CLUSTERED", "updated_at": now}
            ).execute()

        new_count = (
            client.table("campaign_cases")
            .select("case_id")
            .eq("campaign_id", campaign_id)
            .execute()
        )
        total = len(getattr(new_count, "data", None) or [])
        client.table("campaigns").update(
            {"case_count": total, "last_seen": now}
        ).eq("id", campaign_id).execute()

        await emit_event(
            layer="discovery",
            event_type="campaign_grew",
            payload={
                "campaign_id": campaign_id,
                "code": code,
                "new_cases": len(component),
                "total_cases": total,
                "best_cosine": novelty.get("best_cosine"),
            },
        )

    # ── Sweeps ──────────────────────────────────────────────────────────────
    async def run_full_sweep(self) -> None:
        """Force a full discovery sweep (used by the demo 'Run Scenario' button).

        Drives the *whole* pipeline, not just clustering. ``_recluster`` reads
        ``case_links``, which is written only by ``_score_candidates``; on a
        freshly seeded database that edge table is empty, so a clustering-only
        sweep found nothing and returned success. The demo's own bootstrap
        button could not bootstrap. Each case therefore goes through the same
        two ingest steps a live case would before clustering runs.

        Deliberately calls ``_check_observed``/``_score_candidates`` rather
        than ``on_case_ingested``: the latter arms the debounce timer, which
        would defer clustering past the caller and leave a stray timer per
        case. A sweep is the explicit flush, so it clusters inline instead.

        Per-case failures are logged and skipped — one unparseable case must
        not abort the sweep — but a sweep that scores cases and still produces
        no links emits a warning event rather than reporting a silent success.
        """
        client = get_supabase_client()
        all_cases = client.table("fraud_cases").select("id").execute()
        all_ids = {str(c["id"]) for c in (getattr(all_cases, "data", None) or [])}

        scored = 0
        for case_id in sorted(all_ids):
            try:
                await self._check_observed(case_id)
            except Exception:
                logger.exception("discovery: sweep OBSERVED check failed for case %s", case_id)
            try:
                await self._score_candidates(case_id)
                scored += 1
            except Exception:
                logger.exception("discovery: sweep candidate scoring failed for case %s", case_id)

        if all_ids:
            logger.info("discovery: full sweep scored %d/%d case(s)", scored, len(all_ids))

        await self._recluster(all_ids)

        # A populated case table that yields no edges is a real signal, not a
        # success. Surface it instead of letting the dashboard show a clean run.
        if all_ids and not self.store.get_all_links(min_score=LINK_THRESHOLD):
            logger.warning(
                "discovery: sweep over %d case(s) produced no links above %.2f",
                len(all_ids),
                LINK_THRESHOLD,
            )
            await emit_event(
                layer="discovery",
                event_type="discovery_sweep_empty",
                severity="warning",
                payload={"cases_scanned": len(all_ids), "link_threshold": LINK_THRESHOLD},
            )

    async def start_periodic_sweep(self) -> None:
        """Run the 5-minute periodic sweep loop until cancelled."""
        while True:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            try:
                client = get_supabase_client()
                cutoff = (datetime.now(UTC) - timedelta(days=CANDIDATE_WINDOW_DAYS)).isoformat()
                recent = (
                    client.table("fraud_cases").select("id").gte("created_at", cutoff).execute()
                )
                recent_ids = {str(c["id"]) for c in (getattr(recent, "data", None) or [])}
            except Exception:
                logger.exception("discovery: periodic sweep query failed")
                continue

            if not recent_ids:
                continue
            try:
                await self._recluster(recent_ids)
            except Exception:
                logger.exception("discovery: periodic sweep recluster failed")

    def start(self) -> None:
        """Start the background sweep task (idempotent)."""
        if self._sweep_task is not None and not self._sweep_task.done():
            return
        self._sweep_task = asyncio.create_task(self.start_periodic_sweep())

    async def stop(self) -> None:
        """Cancel the sweep task and any pending debounce timer."""
        if self._debounce_timer is not None and not self._debounce_timer.cancelled():
            self._debounce_timer.cancel()
        self._debounce_timer = None
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sweep_task
            self._sweep_task = None


_engine: DiscoveryEngine | None = None


def get_discovery_engine() -> DiscoveryEngine:
    """Return the process-wide DiscoveryEngine singleton."""
    global _engine
    if _engine is None:
        _engine = DiscoveryEngine()
    return _engine
