import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import NervousSystem, { EDGES, NODES, edgeForEvent } from "./NervousSystem";
import { makeEvent, resetEventStore, seedEvents } from "../test-utils";

describe("NervousSystem", () => {
  beforeEach(() => resetEventStore());

  it("renders every layer node", () => {
    render(<NervousSystem />);
    const svg = screen.getByTestId("nervous-system");
    for (const node of NODES) {
      expect(svg.querySelector(`[data-layer="${node.layer}"]`)).toBeTruthy();
    }
  });

  it("is completely idle when no events have arrived", () => {
    render(<NervousSystem />);
    const active = screen
      .getByTestId("nervous-system")
      .querySelectorAll('[data-active="true"]');
    expect(active).toHaveLength(0);
  });

  it("lights the layer that just fired", () => {
    seedEvents([makeEvent({ id: 1, layer: "discovery", event_type: "cluster_formed" })]);
    render(<NervousSystem />);
    const el = screen
      .getByTestId("nervous-system")
      .querySelector('[data-layer="discovery"]');
    expect(el).toHaveAttribute("data-active", "true");
  });

  it("marks a worker as reprogrammed only after a propagation event names it", () => {
    render(<NervousSystem />);
    expect(
      screen.getByTestId("nervous-system").querySelector('[data-worker="phone_agent"]'),
    ).toHaveAttribute("data-consumed", "false");

    resetEventStore();
    seedEvents([
      makeEvent({
        id: 5,
        layer: "propagation",
        event_type: "propagated",
        payload: { agent: "phone_agent" },
      }),
    ]);
    render(<NervousSystem />);
    const nodes = screen.getAllByTestId("nervous-system");
    const latest = nodes[nodes.length - 1];
    expect(latest.querySelector('[data-worker="phone_agent"]')).toHaveAttribute(
      "data-consumed",
      "true",
    );
  });

  it("maps an event to the edge that carried it", () => {
    expect(edgeForEvent(makeEvent({ layer: "case" }))).toEqual(["sensing", "case"]);
    expect(edgeForEvent(makeEvent({ layer: "registry" }))).toEqual([
      "compiler",
      "registry",
    ]);
    expect(edgeForEvent(makeEvent({ layer: "exposure" }))![1]).toBe("exposure");
    expect(edgeForEvent(makeEvent({ layer: "sensing" }))).toBeNull();
  });

  it("wires the layers in pipeline order", () => {
    expect(EDGES).toEqual([
      ["sensing", "case"],
      ["case", "discovery"],
      ["discovery", "compiler"],
      ["compiler", "registry"],
      ["registry", "propagation"],
    ]);
  });
});
