import React from 'react';
import type { XaiReport } from '../types/api';

interface XaiReportModalProps {
  report: XaiReport | null;
  onClose: () => void;
}

const tierColor = (tier: string): { bg: string; border: string; color: string; icon: string; label: string } => {
  switch (tier) {
    case 'HIGH':
      return { bg: 'rgba(186, 26, 26, 0.1)', border: '1px solid #ba1a1a', color: '#ba1a1a', icon: 'gpp_bad', label: 'HIGH RISK' };
    case 'MEDIUM':
      return { bg: 'rgba(245, 158, 11, 0.12)', border: '1px solid #f59e0b', color: '#b45309', icon: 'warning', label: 'MEDIUM RISK' };
    default:
      return { bg: 'rgba(16, 185, 129, 0.1)', border: '1px solid #10b981', color: '#047857', icon: 'verified_user', label: 'LOW RISK' };
  }
};

export const XaiReportModal: React.FC<XaiReportModalProps> = ({ report, onClose }) => {
  if (!report) return null;
  const tier = tierColor(report.risk_tier);
  const formattedUnfreeze = (() => {
    if (!report.unfreeze_at) return null;
    try {
      const d = new Date(report.unfreeze_at as any);
      if (isNaN(d.getTime())) return String(report.unfreeze_at);
      return d.toLocaleString();
    } catch (err) {
      return String(report.unfreeze_at);
    }
  })();

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0,0,0,0.6)',
        backdropFilter: 'blur(6px)',
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px',
      }}
      onClick={onClose}
    >
      <div
        style={{
          backgroundColor: '#ffffff',
          borderRadius: '24px',
          maxWidth: '720px',
          width: '100%',
          maxHeight: '85vh',
          overflowY: 'auto',
          boxShadow: '0 24px 60px rgba(0,0,0,0.3)',
          border: '1px solid var(--surface-container)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '20px 24px',
            borderBottom: '1px solid var(--surface-container)',
            gap: '12px',
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            <h2 style={{ fontSize: '20px', fontWeight: 800, color: 'var(--on-surface)', margin: 0 }}>
              Explainable AI (XAI) Report
            </h2>
            <span
              style={{
                padding: '4px 10px',
                borderRadius: '999px',
                fontSize: '11px',
                fontWeight: 800,
                backgroundColor: tier.bg,
                border: tier.border,
                color: tier.color,
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>{tier.icon}</span>
              {tier.label} ({report.risk_score}/100)
            </span>
          </div>
          <button
            onClick={onClose}
            aria-label="Close report"
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--secondary)', padding: '4px' }}
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Verdict Summary */}
          <div style={{ padding: '16px', borderRadius: '16px', backgroundColor: 'var(--surface-container-low)', border: '1px solid var(--surface-container)' }}>
            <h3 style={{ fontSize: '12px', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--primary)', marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>description</span>
              Verdict Summary
            </h3>
            <p style={{ fontSize: '14px', fontWeight: 600, color: 'var(--on-surface)', margin: 0 }}>
              {report.verdict_summary}
            </p>
            {report.verdict_summary_ms && (
              <p style={{ fontSize: '13px', color: 'var(--secondary)', fontStyle: 'italic', margin: '8px 0 0' }}>
                <strong>MS:</strong> {report.verdict_summary_ms}
              </p>
            )}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', marginTop: '12px', fontSize: '12px', color: 'var(--secondary)' }}>
              <span><strong>Action Taken:</strong> {report.action_taken}</span>
              {formattedUnfreeze && (
                <span><strong>Cooling Off Until:</strong> {formattedUnfreeze}</span>
              )}
              {report.case_id && <span><strong>Case ID:</strong> <code style={{ color: 'var(--primary)' }}>{report.case_id}</code></span>}
            </div>
          </div>

          {/* Linked Case */}
          {report.associated_case_id && (
            <div style={{ padding: '14px', borderRadius: '16px', backgroundColor: 'rgba(0, 84, 214, 0.06)', border: '1px solid rgba(0, 84, 214, 0.2)' }}>
              <h4 style={{ fontSize: '13px', fontWeight: 800, color: 'var(--primary)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>link</span>
                Linked Case Context
              </h4>
              <p style={{ fontSize: '12px', color: 'var(--on-surface-variant)', margin: 0 }}>
                This analysis accounted for the selected case{' '}
                <strong style={{ color: 'var(--primary)', fontFamily: 'monospace' }}>{report.associated_case_id}</strong>.
                Its call transcripts and extracted accounts were cross-checked against this transfer by the agents below.
              </p>
            </div>
          )}

          {/* Recommendation */}
          {report.recommendation && (
            <div style={{ padding: '14px', borderRadius: '16px', backgroundColor: 'rgba(245, 158, 11, 0.08)', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
              <h4 style={{ fontSize: '13px', fontWeight: 800, color: '#b45309', marginBottom: '6px' }}>
                💡 Recommendation
              </h4>
              <p style={{ fontSize: '13px', color: 'var(--on-surface)', margin: 0 }}>{report.recommendation}</p>
            </div>
          )}

          {/* Activated Workers */}
          <div>
            <h4 style={{ fontSize: '13px', fontWeight: 800, color: 'var(--on-surface)', marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span className="material-symbols-outlined" style={{ fontSize: '16px', color: 'var(--primary)' }}>memory</span>
              Activated Agents ({report.workers_activated?.length || 0})
            </h4>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
              {report.workers_activated?.map((w) => (
                <span
                  key={w}
                  style={{
                    padding: '4px 12px',
                    borderRadius: '999px',
                    backgroundColor: 'var(--primary-fixed)',
                    color: 'var(--on-primary-fixed-variant)',
                    fontSize: '11px',
                    fontWeight: 700,
                  }}
                >
                  {w} worker
                </span>
              ))}
            </div>
          </div>

          {/* Worker Findings */}
          <div>
            <h4 style={{ fontSize: '13px', fontWeight: 800, color: 'var(--on-surface)', marginBottom: '10px' }}>
              🔍 Agent Findings & Evidence
            </h4>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
              {report.worker_findings?.map((finding, idx) => {
                const isHigh = (finding.score || 0) > 50;
                return (
                  <div
                    key={idx}
                    style={{
                      padding: '14px',
                      borderRadius: '14px',
                      border: isHigh ? '1px solid rgba(186, 26, 26, 0.4)' : '1px solid var(--surface-container)',
                      backgroundColor: isHigh ? 'rgba(186, 26, 26, 0.04)' : 'var(--surface-container-low)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '8px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '4px' }}>
                      <span style={{ fontSize: '11px', fontWeight: 800, color: 'var(--on-surface)' }}>
                        {finding.worker.toUpperCase()} WORKER
                      </span>
                      <span style={{ fontSize: '10px', fontWeight: 800, color: isHigh ? '#ba1a1a' : '#047857' }}>
                        Score: {finding.score}/100
                      </span>
                    </div>
                    <span style={{ fontSize: '10px', color: 'var(--secondary)' }}>
                      Conf: {Math.round((finding.confidence || 0) * 100)}%
                    </span>
                    {finding.error ? (
                      <p style={{ fontSize: '11px', color: '#ba1a1a', margin: 0 }}>Error: {finding.error}</p>
                    ) : (
                      <ul style={{ margin: 0, paddingLeft: '16px', fontSize: '12px', color: 'var(--on-surface-variant)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        {finding.evidence?.map((ev, i) => (
                          <li key={i}>{ev}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div style={{ padding: '16px 24px', borderTop: '1px solid var(--surface-container)', display: 'flex', justifyContent: 'flex-end' }}>
          <button
            onClick={onClose}
            className="btn-primary"
            style={{ padding: '12px 24px', justifyContent: 'center', backgroundColor: 'var(--primary-container)', color: '#ffffff', borderRadius: '14px', border: 'none', fontWeight: 700, fontSize: '13px', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '8px' }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>close</span>
            Close Report
          </button>
        </div>
      </div>
    </div>
  );
};
