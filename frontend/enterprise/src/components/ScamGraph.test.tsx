import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import ScamGraph, { linkColour, linkWidth, nodeColour } from "./ScamGraph";
import { mockGraph } from "../services/mockData";
import type { GraphLink, GraphNode } from "../types/campaign";

// react-force-graph-2d needs a real canvas; swap it for a probe that renders
// the graph as inspectable DOM so we can assert on the data we feed it.
vi.mock("react-force-graph-2d", () => ({
  default: ({ graphData }: { graphData: { nodes: GraphNode[]; links: GraphLink[] } }) => (
    <div data-testid="force-graph">
      <span data-testid="node-count">{graphData.nodes.length}</span>
      <span data-testid="link-count">{graphData.links.length}</span>
      {graphData.links.map((l, i) => (
        <span key={i} data-testid="link-reason">
          {l.reason}
        </span>
      ))}
    </div>
  ),
}));

describe("graph visual encoding", () => {
  it("colours nodes by kind and entity type", () => {
    expect(nodeColour({ id: "c", kind: "case", label: "#1" })).toBe("#8a94a6");
    expect(
      nodeColour({ id: "e", kind: "entity", label: "acct", entity_type: "ACCOUNT" }),
    ).toBe("#4CAF50");
    expect(nodeColour({ id: "k", kind: "campaign", label: "SCAM-027" })).toContain("rgba");
  });

  it("scales case-case edges by fused weight", () => {
    const light: GraphLink = {
      source: "a",
      target: "b",
      kind: "case-case",
      weight: 0.1,
      reason: "",
    };
    const heavy: GraphLink = { ...light, weight: 0.95 };
    expect(linkWidth(heavy)).toBeGreaterThan(linkWidth(light));
  });

  it("highlights a hovered edge in the accent colour", () => {
    const link: GraphLink = {
      source: "a",
      target: "b",
      kind: "case-case",
      weight: 0.5,
      reason: "",
    };
    expect(linkColour(link, true)).toBe("#FFB74D");
    expect(linkColour(link, false)).not.toBe("#FFB74D");
  });
});

describe("ScamGraph", () => {
  it("feeds every node and link into the force layout", async () => {
    const data = mockGraph();
    render(<ScamGraph data={data} />);
    await waitFor(() => expect(screen.getByTestId("force-graph")).toBeInTheDocument());
    expect(screen.getByTestId("node-count")).toHaveTextContent(String(data.nodes.length));
    expect(screen.getByTestId("link-count")).toHaveTextContent(String(data.links.length));
  });

  it("carries a why-this-edge-exists reason on every link", () => {
    const data = mockGraph();
    for (const link of data.links) {
      expect(link.reason.length).toBeGreaterThan(0);
    }
  });

  it("renders the legend explaining the encoding", () => {
    render(<ScamGraph data={mockGraph()} />);
    expect(screen.getByText(/edge thickness = fused weight/)).toBeInTheDocument();
  });

  it("states plainly that there is no graph rather than spinning forever", () => {
    // The migration isn't applied yet, so /graph legitimately returns [].
    render(<ScamGraph data={{ nodes: [], links: [], hulls: [] }} />);
    expect(screen.getByTestId("graph-empty")).toHaveTextContent(/no linked cases yet/);
    expect(screen.queryByText(/loading graph/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("force-graph")).not.toBeInTheDocument();
  });
});
