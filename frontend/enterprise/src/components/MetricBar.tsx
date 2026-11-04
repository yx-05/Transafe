/**
 * Screen A bottom panel — time-to-discovery before/after bars.
 * Widths are proportional to real metric values from /enterprise/overview.
 *
 * The panel title and the row tags are deliberately generic ("before ⇄ after"):
 * what is being compared is the *backend's* claim, not this component's, so
 * each metric renders its own `basis` verbatim rather than inheriting a meaning
 * from the heading. Today's single metric compares two cohorts of one
 * campaign's own cases — it is not a "before TranSafe" baseline, and a reader
 * who assumes it is has been misled by the frame rather than the number.
 * A metric with no `basis` gets no caption; none is invented here.
 *
 * `n=` beside each value is the sample the median rests on, per half rather
 * than combined — the two cohorts are separately strong or weak and routinely
 * differ by an order of magnitude. Absent counts render nothing rather than a
 * placeholder, for the same reason as `basis`.
 */

import type { OverviewMetric } from "../types/api";
import { humaniseDuration } from "../lib/format";

interface Props {
  metrics: OverviewMetric[];
}

export function MetricBar({ metrics }: Props) {
  return (
    <div className="panel metrics" data-testid="metric-bar">
      <div className="panel-title">OUTCOME METRICS · before ⇄ after</div>
      <div className="panel-body flush">
        {metrics.length === 0 ? (
          <p className="ticker-empty">no metrics yet</p>
        ) : (
          metrics.map((m) => {
            const max = Math.max(m.before_value, m.after_value, 1);
            const beforePct = (m.before_value / max) * 100;
            const afterPct = (m.after_value / max) * 100;
            return (
              <div className="metric" key={m.label} data-metric={m.label}>
                <div className="metric-label">{m.label}</div>
                {m.basis ? (
                  <p className="metric-basis" data-testid={`basis-${m.label}`}>
                    {m.basis}
                  </p>
                ) : null}
                <div className="metric-row">
                  <span className="tag">before</span>
                  <div className="metric-track">
                    <div
                      className="metric-fill before"
                      style={{ width: `${beforePct}%` }}
                      data-testid={`before-${m.label}`}
                    />
                  </div>
                  <span className="value">
                    <b>{humaniseDuration(m.before_value, m.unit)}</b>
                    {m.before_sample !== null ? (
                      <span
                        className="sample"
                        data-testid={`sample-before-${m.label}`}
                      >{` n=${m.before_sample}`}</span>
                    ) : null}
                  </span>
                </div>
                <div className="metric-row">
                  <span className="tag">after</span>
                  <div className="metric-track">
                    <div
                      className="metric-fill after"
                      style={{ width: `${Math.max(afterPct, 1)}%` }}
                      data-testid={`after-${m.label}`}
                    />
                  </div>
                  <span className="value">
                    <b>{humaniseDuration(m.after_value, m.unit)}</b>
                    {m.after_sample !== null ? (
                      <span
                        className="sample"
                        data-testid={`sample-after-${m.label}`}
                      >{` n=${m.after_sample}`}</span>
                    ) : null}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

export default MetricBar;
