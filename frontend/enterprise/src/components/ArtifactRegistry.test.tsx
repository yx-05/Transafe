import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ArtifactRegistry from "./ArtifactRegistry";
import { mockArtifactDetail, mockArtifacts } from "../services/mockData";

const groups = mockArtifacts().artifacts;

function setup(tab: "core" | "pack" = "core", withDetail = true) {
  const onTabChange = vi.fn();
  const onSelect = vi.fn();
  const onRollback = vi.fn();
  render(
    <ArtifactRegistry
      groups={groups}
      activeTab={tab}
      onTabChange={onTabChange}
      detail={withDetail ? mockArtifactDetail("phone_agent_core", 7) : null}
      onSelect={onSelect}
      onRollback={onRollback}
    />,
  );
  return { onTabChange, onSelect, onRollback };
}

describe("ArtifactRegistry", () => {
  it("shows only the artifacts of the active tier", () => {
    setup("core");
    const registry = screen.getByTestId("artifact-registry");
    expect(registry.querySelectorAll(".artifact-group")).toHaveLength(1);
    expect(registry.querySelector(".artifact-group h4")).toHaveTextContent(
      "phone_agent_core",
    );
    expect(screen.queryByText(/SCAM-024\.json/)).not.toBeInTheDocument();
  });

  it("switches tabs", async () => {
    const user = userEvent.setup();
    const { onTabChange } = setup("core");
    await user.click(screen.getByRole("button", { name: "CAMPAIGN PACKS" }));
    expect(onTabChange).toHaveBeenCalledWith("pack");
  });

  it("renders the full version history with effectiveness", () => {
    setup("core");
    expect(screen.getByText("v7")).toBeInTheDocument();
    expect(screen.getByText("v6")).toBeInTheDocument();
    expect(screen.getByText("20/20 ✓")).toBeInTheDocument();
    expect(screen.getByText("17/20 ✓ · 1 FP")).toBeInTheDocument();
  });

  it("selects a version", async () => {
    const user = userEvent.setup();
    const { onSelect } = setup("core");
    await user.click(screen.getByText("v6").closest("button")!);
    expect(onSelect).toHaveBeenCalledWith("phone_agent_core", 6);
  });

  it("renders a red/green diff of the selected version", () => {
    setup("core");
    const diff = screen.getByTestId("diff-viewer");
    expect(diff).toBeInTheDocument();
    expect(diff.querySelectorAll('[data-difftype="add"]').length).toBeGreaterThan(0);
    expect(screen.getByText(/isolation_directive/)).toBeInTheDocument();
  });

  it("attributes generalisation to its source campaigns", () => {
    setup("core");
    expect(
      screen.getByText(/generalised from SCAM-019 · SCAM-024 · SCAM-027/),
    ).toBeInTheDocument();
  });

  it("rolls back to the previous version", async () => {
    const user = userEvent.setup();
    const { onRollback } = setup("core");
    await user.click(screen.getByRole("button", { name: /ROLLBACK to v6/ }));
    expect(onRollback).toHaveBeenCalledWith("phone_agent_core", 6);
  });

  it("prompts for a selection when nothing is open", () => {
    setup("core", false);
    expect(screen.getByText(/select a version/i)).toBeInTheDocument();
  });
});
