import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import MetricBar from "./MetricBar";
import type { OverviewMetric } from "../types/api";

const BASIS =
  "median minutes from fraud_cases.created_at to campaign_cases.joined_at; " +
  "before = cases ingested before their campaign existed, " +
  "after = cases ingested once it did";

const metrics: OverviewMetric[] = [
  {
    label: "TIME TO DISCOVERY",
    before_value: 12960,
    after_value: 41,
    unit: "min",
    lower_is_better: true,
    basis: BASIS,
    before_sample: 6,
    after_sample: 31,
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

  // "before 9 d ⇄ after 41 min" under a panel titled OUTCOME METRICS reads as
  // TranSafe's improvement over the prior world. It is not: both cohorts are
  // this system's own cases, split on whether the case predates its campaign.
  // The numbers are honest and the frame is not, so the frame has to say so —
  // visibly, not on hover, because the screenshot is what gets read.
  it("states what the two cohorts actually are", () => {
    render(<MetricBar metrics={metrics} />);
    expect(
      screen.getByText(/cases ingested before their campaign existed/i),
    ).toBeInTheDocument();
  });

  // Guard against over-correcting: no invented explanation when none was sent.
  it("says nothing about the comparison when the backend did not explain it", () => {
    render(<MetricBar metrics={[{ ...metrics[0], basis: null }]} />);
    expect(screen.queryByTestId("basis-TIME TO DISCOVERY")).toBeNull();
    expect(screen.getByText("41 min")).toBeInTheDocument();
  });

  // Two bars of identical length can rest on 2 cases or on 40, and the bar is
  // the same picture either way. The count belongs beside the half it
  // qualifies, not in a combined footnote — `before` and `after` are separately
  // strong or weak, and here they differ by 5x.
  it("shows how many cases each half's median rests on", () => {
    render(<MetricBar metrics={metrics} />);
    expect(screen.getByTestId("sample-before-TIME TO DISCOVERY")).toHaveTextContent("6");
    expect(screen.getByTestId("sample-after-TIME TO DISCOVERY")).toHaveTextContent("31");
  });

  // Same rule as basis: render what was sent, invent nothing. A "0" or an
  // "n=?" placeholder would be a claim about sample size the backend never made.
  it("shows no sample count when the backend did not send one", () => {
    render(
      <MetricBar metrics={[{ ...metrics[0], before_sample: null, after_sample: null }]} />,
    );
    expect(screen.queryByTestId("sample-before-TIME TO DISCOVERY")).toBeNull();
    expect(screen.queryByTestId("sample-after-TIME TO DISCOVERY")).toBeNull();
    expect(screen.getByText("9 d")).toBeInTheDocument();
  });
});
