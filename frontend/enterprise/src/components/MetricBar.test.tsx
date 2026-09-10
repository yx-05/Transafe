import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import MetricBar from "./MetricBar";
import type { OverviewMetric } from "../types/api";

const metrics: OverviewMetric[] = [
  {
    label: "TIME TO DISCOVERY",
    before_value: 12960,
    after_value: 41,
    unit: "min",
    lower_is_better: true,
  },
];

describe("MetricBar", () => {
  it("renders an empty state without metrics", () => {
    render(<MetricBar metrics={[]} />);
    expect(screen.getByText(/no metrics yet/i)).toBeInTheDocument();
  });

  it("humanises long durations", () => {
    render(<MetricBar metrics={metrics} />);
    expect(screen.getByText("9 d")).toBeInTheDocument();
    expect(screen.getByText("41 min")).toBeInTheDocument();
  });

  it("scales bar width against the larger of the two values", () => {
    render(<MetricBar metrics={metrics} />);
    const before = screen.getByTestId("before-TIME TO DISCOVERY");
    const after = screen.getByTestId("after-TIME TO DISCOVERY");
    expect(before).toHaveStyle({ width: "100%" });
    expect(parseFloat((after as HTMLElement).style.width)).toBeLessThan(2);
  });
});
