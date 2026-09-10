import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import CaseDetail, { highlightSegments } from "./CaseDetail";
import { mockCaseDetail } from "../services/mockData";

function renderCase() {
  return render(
    <MemoryRouter>
      <CaseDetail detail={mockCaseDetail("case-24")} />
    </MemoryRouter>,
  );
}

describe("highlightSegments", () => {
  it("returns a single plain segment when nothing is novel", () => {
    expect(highlightSegments("hello world", [])).toEqual([
      { text: "hello world", novel: false },
    ]);
  });

  it("splits the line around the novel phrase", () => {
    expect(highlightSegments("pindah ke akaun selamat now", ["akaun selamat"])).toEqual([
      { text: "pindah ke ", novel: false },
      { text: "akaun selamat", novel: true },
      { text: " now", novel: false },
    ]);
  });

  it("ignores phrases that are not on this line", () => {
    const out = highlightSegments("nothing here", ["akaun selamat"]);
    expect(out.some((s) => s.novel)).toBe(false);
  });
});

describe("CaseDetail", () => {
  it("renders the transcript", () => {
    renderCase();
    expect(screen.getByText(/pegawai dari Bank Negara/)).toBeInTheDocument();
  });

  it("highlights novel phrases on their own utterance line", () => {
    renderCase();
    const mark = screen.getByText("akaun selamat sementara");
    expect(mark.tagName).toBe("MARK");
    const line = mark.closest(".transcript-line");
    expect(line).toHaveAttribute("data-novel", "true");
    expect(line?.textContent).toContain("00:22");
  });

  it("leaves non-novel lines unmarked", () => {
    renderCase();
    const line = screen.getByText("Ya, kenapa?").closest(".transcript-line");
    expect(line).toHaveAttribute("data-novel", "false");
  });

  it("renders the MO fingerprint phase chain", () => {
    renderCase();
    expect(screen.getByText("Bank Negara Malaysia")).toBeInTheDocument();
    for (const phase of ["authority", "fear", "isolation", "urgency", "safe-account"]) {
      expect(screen.getByText(phase)).toBeInTheDocument();
    }
  });

  it("lists entities with their case counts", () => {
    renderCase();
    expect(screen.getByText("1592 8834 0021")).toBeInTheDocument();
    expect(screen.getByText("(7 cases)")).toBeInTheDocument();
  });

  it("renders the execution trace", () => {
    renderCase();
    expect(screen.getByText("phone_worker")).toBeInTheDocument();
    expect(screen.getByText(/840ms · groq 612 tok/)).toBeInTheDocument();
  });
});
