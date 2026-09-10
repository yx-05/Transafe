import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import DiffViewer, { buildDiff, diffStats } from "./DiffViewer";

const before = "line one\nline two\n";
const after = "line one\nline two\nline three\n";

describe("buildDiff", () => {
  it("marks added lines", () => {
    const lines = buildDiff(before, after);
    expect(diffStats(lines)).toEqual({ added: 1, removed: 0 });
    expect(lines.find((l) => l.type === "add")?.text).toBe("line three");
  });

  it("marks removed lines", () => {
    const lines = buildDiff(after, before);
    expect(diffStats(lines)).toEqual({ added: 0, removed: 1 });
  });

  it("produces only context lines for identical input", () => {
    expect(diffStats(buildDiff(before, before))).toEqual({ added: 0, removed: 0 });
  });
});

describe("DiffViewer", () => {
  it("renders red/green lines with a summary", () => {
    render(<DiffViewer previous={before} next={after} previousLabel="v6" nextLabel="v7" />);
    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(screen.getByText("−0")).toBeInTheDocument();
    const added = screen
      .getByTestId("diff-viewer")
      .querySelectorAll('[data-difftype="add"]');
    expect(added).toHaveLength(1);
  });

  it("treats a missing previous version as a brand new artifact", () => {
    render(<DiffViewer previous={null} next={"a\nb\n"} />);
    expect(screen.getByText(/NEW ARTIFACT/)).toBeInTheDocument();
  });
});
