import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import StatusBadge, { toneFor } from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders the label", () => {
    render(<StatusBadge label="CANDIDATE" />);
    expect(screen.getByText("CANDIDATE")).toBeInTheDocument();
  });

  it("derives a tone from known statuses", () => {
    expect(toneFor("APPROVED")).toBe("success");
    expect(toneFor("REJECTED")).toBe("danger");
    expect(toneFor("CANDIDATE")).toBe("warning");
    expect(toneFor("SOMETHING_ELSE")).toBe("neutral");
  });

  it("honours an explicit tone override", () => {
    render(<StatusBadge label="CORE" tone="danger" />);
    expect(screen.getByText("CORE")).toHaveAttribute("data-tone", "danger");
  });
});
