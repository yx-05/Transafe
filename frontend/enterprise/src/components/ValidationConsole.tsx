/**
 * Screen D — Campaign Validation Console.
 *
 * Visual rule: deterministic EVIDENCE on the left, LLM HYPOTHESIS on the right,
 * visually separated. An enterprise audience must be able to see at a glance
 * which claims are computed and which are generated.
 */

import { useState } from "react";
import StatusBadge from "./StatusBadge";
import type { CampaignDetail } from "../types/campaign";

interface Props {
  campaign: CampaignDetail;
  onApprove: (id: string) => void | Promise<void>;
  onReject: (id: string, reason: string) => void | Promise<void>;
  onEdit?: (id: string, edits: Record<string, unknown>) => void | Promise<void>;
  onViewDiff?: (artifactName: string, version: number) => void;
  busy?: boolean;
}

export function ValidationConsole({
  campaign,
  onApprove,
  onReject,
  onEdit,
  onViewDiff,
  busy = false,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(campaign.hypothesis.name);
  const [summary, setSummary] = useState(campaign.hypothesis.mo_summary);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  const decided = campaign.status !== "CANDIDATE" && campaign.status !== "PENDING_VALIDATION";

  return (
    <div className="validation" data-testid="validation-console">
      <header className="panel" style={{ padding: "8px 12px" }}>
        <div
          className="mono"
          style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}
        >
          <StatusBadge label={campaign.status} />
          <strong>{campaign.code}</strong>
          <span className="muted">confidence</span>
          <b>{campaign.confidence.toFixed(2)}</b>
          <span className="muted">·</span>
          <span>{campaign.case_count} cases</span>
          <span className="muted">·</span>
          <span>{campaign.customer_count} customers</span>
          <span className="muted">·</span>
          <span>{campaign.span_minutes ?? "—"} min span</span>
        </div>
      </header>

      <div className="validation-split">
        <section className="panel evidence-col" data-testid="evidence-column">
          <div className="panel-title">
            EVIDENCE <span className="col-tag computed">COMPUTED</span>
          </div>
          <div className="panel-body">
            {campaign.evidence.map((item) => (
              <div className="evidence-item" key={item.label}>
                <span className={item.passed ? "ok" : "no"}>
                  {item.passed ? "✓" : "✕"}
                </span>
                <span>
                  <span className="label">{item.label}</span>
                  {item.value}
                </span>
              </div>
            ))}
            <p className="muted mono" style={{ fontSize: 10.5, marginTop: 12 }}>
              Every line above is a deterministic computation over the case graph. No
              language model was involved in producing it.
            </p>
          </div>
        </section>

        <section className="panel hypothesis-col" data-testid="hypothesis-column">
          <div className="panel-title">
            HYPOTHESIS <span className="col-tag llm">LLM-GENERATED</span>
          </div>
          <div className="panel-body">
            {editing ? (
              <div style={{ display: "grid", gap: 8 }}>
                <label className="mono muted" style={{ fontSize: 10.5 }}>
                  NAME
                  <input
                    className="role-select"
                    style={{ width: "100%", marginTop: 4 }}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                <label className="mono muted" style={{ fontSize: 10.5 }}>
                  MO SUMMARY
                  <textarea
                    className="role-select"
                    style={{ width: "100%", marginTop: 4, minHeight: 110 }}
                    value={summary}
                    onChange={(e) => setSummary(e.target.value)}
                  />
                </label>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => {
                      void onEdit?.(campaign.id, { name, mo_summary: summary });
                      setEditing(false);
                    }}
                  >
                    SAVE EDITS
                  </button>
                  <button type="button" className="btn" onClick={() => setEditing(false)}>
                    CANCEL
                  </button>
                </div>
              </div>
            ) : (
              <>
                <dl className="kv">
                  <dt>Name</dt>
                  <dd>{campaign.hypothesis.name}</dd>
                  <dt>MO</dt>
                  <dd style={{ lineHeight: 1.6 }}>{campaign.hypothesis.mo_summary}</dd>
                </dl>

                <div className="mono" style={{ marginTop: 12 }}>
                  <div className="metric-label">NOVEL INDICATORS</div>
                  <ul style={{ margin: "4px 0 0 16px", padding: 0, fontSize: 11.5 }}>
                    {campaign.hypothesis.novel_indicators.map((ind) => (
                      <li key={ind} style={{ color: "var(--amber)" }}>
                        {ind}
                      </li>
                    ))}
                  </ul>
                </div>

                <div style={{ marginTop: 14 }}>
                  <div className="metric-label">PROPOSED ARTIFACTS</div>
                  {campaign.proposed_artifacts.map((a) => (
                    <div className="artifact-proposal" key={`${a.name}-${a.version}`}>
                      <StatusBadge
                        label={a.tier.toUpperCase()}
                        tone={a.tier === "core" ? "danger" : "info"}
                      />
                      <span>{a.name}</span>
                      <span className="muted">v{a.version}</span>
                      <span className="muted">→ {a.target_agent}</span>
                      {a.note && <span className="muted">↳ {a.note}</span>}
                      {onViewDiff && (
                        <button
                          type="button"
                          className="btn"
                          style={{ marginLeft: "auto" }}
                          onClick={() => onViewDiff(a.name, a.version)}
                        >
                          view diff
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </section>
      </div>

      {rejecting && (
        <div className="panel" style={{ padding: 10, display: "flex", gap: 8 }}>
          <input
            className="role-select"
            style={{ flex: 1 }}
            placeholder="reason for rejection"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            aria-label="reason for rejection"
          />
          <button
            type="button"
            className="btn btn-reject"
            disabled={!reason.trim()}
            onClick={() => {
              void onReject(campaign.id, reason.trim());
              setRejecting(false);
              setReason("");
            }}
          >
            CONFIRM REJECT
          </button>
          <button type="button" className="btn" onClick={() => setRejecting(false)}>
            CANCEL
          </button>
        </div>
      )}

      <div className="validation-actions">
        <button
          type="button"
          className="btn btn-approve"
          disabled={busy || decided}
          onClick={() => void onApprove(campaign.id)}
        >
          ✅ Approve
        </button>
        <button
          type="button"
          className="btn"
          disabled={busy || decided}
          onClick={() => setEditing((v) => !v)}
        >
          ✏ Edit
        </button>
        <button
          type="button"
          className="btn btn-reject"
          disabled={busy || decided}
          onClick={() => setRejecting(true)}
        >
          ❌ Reject
        </button>
      </div>
    </div>
  );
}

export default ValidationConsole;
