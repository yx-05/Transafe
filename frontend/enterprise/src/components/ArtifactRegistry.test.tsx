import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ArtifactRegistry from "./ArtifactRegistry";
import { mockArtifactDetail, mockArtifacts } from "../services/mockData";
import { api, __resetFixtureState } from "../services/api";

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

/**
 * Not drift — a present mismatch. `registry.list_artifacts` collapses to the
 * newest row per name and the router returns `{artifacts:[...flat rows...]}`
 * with no `versions` key anywhere, while the screen maps over exactly that
 * key. An empty registry rendered the "no artifacts" state and looked fine,
 * so this only surfaced once the system had actually published something.
 */
describe("ArtifactRegistry against the real /artifacts payload", () => {
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

  const flatRow = {
    id: "art-core-7",
    name: "phone_agent_core",
    tier: "core",
    artifact_type: "system_prompt",
    target_agent: "phone_agent",
    version: 7,
    status: "PUBLISHED",
    created_at: "2026-09-10T12:05:06Z",
    created_by: "generaliser",
    approved_by: "fraud_ops",
    source_campaigns: ["SCAM-019"],
    campaign_id: null,
    effectiveness: null,
  };

  it("renders the flat backend rows the registry actually returns", async () => {
    serve({ artifacts: [flatRow], count: 1 });

    const { artifacts } = await api.getArtifacts();

    render(
      <ArtifactRegistry
        groups={artifacts}
        activeTab="core"
        onTabChange={vi.fn()}
        detail={null}
        onSelect={vi.fn()}
        onRollback={vi.fn()}
      />,
    );

    expect(screen.getByText("phone_agent_core")).toBeInTheDocument();
    expect(screen.getByText(/v7/)).toBeInTheDocument();
  });

  it("folds repeated rows of one artifact into a single version history", async () => {
    serve({
      artifacts: [flatRow, { ...flatRow, id: "art-core-6", version: 6, status: "ROLLED_BACK" }],
    });

    const { artifacts } = await api.getArtifacts();

    expect(artifacts).toHaveLength(1);
    expect(artifacts[0].latest_version).toBe(7);

    render(
      <ArtifactRegistry
        groups={artifacts}
        activeTab="core"
        onTabChange={vi.fn()}
        detail={null}
        onSelect={vi.fn()}
        onRollback={vi.fn()}
      />,
    );

    expect(screen.getByText("phone_agent_core")).toBeInTheDocument();
  });

  it("unwraps the current/previous envelope for the diff pane", async () => {
    // `/artifacts/{name}/{version}` returns {current, previous, diff}, not the
    // flat record the pane reads — `detail.source_campaigns.length` and
    // `detail.version` are both dereferenced directly.
    serve({
      current: { ...flatRow, content: "# core v7\n" },
      previous: { version: 6, content: "# core v6\n" },
      diff: { added: 1, removed: 0 },
    });

    const detail = await api.getArtifact("phone_agent_core", 7);

    expect(detail.version).toBe(7);
    expect(detail.content).toContain("core v7");
    expect(detail.previous_version).toBe(6);
    expect(detail.source_campaigns).toEqual(["SCAM-019"]);

    render(
      <ArtifactRegistry
        groups={[]}
        activeTab="core"
        onTabChange={vi.fn()}
        onSelect={vi.fn()}
        onRollback={vi.fn()}
        detail={detail}
      />,
    );

    expect(screen.getByText("phone_agent_core · v7")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ROLLBACK to v6/ })).toBeInTheDocument();
  });
});
