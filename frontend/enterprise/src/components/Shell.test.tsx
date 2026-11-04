import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Shell from "./Shell";
import { MockWebSocket, resetEventStore } from "../test-utils";
import { useEventStore } from "../store/useEventStore";
import { useCampaignStore } from "../store/useCampaignStore";
import { api, __resetFixtureState } from "../services/api";

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
    __resetFixtureState();
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

  it("raises the FIXTURE badge for a fallback on a screen that never touches the overview", async () => {
    // Backend is up and /overview answers normally, so the shell's own data is
    // real and nothing about it ever changes again. Screen E then falls back
    // to fabricated artifacts. Sampling `lastFixtureRoute()` from an effect
    // keyed on `overview` cannot see this: fabricated rows render under a
    // clean header, which is exactly the failure this console keeps shipping.
    // Everything the shell itself needs is served for real, so the header has
    // no reason of its own to raise the badge. Only /artifacts falls back.
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/artifacts")) throw new Error("offline");
      return {
        ok: true,
        status: 200,
        json: async () => (url.includes("/events") ? [] : {}),
      } as Response;
    }) as unknown as typeof fetch;

    function RegistryBody() {
      return (
        <button type="button" onClick={() => void api.getArtifacts()}>
          load artifacts
        </button>
      );
    }

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/registry"]}>
        <Routes>
          <Route element={<Shell />}>
            <Route path="registry" element={<RegistryBody />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    // Let the shell fully settle first. Its overview is real and will not
    // change again — which is the whole problem: an effect keyed on `overview`
    // has already fired for the last time before the operator ever reaches
    // this screen.
    await waitFor(() => expect(useCampaignStore.getState().overview).not.toBeNull());
    expect(screen.queryByTestId("fixture-badge")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "load artifacts" }));

    const badge = await screen.findByTestId("fixture-badge");
    expect(badge).toHaveAttribute("title", expect.stringContaining("/artifacts"));
  });

  it("shows no FIXTURE badge while every request is served by the backend", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({}),
    })) as unknown as typeof fetch;

    renderShell();

    await waitFor(() => expect(useCampaignStore.getState().overview).not.toBeNull());
    expect(screen.queryByTestId("fixture-badge")).not.toBeInTheDocument();
  });
});
