import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ValidationConsole from "./ValidationConsole";
import { mockCampaignDetail } from "../services/mockData";

function setup(overrides: Partial<Parameters<typeof ValidationConsole>[0]> = {}) {
  const onApprove = vi.fn();
  const onReject = vi.fn();
  const onEdit = vi.fn();
  render(
    <ValidationConsole
      campaign={mockCampaignDetail("camp-027")}
      onApprove={onApprove}
      onReject={onReject}
      onEdit={onEdit}
      {...overrides}
    />,
  );
  return { onApprove, onReject, onEdit };
}

describe("ValidationConsole", () => {
  it("separates computed evidence from the LLM hypothesis", () => {
    setup();
    const evidence = screen.getByTestId("evidence-column");
    const hypothesis = screen.getByTestId("hypothesis-column");
    expect(evidence).toHaveTextContent("COMPUTED");
    expect(hypothesis).toHaveTextContent("LLM-GENERATED");
    expect(evidence).not.toBe(hypothesis);
  });

  it("lists every evidence line with a pass mark", () => {
    setup();
    const evidence = screen.getByTestId("evidence-column");
    expect(evidence).toHaveTextContent("6 cases, 4 customers");
    expect(evidence).toHaveTextContent("0.89");
    expect(evidence.querySelectorAll(".evidence-item")).toHaveLength(5);
  });

  it("shows proposed artifacts with their tier", () => {
    setup();
    const hypothesis = screen.getByTestId("hypothesis-column");
    expect(hypothesis).toHaveTextContent("SCAM-027.json");
    expect(hypothesis).toHaveTextContent("phone_agent_core");
    expect(hypothesis).toHaveTextContent("CORE");
    expect(hypothesis).toHaveTextContent("PACK");
  });

  it("approves the campaign", async () => {
    const user = userEvent.setup();
    const { onApprove } = setup();
    await user.click(screen.getByRole("button", { name: /Approve/ }));
    expect(onApprove).toHaveBeenCalledWith("camp-027");
  });

  it("requires a reason before rejecting", async () => {
    const user = userEvent.setup();
    const { onReject } = setup();
    await user.click(screen.getByRole("button", { name: /Reject/ }));
    const confirm = screen.getByRole("button", { name: /CONFIRM REJECT/ });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText(/reason for rejection/i), "coincidence");
    await user.click(confirm);
    expect(onReject).toHaveBeenCalledWith("camp-027", "coincidence");
  });

  it("lets an analyst edit the generated hypothesis", async () => {
    const user = userEvent.setup();
    const { onEdit } = setup();
    await user.click(screen.getByRole("button", { name: /Edit/ }));
    const input = screen.getByDisplayValue('Fake BNM "Safe Account" Wave');
    await user.clear(input);
    await user.type(input, "BNM Safe Account");
    await user.click(screen.getByRole("button", { name: /SAVE EDITS/ }));
    expect(onEdit).toHaveBeenCalledWith(
      "camp-027",
      expect.objectContaining({ name: "BNM Safe Account" }),
    );
  });

  it("disables decisions once the campaign is no longer a candidate", () => {
    render(
      <ValidationConsole
        campaign={{ ...mockCampaignDetail("camp-027"), status: "ACTIVE" }}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /Approve/ })).toBeDisabled();
  });
});
