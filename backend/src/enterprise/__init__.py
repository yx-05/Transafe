"""TranSafe v2 — Enterprise layer.

The enterprise layer wraps v1: every module here is asynchronous and strictly
downstream of the live call/transaction pipeline. Nothing in this package may
be imported into the v1 hot path.

Modules
-------
events           ns_events emitter + in-process WebSocket fan-out (B0)
mo_extractor     Modus-Operandi fingerprint extraction, post-call (B1)
entity_resolver  Entity normalisation + resolution (B1)
graph_store      GraphStore protocol + Postgres implementation (B2)
linkage          Deterministic 4-signal case-pair scoring, noisy-OR fusion (B2)
clustering       Connected-component clustering + promotion gates (B2)
discovery        Orchestrator: on-ingest trigger, debounce, periodic sweep (B2)
"""
