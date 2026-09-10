/**
 * Screen A centre panel — the organisational nervous system.
 * Also exported as `NerveMap` (shared component name).
 *
 * GOVERNING RULE: every pulse and every travelling dot below is triggered by a
 * real ns_event arriving in the store. There is no setInterval, no CSS
 * keyframe loop, no fake heartbeat. If the backend is silent, this is still.
 */

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { selectLatestByLayer, useEventStore } from "../store/useEventStore";
import type { Layer, NsEvent } from "../types/events";

interface LayerNode {
  id: string;
  label: string;
  layer: Layer;
  x: number;
  y: number;
  w?: number;
}

export const NODES: LayerNode[] = [
  { id: "sensing", label: "SENSING", layer: "sensing", x: 90, y: 42 },
  { id: "case", label: "CASE", layer: "case", x: 250, y: 42 },
  { id: "discovery", label: "DISCOVERY", layer: "discovery", x: 415, y: 42 },
  { id: "compiler", label: "COMPILER", layer: "compiler", x: 625, y: 120 },
  { id: "registry", label: "REGISTRY", layer: "registry", x: 415, y: 120 },
  { id: "propagation", label: "PROPAGATION", layer: "propagation", x: 180, y: 120 },
];

export const EDGES: [string, string][] = [
  ["sensing", "case"],
  ["case", "discovery"],
  ["discovery", "compiler"],
  ["compiler", "registry"],
  ["registry", "propagation"],
];

interface WorkerNode {
  id: string;
  label: string;
  x: number;
  y: number;
}

export const WORKERS: WorkerNode[] = [
  { id: "phone_agent", label: "Phone", x: 60, y: 205 },
  { id: "fraud_ops", label: "FraudOps", x: 160, y: 205 },
  { id: "phishing_agent", label: "Phishing", x: 260, y: 205 },
  { id: "txn_monitor", label: "Txn", x: 360, y: 205 },
];

/**
 * Backend agent name -> worker node id.
 *
 * The propagation layer names its subscribers `phone_worker` /
 * `phishing_worker` / `financial_worker` (SUBSCRIPTION_MAP in
 * backend/src/enterprise/propagation.py). The node ids here predate that
 * vocabulary and share no member with it, so a live propagation event
 * resolved nothing before this map existed. Identity entries let a payload
 * that already speaks node ids — the recorded REPLAY corpus — pass through
 * unchanged, which is why REPLAY lit up while LIVE stayed dark.
 */
const AGENT_TO_WORKER: Record<string, string> = {
  phone_worker: "phone_agent",
  phishing_worker: "phishing_agent",
  financial_worker: "txn_monitor",
  phone_agent: "phone_agent",
  phishing_agent: "phishing_agent",
  txn_monitor: "txn_monitor",
  fraud_ops: "fraud_ops",
};

/**
 * Resolve the worker node a propagation event refers to.
 *
 * Reads both `agent` (recorded corpus) and `agent_name` (live backend).
 * Returns null for an unrecognised agent rather than a falsy id, so an
 * unmapped name stays visibly dark instead of silently matching node zero.
 */
export function workerIdForEvent(event: NsEvent): string | null {
  const payload = event.payload as Record<string, unknown> | undefined;
  const raw = String(payload?.agent ?? payload?.agent_name ?? "");
  return AGENT_TO_WORKER[raw] ?? null;
}

const EXPOSURE = { id: "exposure", label: "MCP · CodeBuddy", x: 610, y: 205 };

const NODE_W = 116;
const NODE_H = 34;
const WORKER_W = 88;
const WORKER_H = 26;

interface Pulse {
  key: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

function centre(id: string): { x: number; y: number } | null {
  const n = NODES.find((x) => x.id === id);
  if (n) return { x: n.x, y: n.y };
  const w = WORKERS.find((x) => x.id === id);
  if (w) return { x: w.x, y: w.y };
  if (id === EXPOSURE.id) return { x: EXPOSURE.x, y: EXPOSURE.y };
  return null;
}

/** Which edge carried this event: the edge whose destination is the event layer. */
export function edgeForEvent(event: NsEvent): [string, string] | null {
  const edge = EDGES.find(([, dst]) => dst === event.layer);
  if (edge) return edge;
  if (event.layer === "exposure") return ["registry", EXPOSURE.id];
  return null;
}

export function NervousSystem() {
  const events = useEventStore((s) => s.events);
  const lastEvent = useEventStore((s) => s.lastEvent);
  const [pulses, setPulses] = useState<Pulse[]>([]);
  const seen = useRef<number | null>(null);

  const latestByLayer = selectLatestByLayer(events);
  const maxId = events.length ? Math.max(...events.map((e) => e.id)) : 0;

  // A travelling dot is emitted exactly once per arriving event.
  useEffect(() => {
    if (!lastEvent || seen.current === lastEvent.id) return;
    seen.current = lastEvent.id;

    const newPulses: Pulse[] = [];
    const edge = edgeForEvent(lastEvent);
    if (edge) {
      const a = centre(edge[0]);
      const b = centre(edge[1]);
      if (a && b)
        newPulses.push({ key: `e-${lastEvent.id}`, x1: a.x, y1: a.y, x2: b.x, y2: b.y });
    }

    if (lastEvent.layer === "propagation") {
      const workerId = workerIdForEvent(lastEvent);
      const worker = WORKERS.find((w) => w.id === workerId);
      if (worker) {
        const src = centre("propagation")!;
        newPulses.push({
          key: `w-${lastEvent.id}`,
          x1: src.x,
          y1: src.y,
          x2: worker.x,
          y2: worker.y,
        });
      }
    }

    if (newPulses.length) setPulses((cur) => [...cur, ...newPulses]);
  }, [lastEvent]);

  const removePulse = (key: string) =>
    setPulses((cur) => cur.filter((p) => p.key !== key));

  const heatFor = (layer: Layer): number => {
    const evt = latestByLayer[layer];
    if (!evt || maxId === 0) return 0;
    const distance = maxId - evt.id;
    return Math.max(0, 1 - distance / 8);
  };

  const lastPropagationAgents = new Set(
    events
      .filter((e) => e.layer === "propagation")
      .map((e) => workerIdForEvent(e))
      .filter((id): id is string => id !== null),
  );

  const exposureHeat = heatFor("exposure");

  return (
    <div className="panel nerve" data-testid="nervous-system">
      <div className="panel-title">
        ORGANISATIONAL NERVOUS SYSTEM
        <span className="muted" style={{ marginLeft: "auto", letterSpacing: 0 }}>
          nodes pulse · edges animate on real events
        </span>
      </div>
      <div className="panel-body">
        <svg viewBox="0 0 760 250" className="nerve-svg" width="100%" height="100%">
          {/* static wiring */}
          {EDGES.map(([src, dst]) => {
            const a = centre(src)!;
            const b = centre(dst)!;
            return (
              <line
                key={`${src}-${dst}`}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke="#232a38"
                strokeWidth={2}
              />
            );
          })}
          {WORKERS.map((w) => {
            const p = centre("propagation")!;
            return (
              <line
                key={`prop-${w.id}`}
                x1={p.x}
                y1={p.y}
                x2={w.x}
                y2={w.y}
                stroke="#1b2230"
                strokeWidth={1.5}
              />
            );
          })}
          <line
            x1={415}
            y1={120}
            x2={EXPOSURE.x}
            y2={EXPOSURE.y}
            stroke="#1b2230"
            strokeWidth={1.5}
            strokeDasharray="4 4"
          />

          {/* travelling dots — one per real event */}
          <AnimatePresence>
            {pulses.map((p) => (
              <motion.circle
                key={p.key}
                r={4}
                fill="#FFB74D"
                initial={{ cx: p.x1, cy: p.y1, opacity: 1 }}
                animate={{ cx: p.x2, cy: p.y2, opacity: 0.15 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.55, ease: "easeInOut" }}
                onAnimationComplete={() => removePulse(p.key)}
              />
            ))}
          </AnimatePresence>

          {/* layer nodes */}
          {NODES.map((node) => {
            const evt = latestByLayer[node.layer];
            const heat = heatFor(node.layer);
            const lit = heat > 0.05;
            return (
              <motion.g
                key={`${node.id}-${evt?.id ?? "idle"}`}
                initial={{ scale: 1 }}
                animate={{ scale: evt ? [1, 1.15, 1] : 1 }}
                transition={{ duration: 0.4 }}
                style={{ transformOrigin: `${node.x}px ${node.y}px` }}
                data-layer={node.layer}
                data-active={lit ? "true" : "false"}
              >
                <rect
                  x={node.x - NODE_W / 2}
                  y={node.y - NODE_H / 2}
                  width={NODE_W}
                  height={NODE_H}
                  rx={6}
                  fill={lit ? "#FFB74D" : "#1A1F2E"}
                  fillOpacity={lit ? 0.25 + 0.75 * heat : 1}
                  stroke={lit ? "#FFB74D" : "#232a38"}
                  strokeWidth={1.5}
                />
                <text
                  x={node.x}
                  y={node.y + 4}
                  textAnchor="middle"
                  fill={heat > 0.6 ? "#0A0E14" : lit ? "#FFB74D" : "#9E9E9E"}
                  fontSize={11}
                  fontFamily="var(--mono)"
                  letterSpacing="1.2"
                >
                  {node.label}
                </text>
              </motion.g>
            );
          })}

          {/* reprogrammed workers */}
          {WORKERS.map((w) => {
            const consumed = lastPropagationAgents.has(w.id);
            return (
              <g key={w.id} data-worker={w.id} data-consumed={consumed ? "true" : "false"}>
                <rect
                  x={w.x - WORKER_W / 2}
                  y={w.y - WORKER_H / 2}
                  width={WORKER_W}
                  height={WORKER_H}
                  rx={4}
                  fill={consumed ? "rgba(76,175,80,0.18)" : "#11161f"}
                  stroke={consumed ? "#4CAF50" : "#232a38"}
                />
                <text
                  x={w.x}
                  y={w.y + 4}
                  textAnchor="middle"
                  fill={consumed ? "#4CAF50" : "#6b7280"}
                  fontSize={10}
                  fontFamily="var(--mono)"
                >
                  {w.label}
                </text>
              </g>
            );
          })}

          {/* exposure — third-party callers over MCP */}
          <g data-layer="exposure" data-active={exposureHeat > 0.05 ? "true" : "false"}>
            <rect
              x={EXPOSURE.x - 78}
              y={EXPOSURE.y - 16}
              width={156}
              height={32}
              rx={6}
              fill={exposureHeat > 0.05 ? "rgba(79,195,247,0.18)" : "#11161f"}
              stroke={exposureHeat > 0.05 ? "#4FC3F7" : "#232a38"}
              strokeDasharray="4 3"
            />
            <text
              x={EXPOSURE.x}
              y={EXPOSURE.y + 4}
              textAnchor="middle"
              fill={exposureHeat > 0.05 ? "#4FC3F7" : "#6b7280"}
              fontSize={10}
              fontFamily="var(--mono)"
            >
              {EXPOSURE.label}
            </text>
          </g>

          <text
            x={610}
            y={238}
            textAnchor="middle"
            fill="#4b5563"
            fontSize={9}
            fontFamily="var(--mono)"
          >
            external agentic system — produces its own artifacts
          </text>
        </svg>
      </div>
    </div>
  );
}

export const NerveMap = NervousSystem;
export default NervousSystem;
