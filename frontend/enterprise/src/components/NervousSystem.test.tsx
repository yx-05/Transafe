import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import NervousSystem, {
  EDGES,
  NODES,
  WORKERS,
  edgeForEvent,
  workerIdForEvent,
} from "./NervousSystem";
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

  // The test above seeds `{ agent: "phone_agent" }` — the shape the recorded
  // REPLAY corpus emits. The live backend emits `{ agent_name: "phone_worker" }`
  // instead, and shares no worker name with the console's node ids. So the
  // suite above stayed green for a component that lit nothing in LIVE. These
  // cases pin the live shape specifically.
  it("resolves a LIVE propagation payload to a worker node", () => {
    expect(
      workerIdForEvent(
        makeEvent({ layer: "propagation", payload: { agent_name: "phone_worker" } }),
      ),
    ).toBe("phone_agent");
    expect(
      workerIdForEvent(
        makeEvent({ layer: "propagation", payload: { agent_name: "phishing_worker" } }),
      ),
    ).toBe("phishing_agent");
    expect(
      workerIdForEvent(
        makeEvent({ layer: "propagation", payload: { agent_name: "financial_worker" } }),
      ),
    ).toBe("txn_monitor");
  });

  it("still resolves the recorded REPLAY payload shape", () => {
    expect(
      workerIdForEvent(
        makeEvent({ layer: "propagation", payload: { agent: "phone_agent" } }),
      ),
    ).toBe("phone_agent");
  });

  it("returns null for an unknown agent rather than a falsy node id", () => {
    expect(
      workerIdForEvent(
        makeEvent({ layer: "propagation", payload: { agent_name: "nope_worker" } }),
      ),
    ).toBeNull();
    expect(workerIdForEvent(makeEvent({ layer: "propagation", payload: {} }))).toBeNull();
  });

  it("maps every backend subscriber name onto a real worker node", () => {
    // Mirrors SUBSCRIPTION_MAP in backend/src/enterprise/propagation.py. If a
    // subscriber is added there and not mapped here, its acknowledgement is
    // silently invisible on screen — which is the failure this pins.
    const ids = new Set(WORKERS.map((w) => w.id));
    for (const backendName of ["phone_worker", "phishing_worker", "financial_worker"]) {
      const mapped = workerIdForEvent(
        makeEvent({ layer: "propagation", payload: { agent_name: backendName } }),
      );
      expect(mapped, `${backendName} is unmapped`).not.toBeNull();
      expect(ids.has(mapped!), `${backendName} -> ${mapped} is not a node`).toBe(true);
    }
  });

  it("lights the worker node from a LIVE-shaped propagation event", () => {
    seedEvents([
      makeEvent({
        id: 7,
        layer: "propagation",
        event_type: "propagation_acknowledged",
        payload: { agent_name: "financial_worker" },
      }),
    ]);
    render(<NervousSystem />);
    expect(
      screen.getByTestId("nervous-system").querySelector('[data-worker="txn_monitor"]'),
    ).toHaveAttribute("data-consumed", "true");
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
