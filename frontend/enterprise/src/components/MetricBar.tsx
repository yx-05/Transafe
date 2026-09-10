/**
 * Screen A bottom panel — time-to-discovery before/after bars.
 * Widths are proportional to real metric values from /enterprise/overview.
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
