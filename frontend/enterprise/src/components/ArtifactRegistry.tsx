/**
 * Screen E — Artifact Registry.
 *
 * Two tabs doing argumentative work: CAMPAIGN PACKS grows with every campaign,
 * CORE barely moves. That is the scaling answer rendered as a screen.
 */

import { useEffect, useMemo, useState } from "react";
import DiffViewer from "./DiffViewer";
import StatusBadge from "./StatusBadge";
import { shortDate } from "../lib/format";
import type { ArtifactDetail, ArtifactGroup, ArtifactVersion } from "../types/campaign";

export type RegistryTab = "core" | "pack";

interface Props {
  groups: ArtifactGroup[];
  activeTab: RegistryTab;
  onTabChange: (tab: RegistryTab) => void;
  detail: ArtifactDetail | null;
  onSelect: (name: string, version: number) => void;
  onRollback?: (name: string, version: number) => void | Promise<void>;
  busy?: boolean;
}

function effectivenessLabel(v: ArtifactVersion): {
  text: string;
  cls: string;
} | null {
  if (!v.effectiveness) return null;
  const { detected, total, fp } = v.effectiveness;
  const ratio = total ? detected / total : 0;
  return {
    text: `${detected}/${total} ✓${fp ? ` · ${fp} FP` : ""}`,
    cls: ratio >= 0.95 ? "good" : "mid",
  };
}

export function ArtifactRegistry({
  groups,
  activeTab,
  onTabChange,
  detail,
  onSelect,
  onRollback,
  busy = false,
}: Props) {
  const visible = useMemo(
    () => groups.filter((g) => g.tier === activeTab),
    [groups, activeTab],
  );

  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  useEffect(() => {
    if (detail) setSelectedKey(`${detail.name}@${detail.version}`);
  }, [detail]);

  return (
    <div className="registry" data-testid="artifact-registry">
      <section className="panel">
        <div className="tabs">
          <button
            type="button"
            className={`tab ${activeTab === "core" ? "active" : ""}`}
            onClick={() => onTabChange("core")}
            aria-pressed={activeTab === "core"}
          >
            CORE
          </button>
          <button
            type="button"
            className={`tab ${activeTab === "pack" ? "active" : ""}`}
            onClick={() => onTabChange("pack")}
            aria-pressed={activeTab === "pack"}
          >
            CAMPAIGN PACKS
          </button>
        </div>

        <div className="panel-body flush">
          {visible.length === 0 ? (
            <p className="ticker-empty">no artifacts in this tier yet</p>
          ) : (
            visible.map((group) => (
              <div className="artifact-group" key={group.name}>
                <h4>
                  {group.name}{" "}
                  <span className="muted" style={{ fontSize: 10.5 }}>
                    → {group.target_agent}
                  </span>
                </h4>
                {group.versions.map((v) => {
                  const eff = effectivenessLabel(v);
                  const key = `${v.name}@${v.version}`;
                  return (
                    <button
                      type="button"
                      key={key}
                      className={`version-row ${selectedKey === key ? "selected" : ""}`}
                      onClick={() => {
                        setSelectedKey(key);
                        onSelect(v.name, v.version);
                      }}
                    >
                      <span className="ver">v{v.version}</span>
                      <span>{shortDate(v.created_at)}</span>
                      {v.source_campaigns.length > 1 && (
                        <span className="muted">
                          from {v.source_campaigns.length} campaigns
                        </span>
                      )}
                      <StatusBadge label={v.status} />
                      {eff && <span className={`eff ${eff.cls}`}>{eff.text}</span>}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>
      </section>

      <section className="panel">
        <div className="panel-title">
          {detail ? `${detail.name} · v${detail.version}` : "DIFF"}
          {detail && (
            <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
              <span className="muted" style={{ letterSpacing: 0 }}>
                by {detail.created_by}
                {detail.approved_by ? ` · approved by ${detail.approved_by}` : ""}
              </span>
              {onRollback && detail.previous_version !== null && (
                <button
                  type="button"
                  className="btn"
                  disabled={busy}
                  onClick={() => void onRollback(detail.name, detail.previous_version!)}
                >
                  ↩ ROLLBACK to v{detail.previous_version}
                </button>
              )}
            </span>
          )}
        </div>
        <div className="panel-body flush">
          {detail ? (
            <>
              {detail.source_campaigns.length > 0 && (
                <div className="diff-summary">
                  generalised from {detail.source_campaigns.join(" · ")}
                </div>
              )}
              <DiffViewer
                previous={detail.previous_content}
                next={detail.content}
                previousLabel={
                  detail.previous_version !== null ? `v${detail.previous_version}` : undefined
                }
                nextLabel={`v${detail.version}`}
              />
            </>
          ) : (
            <p className="empty-state">select a version to see what changed</p>
          )}
        </div>
      </section>
    </div>
  );
}

export default ArtifactRegistry;
