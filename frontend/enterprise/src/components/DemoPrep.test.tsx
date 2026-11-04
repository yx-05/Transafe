import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DemoPrep from "./DemoPrep";
import type { PreflightResponse } from "../types/api";

function preflight(overrides: Partial<PreflightResponse> = {}): PreflightResponse {
  return {
    ok: true,
    summary: "Ready",
    checks: [
      { name: "supabase", status: "pass", detail: "Connected" },
      { name: "campaigns", status: "info", detail: "3 active campaign(s)" },
    ],
    ...overrides,
  };
}

const base = {
  checking: false,
  stage: "idle" as const,
  detail: "",
  onCheck: vi.fn(),
  onWarmup: vi.fn(),
  onClose: vi.fn(),
};

describe("DemoPrep", () => {
  it("renders each check with its verdict", () => {
    render(<DemoPrep {...base} preflight={preflight()} />);

    expect(screen.getByText("supabase")).toBeInTheDocument();
    expect(screen.getByText("PASS")).toBeInTheDocument();
    expect(screen.getByText("INFO")).toBeInTheDocument();
  });

  it("distinguishes warn from fail", () => {
    // Four states, not two. A warning is a demo you can still give, and
    // rendering it as failure would teach the operator to ignore the verdict.
    render(
      <DemoPrep
        {...base}
        preflight={preflight({
          ok: true,
          summary: "Ready, with 1 warning(s): llm",
          checks: [
            { name: "llm", status: "warn", detail: "thinking mode" },
            { name: "v2_schema", status: "fail", detail: "missing table" },
          ],
        })}
      />,
    );

    expect(screen.getByText("WARN")).toBeInTheDocument();
    expect(screen.getByText("FAIL")).toBeInTheDocument();
  });

  it("says so when no checks ran, rather than showing nothing", () => {
    // An empty list with a green summary would be the worst possible output.
    render(
      <DemoPrep
        {...base}
        preflight={{ ok: false, summary: "Backend did not answer", checks: [] }}
      />,
    );

    expect(screen.getByText(/no checks ran/i)).toBeInTheDocument();
  });

  it("shows nothing until a check or a warm-up has started", () => {
    render(<DemoPrep {...base} preflight={null} />);

    expect(screen.queryByTestId("demo-prep-checks")).not.toBeInTheDocument();
    expect(screen.queryByTestId("demo-prep-stage")).not.toBeInTheDocument();
  });

  it("reports warm-up progress once the chain starts", () => {
    render(
      <DemoPrep {...base} preflight={null} stage="sweeping" detail="Sweep 1 of 2" />,
    );

    expect(screen.getByTestId("demo-prep-stage")).toHaveTextContent("Sweep 1 of 2");
  });

  it("locks the warm-up button while the chain is running", () => {
    // Pressing PREPARE twice would reset the demo out from under a sweep that
    // is already in flight.
    render(<DemoPrep {...base} preflight={null} stage="sweeping2" detail="Sweep 2" />);

    expect(screen.getByRole("button", { name: /PREPARING/ })).toBeDisabled();
  });

  it("triggers both actions", async () => {
    const user = userEvent.setup();
    const onCheck = vi.fn();
    const onWarmup = vi.fn();
    render(<DemoPrep {...base} preflight={null} onCheck={onCheck} onWarmup={onWarmup} />);

    await user.click(screen.getByRole("button", { name: /CHECK READINESS/ }));
    await user.click(screen.getByRole("button", { name: /PREPARE DEMO/ }));

    expect(onCheck).toHaveBeenCalled();
    expect(onWarmup).toHaveBeenCalled();
  });

  it("does not reset anything merely by being open", () => {
    // Opening the panel must be inert; only the button starts the chain.
    const onWarmup = vi.fn();
    render(<DemoPrep {...base} preflight={preflight()} onWarmup={onWarmup} />);

    expect(onWarmup).not.toHaveBeenCalled();
  });
});
