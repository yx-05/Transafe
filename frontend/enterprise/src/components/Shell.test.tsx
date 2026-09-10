import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Shell from "./Shell";
import { MockWebSocket, resetEventStore } from "../test-utils";
import { useEventStore } from "../store/useEventStore";
import { useCampaignStore } from "../store/useCampaignStore";

const originalWs = globalThis.WebSocket;

function renderShell(initial = "/") {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<div>overview body</div>} />
          <Route path="graph" element={<div>graph body</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("Shell", () => {
  beforeEach(() => {
    resetEventStore();
    useCampaignStore.setState({ overview: null });
    MockWebSocket.reset();
    (globalThis as any).WebSocket = MockWebSocket;
    // no backend in tests → api falls back to fixtures
    globalThis.fetch = vi.fn(async () => {
      throw new Error("offline");
    }) as unknown as typeof fetch;
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    (globalThis as any).WebSocket = originalWs;
    vi.restoreAllMocks();
  });

  it("always shows the mode badge", async () => {
    renderShell();
    expect(await screen.findByTestId("mode-badge")).toHaveTextContent("LIVE");
  });

  it("renders every screen in the navigation", () => {
    renderShell();
    for (const label of [
      "OVERVIEW",
      "CASES",
      "SCAM GRAPH",
      "VALIDATION",
      "REGISTRY",
      "EVALUATION",
      "MCP LOG",
    ]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("opens the live event stream on mount", async () => {
    renderShell();
    await waitFor(() => expect(MockWebSocket.instances.length).toBeGreaterThan(0));
    expect(MockWebSocket.last!.url).toContain("/enterprise/ws/events");
  });

  it("reflects connection state in the badge dot", async () => {
    renderShell();
    await waitFor(() => expect(MockWebSocket.last).toBeDefined());
    MockWebSocket.last!.open();
    await waitFor(() =>
      expect(screen.getByTestId("mode-badge").querySelector(".mode-dot")).not.toHaveClass(
        "off",
      ),
    );
  });

  it("renders live counters from the overview endpoint", async () => {
    renderShell();
    await waitFor(() => expect(screen.getByTestId("counter-strip")).toHaveTextContent("47"));
    expect(screen.getByTestId("counter-strip")).toHaveTextContent("v7");
  });

  it("switches to REPLAY and back", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getByRole("button", { name: /REPLAY/ }));
    await waitFor(() => expect(useEventStore.getState().mode).toBe("REPLAY"));
    expect(screen.getByTestId("mode-badge")).toHaveTextContent("REPLAY");

    await user.click(screen.getByRole("button", { name: /LIVE/ }));
    await waitFor(() => expect(useEventStore.getState().mode).toBe("LIVE"));
  });

  it("clears the event buffer on reset", async () => {
    const user = userEvent.setup();
    renderShell();
    useEventStore.setState({
      events: [
        {
          id: 1,
          ts: new Date().toISOString(),
          layer: "case",
          event_type: "case_ingested",
          severity: "info",
          payload: {},
          run_id: null,
        },
      ],
    });
    await user.click(screen.getByRole("button", { name: /RESET/ }));
    await waitFor(() => expect(useEventStore.getState().events).toHaveLength(0));
  });

  it("renders the routed screen body", () => {
    renderShell("/graph");
    expect(screen.getByText("graph body")).toBeInTheDocument();
  });
});
