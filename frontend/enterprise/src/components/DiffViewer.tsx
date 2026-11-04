/**
 * Line-level red/green diff over the `diff` package.
 * Used by the Artifact Registry (Screen E) and the Validation Console (Screen D).
 */

import { useMemo } from "react";
import { diffLines } from "diff";

export interface DiffLine {
  type: "add" | "del" | "ctx";
  text: string;
}

export function buildDiff(previous: string, next: string): DiffLine[] {
  const parts = diffLines(previous ?? "", next ?? "");
  const out: DiffLine[] = [];
  for (const part of parts) {
    const lines = part.value.split("\n");
    // split() leaves a trailing empty string when the chunk ends with \n
    if (lines.length && lines[lines.length - 1] === "") lines.pop();
    for (const text of lines) {
      out.push({
        type: part.added ? "add" : part.removed ? "del" : "ctx",
        text,
      });
    }
  }
  return out;
}

export function diffStats(lines: DiffLine[]): { added: number; removed: number } {
  return {
    added: lines.filter((l) => l.type === "add").length,
    removed: lines.filter((l) => l.type === "del").length,
  };
}

interface Props {
  previous: string | null;
  next: string;
  previousLabel?: string;
  nextLabel?: string;
}

const SIGN = { add: "+", del: "-", ctx: " " } as const;

export function DiffViewer({ previous, next, previousLabel, nextLabel }: Props) {
  const lines = useMemo(() => buildDiff(previous ?? "", next ?? ""), [previous, next]);
  const stats = useMemo(() => diffStats(lines), [lines]);

  if (!previous) {
    return (
      <div data-testid="diff-viewer">
        <div className="diff-summary">
          NEW ARTIFACT · no previous version · <span className="add">
            +{next.split("\n").length}
          </span>
        </div>
        <div className="diff">
          {next.split("\n").map((text, i) => (
            <div className="diff-line add" key={i}>
              <span className="sign">+</span>
              <span>{text}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div data-testid="diff-viewer">
      <div className="diff-summary">
        {previousLabel ?? "previous"} → {nextLabel ?? "current"} ·{" "}
        <span className="add">+{stats.added}</span>{" "}
        <span className="del">−{stats.removed}</span>
      </div>
      <div className="diff">
        {lines.map((line, i) => (
          <div className={`diff-line ${line.type}`} key={i} data-difftype={line.type}>
            <span className="sign">{SIGN[line.type]}</span>
            <span>{line.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default DiffViewer;
