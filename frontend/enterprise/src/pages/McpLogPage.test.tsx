import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import McpLogPage from "./McpLogPage";
import { api } from "../services/api";
import { makeEvent, resetEventStore, seedEvents } from "../test-utils";
import type { McpLogResponse } from "../types/api";

/**
 * The defect this file exists to prevent: `getMcpLog` was called with no
 * arguments, so the console always received the unprojected operator payload
 * and the role selector changed nothing but a label. A component-level test
 * could not have caught it — the bug lived in the wiring.
 */

vi.mock("../services/api", () => ({
  api: { getMcpLog: vi.fn() },
}));

const getMcpLog = vi.mocked(api.getMcpLog);

const ROLES = ["compliance", "fraud_ops", "public"];

function response(asRole?: string): McpLogResponse {
  const withheld = asRole === "public" ? ["pii", "transcripts"] : [];
  return {
    entries: [
      {
        id: 1,
        ts: "2026-09-10T12:05:31Z",
        caller: "codebuddy",
        role: "compliance",
        tool: "get_campaign",
        params: asRole === "public" ? { outcome: null } : { code: "SCAM-027" },
        latency_ms: 88,
        citations: asRole === "public" ? null : ["SCAM-027"],
        citation_count: 1,
        redacted_fields: withheld,
      },
    ],
    count: 1,
    roles: ROLES,
  };
}

beforeEach(() => {
  resetEventStore();
  getMcpLog.mockReset();
  getMcpLog.mockImplementation((asRole?: string) =>
    Promise.resolve(response(asRole)),
  );
});

/** An `mcp_call` event carrying whatever audit claim the case needs. */
function mcpCall(payload: Record<string, unknown>) {
  return makeEvent({ layer: "exposure", event_type: "mcp_call", payload });
}

describe("McpLogPage", () => {
  it("requests the log through a lens on first load", async () => {
    render(<McpLogPage />);
    await waitFor(() => expect(getMcpLog).toHaveBeenCalled());

    // Not `getMcpLog()` — the operator view is never what the console shows.
    expect(getMcpLog).toHaveBeenCalledWith("fraud_ops");
  });

  it("refetches through the new lens when the role changes", async () => {
    const user = userEvent.setup();
    render(<McpLogPage />);
    await waitFor(() => expect(getMcpLog).toHaveBeenCalledWith("fraud_ops"));

    await user.selectOptions(screen.getByTestId("role-select"), "public");

    await waitFor(() => expect(getMcpLog).toHaveBeenCalledWith("public"));
    expect(getMcpLog).toHaveBeenCalledTimes(2);
  });

  it("renders the payload the server returned for the selected lens", async () => {
    const user = userEvent.setup();
    render(<McpLogPage />);
    await waitFor(() =>
      expect(screen.getByTestId("mcp-row")).toHaveTextContent("code="),
    );

    await user.selectOptions(screen.getByTestId("role-select"), "public");

    // The data itself changed, not just the caption — this is the assertion
    // the old screen could never have satisfied.
    await waitFor(() =>
      expect(screen.getByTestId("mcp-row")).not.toHaveTextContent("SCAM-027"),
    );
    expect(screen.getByTestId("mcp-row")).toHaveTextContent("params withheld");
    expect(screen.getByTestId("redaction-summary")).toHaveTextContent("transcripts");
  });

  it("populates the selector from the server's role list", async () => {
    render(<McpLogPage />);
    await waitFor(() => expect(getMcpLog).toHaveBeenCalled());

    const options = Array.from(
      screen.getByTestId<HTMLSelectElement>("role-select").options,
    ).map((o) => o.value);
    expect(options).toEqual(ROLES);
  });

  it("keeps the last good role list when a response omits it", async () => {
    render(<McpLogPage />);
    await waitFor(() => expect(getMcpLog).toHaveBeenCalled());

    getMcpLog.mockResolvedValueOnce({ entries: [], count: 0 });
    const user = userEvent.setup();
    await user.selectOptions(screen.getByTestId("role-select"), "public");

    await waitFor(() => expect(getMcpLog).toHaveBeenCalledWith("public"));
    // An empty selector mid-demo would be unrecoverable without a reload.
    const options = Array.from(
      screen.getByTestId<HTMLSelectElement>("role-select").options,
    ).map((o) => o.value);
    expect(options).toEqual(ROLES);
  });

  it("surfaces a call whose audit row was never written", async () => {
    render(<McpLogPage />);
    await waitFor(() => expect(getMcpLog).toHaveBeenCalled());

    act(() => seedEvents([mcpCall({ audit_persisted: false })]));

    // The refetch this event triggers returns a log *without* the call, so
    // without the banner an audit failure looks like a refresh that did
    // nothing at all.
    await waitFor(() =>
      expect(screen.getByTestId("audit-gap-warning")).toBeInTheDocument(),
    );
  });

  it("does not accuse events that predate the audit_persisted field", async () => {
    render(<McpLogPage />);
    await waitFor(() => expect(getMcpLog).toHaveBeenCalled());

    // `mcp_call` events 47-95 on the live instance carry no such key. A
    // falsy-check instead of `=== false` would make the console retroactively
    // report every one of them as a lost audit row.
    act(() => seedEvents([mcpCall({ caller: "codebuddy", outcome: "ok" })]));

    await waitFor(() => expect(getMcpLog).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("audit-gap-warning")).not.toBeInTheDocument();
  });

  it("stays silent when the audit row was written", async () => {
    render(<McpLogPage />);
    await waitFor(() => expect(getMcpLog).toHaveBeenCalled());

    act(() => seedEvents([mcpCall({ audit_persisted: true })]));

    await waitFor(() => expect(getMcpLog).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("audit-gap-warning")).not.toBeInTheDocument();
  });
});
