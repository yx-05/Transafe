/**
 * Screen F — Evaluation.
 *
 * Paired before/after bars. The false-positive row is rendered with exactly
 * the same visual weight as the detection row: a system that learns must also
 * be shown not to over-trigger.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EvalComparison, EvalRunSummary } from "../types/api";

interface Props {
  comparison: EvalComparison;
  onRun?: () => void | Promise<void>;
  running?: boolean;
}

function pct(n: number, d: number): number {
  return d ? Math.round((n / d) * 1000) / 10 : 0;
}

function Stat({
  label,
  before,
  after,
  suffix,
  lowerIsBetter,
}: {
  label: string;
  before: number | null;
  after: number | null;
  suffix: string;
  lowerIsBetter: boolean;
}) {
  const delta = before !== null && after !== null ? after - before : null;
  const good = delta === null ? false : lowerIsBetter ? delta <= 0 : delta >= 0;
  return (
    <div className="stat">
      <div className="k">{label}</div>
      <div className={`v ${delta === null ? "" : good ? "good" : "bad"}`}>
        {after === null ? "—" : `${after}${suffix}`}
      </div>
      <div className="d">
        was {before === null ? "—" : `${before}${suffix}`}
        {delta !== null && (
          <>
            {" "}
            · {delta > 0 ? "+" : ""}
            {Math.round(delta * 10) / 10}
            {suffix}
          </>
        )}
      </div>
    </div>
  );
}

function runLabel(run: EvalRunSummary | null, fallback: string): string {
  return run?.label ?? fallback;
}

export function EvalScreen({ comparison, onRun, running = false }: Props) {
  const { before, after } = comparison;

  const detectionData = [
    {
      name: runLabel(before, "before"),
      value: before ? pct(before.detected, before.total) : 0,
      raw: before ? `${before.detected}/${before.total}` : "—",
      tone: "before",
    },
    {
      name: runLabel(after, "after"),
      value: after ? pct(after.detected, after.total) : 0,
      raw: after ? `${after.detected}/${after.total}` : "—",
      tone: "after",
    },
  ];

  const fpData = [
    {
      name: runLabel(before, "before"),
      value: before ? pct(before.false_positives, before.fp_total) : 0,
      raw: before ? `${before.false_positives}/${before.fp_total}` : "—",
      tone: "before",
    },
    {
      name: runLabel(after, "after"),
      value: after ? pct(after.false_positives, after.fp_total) : 0,
      raw: after ? `${after.false_positives}/${after.fp_total}` : "—",
      tone: "after",
    },
  ];

  return (
    <div className="eval" data-testid="eval-screen">
      <div className="eval-summary">
        <Stat
          label="DETECTION RATE"
          before={before ? pct(before.detected, before.total) : null}
          after={after ? pct(after.detected, after.total) : null}
          suffix="%"
          lowerIsBetter={false}
        />
        <Stat
          label="FALSE POSITIVE RATE"
          before={before ? pct(before.false_positives, before.fp_total) : null}
          after={after ? pct(after.false_positives, after.fp_total) : null}
          suffix="%"
          lowerIsBetter
        />
        <Stat
          label="MEAN LATENCY"
          before={before?.mean_latency_ms ?? null}
          after={after?.mean_latency_ms ?? null}
          suffix="ms"
          lowerIsBetter
        />
        <div className="stat">
          <div className="k">ARTIFACT VERSIONS</div>
          <div className="v" style={{ fontSize: 13, lineHeight: 1.5 }}>
            {after
              ? Object.entries(after.artifact_ver)
                  .map(([k, v]) => `${k} v${v}`)
                  .join(" · ")
              : "—"}
          </div>
          {onRun && (
            <button
              type="button"
              className="btn btn-primary"
              style={{ marginTop: 8 }}
              onClick={() => void onRun()}
              disabled={running}
            >
              {running ? "RUNNING…" : "▶ RUN EVAL"}
            </button>
          )}
        </div>
      </div>

      <div className="eval-charts">
        <section className="panel" data-testid="detection-chart">
          <div className="panel-title">
            DETECTION RATE · higher is better
            <span className="muted" style={{ marginLeft: "auto", letterSpacing: 0 }}>
              {detectionData[0].raw} → {detectionData[1].raw}
            </span>
          </div>
          <div className="panel-body">
            <ResponsiveContainer width="100%" height="100%" minHeight={180}>
              <BarChart data={detectionData} layout="vertical" margin={{ left: 24 }}>
                <CartesianGrid stroke="#1b2230" horizontal={false} />
                <XAxis
                  type="number"
                  domain={[0, 100]}
                  stroke="#6b7280"
                  fontSize={11}
                  unit="%"
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  stroke="#6b7280"
                  fontSize={11}
                  width={150}
                />
                <Tooltip
                  contentStyle={{ background: "#11161f", border: "1px solid #232a38" }}
                  formatter={(v: number) => `${v}%`}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="value" name="detection %" barSize={26}>
                  {detectionData.map((d) => (
                    <Cell key={d.name} fill={d.tone === "after" ? "#FFB74D" : "#55606f"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="panel" data-testid="false-positive-chart">
          <div className="panel-title">
            FALSE POSITIVE RATE · lower is better
            <span className="muted" style={{ marginLeft: "auto", letterSpacing: 0 }}>
              {fpData[0].raw} → {fpData[1].raw}
            </span>
          </div>
          <div className="panel-body">
            <ResponsiveContainer width="100%" height="100%" minHeight={180}>
              <BarChart data={fpData} layout="vertical" margin={{ left: 24 }}>
                <CartesianGrid stroke="#1b2230" horizontal={false} />
                <XAxis
                  type="number"
                  domain={[0, 100]}
                  stroke="#6b7280"
                  fontSize={11}
                  unit="%"
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  stroke="#6b7280"
                  fontSize={11}
                  width={150}
                />
                <Tooltip
                  contentStyle={{ background: "#11161f", border: "1px solid #232a38" }}
                  formatter={(v: number) => `${v}%`}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="value" name="false positive %" barSize={26}>
                  {fpData.map((d) => (
                    <Cell key={d.name} fill={d.tone === "after" ? "#EF5350" : "#55606f"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      </div>
    </div>
  );
}

export default EvalScreen;
