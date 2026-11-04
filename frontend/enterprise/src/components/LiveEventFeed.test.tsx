import { beforeEach, describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LiveEventFeed from "./LiveEventFeed";
import { makeEvent, resetEventStore, seedEvents } from "../test-utils";
import { useEventStore } from "../store/useEventStore";

describe("LiveEventFeed", () => {
  beforeEach(() => resetEventStore());

  it("shows an honest empty state when no events have arrived", () => {
    render(<LiveEventFeed />);
    expect(screen.getByText(/waiting for ns_events/i)).toBeInTheDocument();
  });

  it("renders one row per event, newest first", () => {
    seedEvents([
      makeEvent({ id: 1, layer: "sensing", event_type: "call_received" }),
      makeEvent({ id: 2, layer: "case", event_type: "case_ingested", payload: { case_number: 41 } }),
    ]);
    render(<LiveEventFeed />);
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("data-event-type", "case_ingested");
    expect(rows[1]).toHaveAttribute("data-event-type", "call_received");
  });

  it("marks critical events so they read as alarms", () => {
    seedEvents([
      makeEvent({
        id: 1,
        layer: "discovery",
        event_type: "campaign_proposed",
        severity: "critical",
        payload: { code: "SCAM-027", case_count: 3 },
      }),
    ]);
    render(<LiveEventFeed />);
    expect(screen.getByRole("listitem")).toHaveClass("severity-critical");
    expect(screen.getByText(/CAMPAIGN PROPOSED \(3\) SCAM-027/)).toBeInTheDocument();
  });

  it("filters by layer when a layer chip is toggled", async () => {
    const user = userEvent.setup();
    seedEvents([
      makeEvent({ id: 1, layer: "sensing", event_type: "call_received" }),
      makeEvent({ id: 2, layer: "case", event_type: "case_ingested" }),
    ]);
    render(<LiveEventFeed />);
    await user.click(screen.getByRole("button", { name: "SENSING" }));
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveAttribute("data-layer", "sensing");
  });

  it("adds a row when a new event lands in the store", () => {
    render(<LiveEventFeed />);
    act(() => {
      useEventStore.getState().appendEvent(makeEvent({ id: 7 }));
    });
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });
});
