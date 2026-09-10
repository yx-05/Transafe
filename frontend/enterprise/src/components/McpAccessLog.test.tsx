import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import McpAccessLog from "./McpAccessLog";
import type { McpLogRow } from "../types/api";

/**
 * These tests deliberately assert that the component holds **no** policy.
 *
 * The previous suite tested `redactedFor("compliance")` — a frontend copy of
 * the server's visibility table. It passed while stating a policy the server
 * contradicted, which is worse than no test: it certified the drift. So the
 * chips are now asserted to follow `redacted_fields` off the row, including
 * for a category list the frontend has never heard of.
 */

const ROLES = [
  "analyst",
  "auditor",
  "compliance",
  "customer_service",
  "external_researcher",
  "fraud_ops",
  "legal",
  "partner_bank",
  "public",
];

function row(over: Partial<McpLogRow> = {}): McpLogRow {
  return {
    id: 1,
    ts: "2026-09-10T12:05:31Z",
    caller: "codebuddy",
    role: "compliance",
    tool: "get_campaign",
    params: { code: "SCAM-027" },
    latency_ms: 88,
    citations: ["SCAM-027"],
    ...over,
  };
}

function renderLog(entries: McpLogRow[], role = "fraud_ops") {
  const onRoleChange = vi.fn();
  render(
    <McpAccessLog
      entries={entries}
      roles={ROLES}
      role={role}
      onRoleChange={onRoleChange}
    />,
  );
  return { onRoleChange };
}

describe("McpAccessLog", () => {
  it("renders one row per call", () => {
    renderLog([row({ id: 1 }), row({ id: 2 }), row({ id: 3 })]);
    expect(screen.getAllByTestId("mcp-row")).toHaveLength(3);
  });

  it("shows an empty state before any external call", () => {
    renderLog([]);
    expect(screen.getByText(/no MCP calls yet/i)).toBeInTheDocument();
  });

  it("offers every role the server declared, not a hardcoded subset", () => {
    renderLog([row()]);
    const options = Array.from(
      screen.getByTestId<HTMLSelectElement>("role-select").options,
    ).map((o) => o.value);
    expect(options).toEqual(ROLES);
    // The old hardcoded list omitted these four; fraud_ops in particular gives
    // the sharpest before/after contrast on this screen.
    expect(options).toContain("fraud_ops");
    expect(options).toContain("auditor");
    expect(options).toContain("partner_bank");
    expect(options).toContain("external_researcher");
  });

  it("labels chips from the server's category list, whatever it says", () => {
    // A vocabulary the frontend has no knowledge of. If any local table were
    // still in play these would not appear.
    renderLog([row({ redacted_fields: ["account_numbers", "pii", "transcripts"] })], "compliance");

    const summary = screen.getByTestId("redaction-summary");
    expect(summary).toHaveTextContent("account_numbers");
    expect(summary).toHaveTextContent("pii");
    expect(summary).toHaveTextContent("transcripts");
  });

  it("reports full visibility when the server withholds nothing", () => {
    renderLog([row({ redacted_fields: [], citation_count: 1 })], "fraud_ops");

    const summary = screen.getByTestId("redaction-summary");
    expect(summary).toHaveTextContent(/full visibility/i);
    expect(summary).not.toHaveTextContent(/least privilege/i);
    // A lens that withholds nothing is still projected — it must not be
    // labelled as having had its params cut.
    expect(screen.getByTestId("mcp-row")).not.toHaveTextContent("params withheld");
    expect(screen.getByTestId("mcp-row")).toHaveTextContent("code=");
  });

  it("fails closed when the lens is unknown", () => {
    // No `redacted_fields` anywhere: an old server or the offline fixture.
    renderLog([row({ redacted_fields: undefined })], "public");

    const summary = screen.getByTestId("redaction-summary");
    expect(summary).toHaveTextContent(/least privilege/i);
    // The one wrong answer would be implying nothing was withheld.
    expect(summary).not.toHaveTextContent(/full visibility/i);
  });

  it("marks params and citations as withheld on a projected row", () => {
    renderLog(
      [
        row({
          params: { outcome: null },
          citations: null,
          citation_count: 2,
          redacted_fields: ["pii", "transcripts"],
        }),
      ],
      "public",
    );

    const rendered = screen.getByTestId("mcp-row");
    expect(rendered).toHaveTextContent("params withheld");
    expect(rendered).toHaveTextContent("2 citations withheld");
    // The null placeholder must not leak into the rendered params.
    expect(rendered).not.toHaveTextContent("outcome=null");
  });

  it("does not claim params were withheld from a call that had none", () => {
    // Operator view: `params: {}` means the call took no arguments. Absent
    // `citation_count` is what distinguishes it from a withheld payload.
    renderLog([row({ tool: "list_campaigns", params: {}, citations: [] })]);
    expect(screen.getByTestId("mcp-row")).not.toHaveTextContent("params withheld");
  });

  it("shows citations when the reader is entitled to them", () => {
    renderLog([row({ citations: ["SCAM-027 (6 cases)"] })]);
    expect(screen.getByText(/cited SCAM-027 \(6 cases\)/)).toBeInTheDocument();
  });

  it("delegates the role switch upward so the log is refetched", async () => {
    const user = userEvent.setup();
    const { onRoleChange } = renderLog([row()]);

    await user.selectOptions(screen.getByTestId("role-select"), "public");

    // The component must not resolve the new lens locally — only the server
    // can, and it does so on the refetch this callback triggers.
    await waitFor(() => expect(onRoleChange).toHaveBeenCalledWith("public"));
  });
});
