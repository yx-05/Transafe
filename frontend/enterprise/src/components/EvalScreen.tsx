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
  /** Run one blue-team cycle: generalise a rule from the misses, publish it, re-score. */
  onAdapt?: () => void | Promise<void>;
  adapting?: boolean;
}

function pct(n: number, d: number): number {
  return d ? Math.round((n / d) * 1000) / 10 : 0;
}

/**
 * Convert a 0–1 metric from the API into a 0–100 percentage, or `null` when
 * the field is missing (an older run persisted before the split existed).
 * Returning `null` rather than 0 matters: a fabricated zero would read as
 * "the red team beat us completely" instead of "not measured".
 */
function fraction(value: number | undefined | null): number | null {
  return typeof value === "number" ? Math.round(value * 1000) / 10 : null;
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

/**
 * Chart palette, collected in one place so legibility is fixed once.
 *
 * These were `#6b7280` and `#55606f`. Measured against the panel background
 * (`#11161f`) they come out at 3.75:1 and 2.84:1 — both under the 4.5:1 AA
 * floor, and the first was painting the axis ticks, i.e. the smallest text on
 * the screen. At 2.84:1 the "before" bar read as an empty track rather than a
 * second datum, which defeats the point of a paired bar. The replacements sit
 * at 7.06:1 and 5.94:1 and keep the before/after hierarchy intact.
 */
const AXIS = "#9aa2b1";
const GRID = "#2b3546";
const BAR_BEFORE = "#8b94a6";
const BAR_AFTER = "#ffb74d";

interface BarDatum {
  name: string;
  value: number;
  tone: "before" | "after";
  /** Counts behind the percentage, shown in the panel title. */
  raw?: string;
}

/**
 * One paired before/after bar chart.
 *
 * All three charts are structurally identical, so they share a single
 * definition: three copies is how the red-team chart ended up with different
 * axis contrast from the other two in the first place.
 */
function PairedBars({
  data,
  seriesName,
  afterFill,
}: {
  data: BarDatum[];
  seriesName: string;
  afterFill: string;
}) {
  return (
    <ResponsiveContainer width="100%" height="100%" minHeight={180}>
      <BarChart data={data} layout="vertical" margin={{ left: 24 }}>
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" domain={[0, 100]} stroke={AXIS} fontSize={12} unit="%" />
        <YAxis
          type="category"
          dataKey="name"
          stroke={AXIS}
          fontSize={12}
          width={170}
        />
        <Tooltip
          contentStyle={{ background: "#11161f", border: "1px solid #232a38" }}
          formatter={(v: number) => `${v}%`}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="value" name={seriesName} barSize={28}>
          {data.map((d) => (
            <Cell key={d.name} fill={d.tone === "after" ? afterFill : BAR_BEFORE} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function EvalScreen({ comparison, onRun, running = false, onAdapt, adapting = false }: Props) {
  const { before, after } = comparison;

  const detectionData: BarDatum[] = [
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

  const fpData: BarDatum[] = [
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

  // The red-team corpus is the adversarial half of the eval: mutations of the
  // live script (entities swapped, language switched, phases reordered) that
  // test whether the learned defence survives an attacker who adapts.
  const redteamBefore = fraction(before?.redteam_detection);
  const redteamAfter = fraction(after?.redteam_detection);
  const redteamData: BarDatum[] = [
    { name: runLabel(before, "before"), value: redteamBefore ?? 0, tone: "before" },
    { name: runLabel(after, "after"), value: redteamAfter ?? 0, tone: "after" },
  ];
  const redteamRaw = (v: number | null) => (v === null ? "—" : `${v}%`);

  // Read the corpus size from the payload rather than hard-coding 30: the
  // offline fixture is a smaller corpus, and a label that outranks its own
  // numbers is worse than no label.
  const variantCount = (after ?? before)?.total ?? 0;

  return (
    <div className="eval" data-testid="eval-screen">
      <div className="eval-summary">
        <Stat
          label={variantCount ? `DETECTION RATE · ALL ${variantCount}` : "DETECTION RATE"}
          before={before ? pct(before.detected, before.total) : null}
          after={after ? pct(after.detected, after.total) : null}
          suffix="%"
          lowerIsBetter={false}
        />
        <Stat
          label="RED-TEAM DETECTION · 10"
          before={redteamBefore}
          after={redteamAfter}
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
            {after ? (
              // One unbreakable entry per version. Joined into a single string,
              // the long SCAM-027_* names wrapped mid-token, so
              // "SCAM-027_compliance_brief v1" printed across two lines and
              // read as two separate artifacts.
              <span style={{ display: "flex", flexWrap: "wrap", gap: "2px 12px" }}>
                {Object.entries(after.artifact_ver).map(([k, v]) => (
                  <span key={k} style={{ whiteSpace: "nowrap" }}>
                    {k} v{v}
                  </span>
                ))}
              </span>
            ) : (
              "—"
            )}
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
          {onAdapt && (
            <button
              type="button"
              className="btn"
              style={{ marginTop: 8, marginLeft: onRun ? 8 : 0 }}
              onClick={() => void onAdapt()}
              disabled={adapting || running}
              title={
                "Red-team half of the loop: score the corpus, generalise one " +
                "structural rule from the misses, publish it if its confidence " +
                "clears the threshold, then re-score. Publishes a new core version."
              }
            >
              {adapting ? "ADAPTING…" : "▶ RUN ADAPTATION"}
            </button>
          )}
        </div>
      </div>

      <div className="eval-charts">
        <section className="panel" data-testid="detection-chart">
          <div className="panel-title">
            DETECTION RATE · all variants · higher is better
            <span className="muted" style={{ marginLeft: "auto", letterSpacing: 0 }}>
              {detectionData[0].raw} → {detectionData[1].raw}
            </span>
          </div>
          <div className="panel-body">
            <PairedBars
              data={detectionData}
              seriesName="detection %"
              afterFill={BAR_AFTER}
            />
          </div>
        </section>

        <section className="panel" data-testid="redteam-chart">
          <div className="panel-title">
            RED-TEAM DETECTION · mutations · higher is better
            <span className="muted" style={{ marginLeft: "auto", letterSpacing: 0 }}>
              {redteamRaw(redteamBefore)} → {redteamRaw(redteamAfter)}
            </span>
          </div>
          <div className="panel-body">
            <PairedBars
              data={redteamData}
              seriesName="red-team detection %"
              afterFill={BAR_AFTER}
            />
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
            <PairedBars data={fpData} seriesName="false positive %" afterFill="#ef5350" />
          </div>
        </section>
      </div>
    </div>
  );
}

export default EvalScreen;
