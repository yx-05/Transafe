/**
 * Screen C — the Scam Graph.
 *
 * Force-directed, full-bleed. Cases are small grey dots, entities are squares
 * coloured by type, campaigns are translucent hulls. Edge thickness = fused
 * weight. Hover any edge and it tells you why it exists.
 *
 * New nodes appear because a real ns_event told us to re-fetch — the "cluster
 * tightening" during the wave is the force simulation reacting to real data.
 */

import { Suspense, lazy, useCallback, useMemo, useRef, useState } from "react";
import type { GraphData, GraphLink, GraphNode } from "../types/campaign";

const ForceGraph2D = lazy(() => import("react-force-graph-2d"));

const ENTITY_COLOURS: Record<string, string> = {
  PHONE: "#4FC3F7",
  ACCOUNT: "#4CAF50",
  URL: "#FFB74D",
  DOMAIN: "#EF5350",
  NAME: "#B39DDB",
  OTHER: "#9E9E9E",
};

export function nodeColour(node: GraphNode): string {
  if (node.kind === "case") return "#8a94a6";
  if (node.kind === "campaign") return "rgba(255,183,77,0.35)";
  return ENTITY_COLOURS[node.entity_type ?? "OTHER"] ?? "#9E9E9E";
}

export function linkWidth(link: GraphLink): number {
  if (link.kind === "case-case") return 0.6 + link.weight * 4;
  if (link.kind === "campaign-case") return 0.6;
  return 0.8;
}

export function linkColour(link: GraphLink, hovered: boolean): string {
  if (hovered) return "#FFB74D";
  if (link.kind === "case-case") return `rgba(255,183,77,${0.2 + link.weight * 0.5})`;
  if (link.kind === "campaign-case") return "rgba(255,183,77,0.15)";
  return "rgba(120,132,150,0.35)";
}

interface Props {
  data: GraphData;
  onSelectCase?: (caseId: string) => void;
  focusId?: string | null;
}

interface SimNode extends GraphNode {
  x?: number;
  y?: number;
}

export function ScamGraph({ data, onSelectCase, focusId }: Props) {
  const [hoverLink, setHoverLink] = useState<GraphLink | null>(null);
  const [hoverNode, setHoverNode] = useState<GraphNode | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const graphData = useMemo(
    () => ({
      nodes: data.nodes.map((n) => ({ ...n })),
      links: data.links.map((l) => ({ ...l })),
    }),
    [data],
  );

  const paintNode = useCallback(
    (node: SimNode, ctx: CanvasRenderingContext2D, scale: number) => {
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const focused = focusId && node.id === focusId;

      if (node.kind === "campaign") {
        const r = 26;
        ctx.beginPath();
        ctx.arc(x, y, r, 0, 2 * Math.PI);
        ctx.fillStyle = "rgba(255,183,77,0.10)";
        ctx.fill();
        ctx.strokeStyle = "rgba(255,183,77,0.5)";
        ctx.lineWidth = 1 / scale;
        ctx.stroke();
        ctx.fillStyle = "#FFB74D";
        ctx.font = `${10 / scale}px monospace`;
        ctx.textAlign = "center";
        ctx.fillText(node.label, x, y - r - 4 / scale);
        return;
      }

      if (node.kind === "entity") {
        const s = 8;
        ctx.fillStyle = nodeColour(node);
        ctx.fillRect(x - s / 2, y - s / 2, s, s);
        if (focused) {
          ctx.strokeStyle = "#FFB74D";
          ctx.lineWidth = 2 / scale;
          ctx.strokeRect(x - s, y - s, s * 2, s * 2);
        }
        ctx.fillStyle = "#9E9E9E";
        ctx.font = `${9 / scale}px monospace`;
        ctx.textAlign = "center";
        ctx.fillText(node.label, x, y + s + 7 / scale);
        return;
      }

      // case
      const risk = node.risk_score ?? 0;
      ctx.beginPath();
      ctx.arc(x, y, 3.2, 0, 2 * Math.PI);
      ctx.fillStyle = risk >= 75 ? "#EF5350" : risk >= 50 ? "#FFB74D" : "#8a94a6";
      ctx.fill();
      if (focused) {
        ctx.strokeStyle = "#FFB74D";
        ctx.lineWidth = 1.5 / scale;
        ctx.stroke();
      }
    },
    [focusId],
  );

  return (
    <div className="graph-wrap" ref={containerRef} data-testid="scam-graph">
      {hoverLink && (
        <div className="graph-tooltip" data-testid="edge-tooltip">
          {hoverLink.reason}
        </div>
      )}
      {!hoverLink && hoverNode && (
        <div className="graph-tooltip" data-testid="node-tooltip">
          {hoverNode.kind.toUpperCase()} · {hoverNode.label}
          {hoverNode.case_count !== undefined ? ` · ${hoverNode.case_count} cases` : ""}
        </div>
      )}

      <div className="graph-legend">
        <div>
          <span className="swatch" style={{ background: "#8a94a6", borderRadius: "50%" }} />
          case
        </div>
        {Object.entries(ENTITY_COLOURS)
          .slice(0, 4)
          .map(([type, colour]) => (
            <div key={type}>
              <span className="swatch" style={{ background: colour }} />
              {type}
            </div>
          ))}
        <div>
          <span
            className="swatch"
            style={{ background: "rgba(255,183,77,0.35)", borderRadius: "50%" }}
          />
          campaign hull
        </div>
        <div className="muted">edge thickness = fused weight · hover an edge for why</div>
      </div>

      {graphData.nodes.length === 0 ? (
        // An empty graph is a real answer, not a pending one. Say so rather
        // than spinning on a canvas that will never fill.
        <p className="empty-state" data-testid="graph-empty">
          no linked cases yet — the graph draws itself as entities are extracted
          and cases start sharing them
        </p>
      ) : (
        <Suspense fallback={<p className="empty-state">loading graph…</p>}>
          <ForceGraph2D
          graphData={graphData as never}
          backgroundColor="#0A0E14"
          nodeRelSize={4}
          nodeLabel={() => ""}
          nodeCanvasObject={paintNode as never}
          linkWidth={((l: GraphLink) => linkWidth(l)) as never}
          linkColor={
            ((l: GraphLink) => linkColour(l, hoverLink === l)) as never
          }
          linkLineDash={
            ((l: GraphLink) => (l.kind === "campaign-case" ? [3, 3] : null)) as never
          }
          onLinkHover={((l: GraphLink | null) => setHoverLink(l)) as never}
          onNodeHover={((n: GraphNode | null) => setHoverNode(n)) as never}
          onNodeClick={
            ((n: GraphNode) => {
              if (n.kind === "case") onSelectCase?.(n.id);
            }) as never
          }
          cooldownTicks={120}
        />
        </Suspense>
      )}
    </div>
  );
}

export default ScamGraph;
