import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ValidationConsole from "./ValidationConsole";
import { mockCampaignDetail } from "../services/mockData";
import { api, __resetFixtureState } from "../services/api";

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

  it("shows which campaigns a core artifact was generalised from", () => {
    // `source_campaigns` reached the component through the type and the
    // adapter and was never rendered, so Screen D showed no provenance for
    // any artifact. A core rule compiled out of three campaigns is precisely
    // the one an approver needs the provenance of before pushing it to live
    // workers. Absent on the artifacts that carry no sources — the array is
    // empty there and an empty list is not a fact worth a row.
    setup();
    const sources = screen.getByTestId("artifact-sources-phone_agent_core");
    expect(sources).toHaveTextContent("SCAM-019");
    expect(sources).toHaveTextContent("SCAM-024");
    expect(sources).toHaveTextContent("SCAM-027");
    expect(screen.getAllByTestId(/^artifact-sources-/)).toHaveLength(1);
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

  it("keeps the editor open and says so when the save is refused", async () => {
    // `PATCH /enterprise/campaigns/{id}` is not a registered route, so a real
    // save answers 405. The console used to close the editor the instant the
    // button was pressed, without waiting for the promise: the analyst's
    // rewritten hypothesis vanished from the form and the stored one came
    // back, indistinguishable from a save that worked.
    const user = userEvent.setup();
    const onEdit = vi.fn().mockRejectedValue(new Error("API 405: Method Not Allowed"));
    render(
      <ValidationConsole
        campaign={mockCampaignDetail("camp-027")}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onEdit={onEdit}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Edit/ }));
    const input = screen.getByDisplayValue('Fake BNM "Safe Account" Wave');
    await user.clear(input);
    await user.type(input, "BNM Safe Account");
    await user.click(screen.getByRole("button", { name: /SAVE EDITS/ }));

    const error = await screen.findByTestId("edit-error");
    expect(error).toHaveTextContent(/not saved/i);
    expect(error).toHaveTextContent("405");
    // Still editing, with the analyst's text intact — nothing was committed.
    expect(screen.getByDisplayValue("BNM Safe Account")).toBeInTheDocument();
  });

  it("closes the editor only after the save resolves", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn().mockResolvedValue(undefined);
    render(
      <ValidationConsole
        campaign={mockCampaignDetail("camp-027")}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onEdit={onEdit}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Edit/ }));
    await user.click(screen.getByRole("button", { name: /SAVE EDITS/ }));

    expect(screen.queryByTestId("edit-error")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /SAVE EDITS/ })).not.toBeInTheDocument();
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

/**
 * Screen D is where a human authorises something that compiles artifacts and
 * pushes them to live workers. It reads `confidence.toFixed(2)`,
 * `evidence.map`, `hypothesis.name` and `proposed_artifacts.map` straight off
 * the payload, and `api.getCampaign` handed that payload over unadapted. A
 * shape change on `/campaigns/{id}` therefore took the approval screen to a
 * white page. Degrade, don't explode.
 */
describe("ValidationConsole survives a drifted /campaigns/{id} payload", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    __resetFixtureState();
  });

  function serve(body: unknown) {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: "OK",
        json: async () => body,
      } as Response),
    );
  }

  it("renders a campaign whose optional blocks are absent", async () => {
    // A PATCH route and a `metrics` key are being added to these endpoints, so
    // this response shape is not hypothetical. Only the identity columns are
    // guaranteed here.
    serve({ id: "camp-027", code: "SCAM-027", name: "Unnamed cluster", status: "CANDIDATE" });

    const campaign = await api.getCampaign("camp-027");

    render(
      <ValidationConsole campaign={campaign} onApprove={vi.fn()} onReject={vi.fn()} />,
    );

    expect(screen.getByTestId("validation-console")).toBeInTheDocument();
    // Missing confidence reads as a real 0.00, not a crash and not a number
    // the backend never sent.
    expect(screen.getByTestId("validation-console")).toHaveTextContent("0.00");
    expect(screen.getByTestId("evidence-column")).toBeInTheDocument();
    expect(screen.getByTestId("hypothesis-column")).toBeInTheDocument();
  });

  it("opens the editor on a campaign that arrived with no hypothesis", async () => {
    // The edit form seeds its state from `hypothesis.name`/`.mo_summary`
    // during render, so a null container is a blank screen, not a blank field.
    serve({ id: "camp-027", code: "SCAM-027", name: "Unnamed cluster", hypothesis: null });

    const campaign = await api.getCampaign("camp-027");
    const user = userEvent.setup();
    render(
      <ValidationConsole campaign={campaign} onApprove={vi.fn()} onReject={vi.fn()} onEdit={vi.fn()} />,
    );

    await user.click(screen.getByRole("button", { name: /Edit/ }));
    expect(screen.getByDisplayValue("Unnamed cluster")).toBeInTheDocument();
  });

  it("still renders when evidence rows and artifacts are malformed", async () => {
    serve({
      id: "camp-027",
      code: "SCAM-027",
      name: "Partial",
      evidence: [{ label: "span" }, null],
      proposed_artifacts: [{ name: "SCAM-027.json" }, {}],
    });

    const campaign = await api.getCampaign("camp-027");
    render(
      <ValidationConsole campaign={campaign} onApprove={vi.fn()} onReject={vi.fn()} />,
    );

    // An evidence line with no recorded verdict must not render a green tick.
    const evidence = screen.getByTestId("evidence-column");
    expect(evidence).toHaveTextContent("span");
    expect(evidence.querySelectorAll(".ok")).toHaveLength(0);
  });
});
