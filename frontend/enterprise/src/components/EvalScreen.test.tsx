import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import EvalScreen from "./EvalScreen";
import { mockEval, mockRedteamCorpus } from "../services/mockData";

describe("EvalScreen", () => {
  it("gives the false-positive chart the same weight as detection", () => {
    render(<EvalScreen comparison={mockEval()} />);
    expect(screen.getByTestId("detection-chart")).toBeInTheDocument();
    expect(screen.getByTestId("false-positive-chart")).toBeInTheDocument();
  });

  it("names the actual red-team tests behind the number", () => {
    // The totals are a claim; the cases are the evidence for it. Without this
    // panel the operator has to take the red-team number on trust.
    render(<EvalScreen comparison={mockEval()} redteam={mockRedteamCorpus()} />);
    expect(screen.getByTestId("redteam-corpus")).toBeInTheDocument();
    expect(screen.getAllByTestId("rt-row")).toHaveLength(5);
    expect(screen.getByText("synonym_sub")).toBeInTheDocument();
    expect(screen.getByText("signature phrase")).toBeInTheDocument();
    expect(screen.getByText(/akaun penampan sementara/)).toBeInTheDocument();
  });

  it("marks each test caught or missed on both sides", () => {
    render(<EvalScreen comparison={mockEval()} redteam={mockRedteamCorpus()} />);
    // Five fixtures × two verdict columns. The obfuscation case is caught by
    // both sides; the recon-only case is missed by both, which is correct — it
    // never asks for money, so the structural rule must not fire.
    expect(screen.getAllByText("caught")).toHaveLength(5);
    expect(screen.getAllByText("missed")).toHaveLength(5);
    expect(screen.getByText("1/5 → 4/5")).toBeInTheDocument();
  });

  it("omits the corpus panel when no tests are available", () => {
    render(
      <EvalScreen
        comparison={mockEval()}
        redteam={{ ...mockRedteamCorpus(), tests: [] }}
      />,
    );
    expect(screen.queryByTestId("redteam-corpus")).not.toBeInTheDocument();
  });

  it("reports the paired before/after detection numbers", () => {
    render(<EvalScreen comparison={mockEval()} />);
    expect(screen.getByText("12/20 → 19/20")).toBeInTheDocument();
    expect(screen.getByText("3/10 → 1/10")).toBeInTheDocument();
  });

  it("colours an improvement as good and a regression as bad", () => {
    const comparison = mockEval();
    render(<EvalScreen comparison={comparison} />);
    expect(screen.getByText("95%")).toHaveClass("good"); // detection up
    expect(screen.getByText("10%")).toHaveClass("good"); // false positives down
  });

  it("flags a false-positive regression", () => {
    const comparison = mockEval();
    comparison.after!.false_positives = 6;
    render(<EvalScreen comparison={comparison} />);
    expect(screen.getByText("60%")).toHaveClass("bad");
  });

  it("handles a missing baseline", () => {
    render(<EvalScreen comparison={{ before: null, after: null }} />);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("triggers a new eval run", async () => {
    const user = userEvent.setup();
    const onRun = vi.fn();
    render(<EvalScreen comparison={mockEval()} onRun={onRun} />);
    await user.click(screen.getByRole("button", { name: /RUN EVAL/ }));
    expect(onRun).toHaveBeenCalled();
  });

  it("shows the red-team split, not just the blended rate", () => {
    // The blended 30-case rate averages 20 wave variants with 10 adversarial
    // mutations, so a red-team evasion is invisible in it. The mutation row is
    // the one that shows the defence surviving an attacker who adapts.
    const comparison = mockEval();
    comparison.before!.redteam_detection = 0.2;
    comparison.after!.redteam_detection = 0.9;
    render(<EvalScreen comparison={comparison} />);

    expect(screen.getByTestId("redteam-chart")).toBeInTheDocument();
    expect(screen.getByText("20% → 90%")).toBeInTheDocument();
    // Appears twice on purpose: once as the stat, once as the chart title.
    expect(screen.getAllByText(/RED-TEAM DETECTION/).length).toBe(2);
  });

  it("renders an unmeasured red-team rate as unknown, never as zero", () => {
    // A run persisted before the split existed carries no red-team field.
    // Falling back to 0 would read as "the red team beat us completely" — a
    // claim the payload does not support.
    const comparison = mockEval();
    delete comparison.before!.redteam_detection;
    delete comparison.after!.redteam_detection;
    render(<EvalScreen comparison={comparison} />);

    expect(screen.queryByText("0% → 0%")).not.toBeInTheDocument();
    expect(screen.getByText("— → —")).toBeInTheDocument();
  });

  it("triggers an adaptation cycle", async () => {
    const user = userEvent.setup();
    const onAdapt = vi.fn();
    render(<EvalScreen comparison={mockEval()} onRun={vi.fn()} onAdapt={onAdapt} />);
    await user.click(screen.getByRole("button", { name: /RUN ADAPTATION/ }));
    expect(onAdapt).toHaveBeenCalled();
  });

  it("blocks a second adaptation while one is running", () => {
    // The cycle publishes an artifact. Double-firing it would publish two
    // versions from one hypothesis and make the before/after unreadable.
    render(<EvalScreen comparison={mockEval()} onRun={vi.fn()} onAdapt={vi.fn()} adapting />);
    expect(screen.getByRole("button", { name: /ADAPTING/ })).toBeDisabled();
  });
});
