/**
 * Demo preparation panel — readiness verdict and warm-up progress.
 *
 * Opens from the header, beside RESET, and exists for one reason: everything
 * it reports is something you would otherwise find out from the front of a
 * room. It reads nothing on its own; the data and the warm-up chain live in
 * `useDemoPrep`.
 *
 * The verdict is rendered as four distinct states rather than a green light.
 * `warn` and `info` are not failures, and showing them as failures would teach
 * the operator that the verdict is noise.
 */

import type { PreflightCheck, PreflightResponse } from "../types/api";
import type { PrepStage } from "../hooks/useDemoPrep";

const ICON: Record<PreflightCheck["status"], string> = {
  pass: "✓",
  warn: "!",
  fail: "✕",
  info: "·",
};

const LABEL: Record<PreflightCheck["status"], string> = {
  pass: "PASS",
  warn: "WARN",
  fail: "FAIL",
  info: "INFO",
};

interface Props {
  preflight: PreflightResponse | null;
  checking: boolean;
  stage: PrepStage;
  detail: string;
  onCheck: () => void | Promise<void>;
  onWarmup: () => void | Promise<void>;
  onClose: () => void;
}

export function DemoPrep({
  preflight,
  checking,
  stage,
  detail,
  onCheck,
  onWarmup,
  onClose,
}: Props) {
  const busy = stage === "resetting" || stage === "sweeping" || stage === "sweeping2";

  return (
    <div className="demo-prep" data-testid="demo-prep">
      <div className="demo-prep-head">
        <span className="k">DEMO PREPARATION</span>
        <button type="button" className="btn" onClick={onClose} title="Close">
          ✕
        </button>
      </div>

      <div className="demo-prep-actions">
        <button
          type="button"
          className="btn"
          onClick={() => void onCheck()}
          disabled={checking}
          title="Check every dependency this demo needs, without changing anything"
        >
          {checking ? "CHECKING…" : "CHECK READINESS"}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => void onWarmup()}
          disabled={busy}
          title="RESET, then run discovery twice — the second sweep is the one that promotes"
        >
          {busy ? "PREPARING…" : "PREPARE DEMO"}
        </button>
      </div>

      {/* The chain starts on a click, so an empty detail on a fresh panel is
          not a state worth announcing. */}
      {stage !== "idle" && (
        <div
          className={`demo-prep-stage ${stage === "ready" ? "ok" : ""} ${
            stage === "failed" ? "bad" : ""
          }`}
          data-testid="demo-prep-stage"
        >
          {detail || stage}
        </div>
      )}

      {preflight && (
        <div className="demo-prep-checks" data-testid="demo-prep-checks">
          <div className={`demo-prep-summary ${preflight.ok ? "ok" : "bad"}`}>
            {preflight.summary}
          </div>
          {preflight.checks.length === 0 ? (
            <div className="muted" style={{ padding: "6px 0" }}>
              No checks ran — the backend did not answer.
            </div>
          ) : (
            preflight.checks.map((check) => (
              <div key={check.name} className={`demo-prep-check ${check.status}`}>
                <span className="icon">{ICON[check.status]}</span>
                <span className="name">{check.name}</span>
                <span className="verdict">{LABEL[check.status]}</span>
                <span className="detail">{check.detail}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export default DemoPrep;
