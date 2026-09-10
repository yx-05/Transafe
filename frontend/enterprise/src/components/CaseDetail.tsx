/**
 * Screen B — Living Case.
 *
 * The detail that sells it: a novel phrase is highlighted on the exact
 * transcript line it was said, proving the extraction is grounded.
 */

import { useNavigate } from "react-router-dom";
import StatusBadge from "./StatusBadge";
import type { CaseDetail as CaseDetailModel, TranscriptLine } from "../types/campaign";

/** Split a line into highlighted / plain segments around its novel phrases. */
export function highlightSegments(
  text: string,
  phrases: string[] = [],
): { text: string; novel: boolean }[] {
  const found = phrases
    .map((p) => ({ phrase: p, index: text.toLowerCase().indexOf(p.toLowerCase()) }))
    .filter((m) => m.index >= 0)
    .sort((a, b) => a.index - b.index);

  if (!found.length) return [{ text, novel: false }];

  const out: { text: string; novel: boolean }[] = [];
  let cursor = 0;
  for (const m of found) {
    if (m.index < cursor) continue;
    if (m.index > cursor) out.push({ text: text.slice(cursor, m.index), novel: false });
    out.push({ text: text.slice(m.index, m.index + m.phrase.length), novel: true });
    cursor = m.index + m.phrase.length;
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor), novel: false });
  return out;
}

function TranscriptRow({ line }: { line: TranscriptLine }) {
  const segments = highlightSegments(line.text, line.novel_phrases ?? []);
  const hasNovel = segments.some((s) => s.novel);
  return (
    <div className="transcript-line" data-novel={hasNovel ? "true" : "false"}>
      <span className="tc">{line.t}</span>
      <span className={`spk ${line.speaker}`}>{line.speaker}</span>
      <span className="txt">
        {segments.map((s, i) =>
          s.novel ? (
            <mark className="novel" key={i}>
              {s.text}
            </mark>
          ) : (
            <span key={i}>{s.text}</span>
          ),
        )}
        {hasNovel && <span className="novel-tag">⚠ NOVEL</span>}
      </span>
      <span className="sc">{line.score === null ? "—" : `▓${line.score}`}</span>
    </div>
  );
}

interface Props {
  detail: CaseDetailModel;
}

export function CaseDetail({ detail }: Props) {
  const navigate = useNavigate();
  const maxTrace = Math.max(1, ...detail.trace.map((t) => t.duration_ms));

  return (
    <div className="case-view" data-testid="case-detail" style={{ height: "100%" }}>
      <div className="case-header">
        <strong>Case #{detail.case_number}</strong>
        <span className="muted">·</span>
        <span>{detail.scam_type}</span>
        <StatusBadge label={detail.risk_label} />
        <span className="mono">{detail.risk_score}</span>
        <StatusBadge label={detail.discovery_state} />
        {detail.campaign_id && (
          <button
            type="button"
            className="btn"
            onClick={() => navigate(`/validation/${detail.campaign_id}`)}
          >
            🔗 {detail.campaign_name ?? detail.campaign_id}
          </button>
        )}
      </div>

      <div className="case-grid">
        <section className="panel">
          <div className="panel-title">TRANSCRIPT</div>
          <div className="panel-body">
            {detail.transcript.length === 0 ? (
              <p className="ticker-empty">no transcript captured</p>
            ) : (
              detail.transcript.map((line, i) => <TranscriptRow line={line} key={i} />)
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">MO FINGERPRINT</div>
          <div className="panel-body">
            {detail.mo ? (
              <dl className="kv">
                <dt>Impersonates</dt>
                <dd>{detail.mo.impersonates ?? "—"}</dd>
                <dt>Pretext</dt>
                <dd>{detail.mo.pretext ?? "—"}</dd>
                <dt>Phases</dt>
                <dd>
                  <span className="phase-chain">
                    {detail.mo.phases.map((p, i) => (
                      <span key={p}>
                        <span className="phase">{p}</span>
                        {i < detail.mo!.phases.length - 1 && (
                          <span className="muted"> ▸ </span>
                        )}
                      </span>
                    ))}
                  </span>
                </dd>
                <dt>Money ask at</dt>
                <dd>{detail.mo.money_ask_at ?? "—"}</dd>
                {detail.mo.channel && (
                  <>
                    <dt>Channel</dt>
                    <dd>{detail.mo.channel}</dd>
                  </>
                )}
                {detail.mo.language && (
                  <>
                    <dt>Language</dt>
                    <dd>{detail.mo.language}</dd>
                  </>
                )}
              </dl>
            ) : (
              <p className="ticker-empty">MO not extracted yet</p>
            )}
            {detail.narrative && (
              <p className="mono muted" style={{ marginTop: 12, lineHeight: 1.6 }}>
                {detail.narrative}
              </p>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">ENTITIES</div>
          <div className="panel-body">
            {detail.entities.length === 0 ? (
              <p className="ticker-empty">no entities resolved</p>
            ) : (
              detail.entities.map((e) => (
                <button
                  type="button"
                  className="entity-row"
                  key={e.id}
                  onClick={() => navigate(`/graph?focus=${encodeURIComponent(e.id)}`)}
                  title="jump to graph"
                >
                  <span className={`entity-type ${e.entity_type}`}>{e.entity_type}</span>
                  <span>{e.value_raw}</span>
                  <span className="count">({e.case_count} cases)</span>
                </button>
              ))
            )}
            <p className="muted mono" style={{ fontSize: 10.5, marginTop: 8 }}>
              ↑ click → jump to graph
            </p>
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">EXECUTION TRACE</div>
          <div className="panel-body">
            {detail.trace.length === 0 ? (
              <p className="ticker-empty">no trace recorded</p>
            ) : (
              detail.trace.map((step) => (
                <div className="trace-row" key={step.name}>
                  <span className="muted">{step.name}</span>
                  <div
                    className="trace-bar"
                    style={{ width: `${(step.duration_ms / maxTrace) * 100}%` }}
                  />
                  <span className="meta">
                    {step.duration_ms}ms{step.detail ? ` · ${step.detail}` : ""}
                  </span>
                </div>
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

export default CaseDetail;
