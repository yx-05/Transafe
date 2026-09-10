import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import EvalScreen from "./EvalScreen";
import { mockEval } from "../services/mockData";

describe("EvalScreen", () => {
  it("gives the false-positive chart the same weight as detection", () => {
    render(<EvalScreen comparison={mockEval()} />);
    expect(screen.getByTestId("detection-chart")).toBeInTheDocument();
    expect(screen.getByTestId("false-positive-chart")).toBeInTheDocument();
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
});
