import React from 'react';
import type { XaiReport } from '../types/api';
import { AlertTriangle, CheckCircle, ShieldAlert, Cpu, FileText } from 'lucide-react';

interface XaiReportModalProps {
  report: XaiReport | null;
  onClose: () => void;
}

export const XaiReportModal: React.FC<XaiReportModalProps> = ({ report, onClose }) => {
  if (!report) return null;

  const getTierBadge = (tier: string) => {
    switch (tier) {
      case 'HIGH':
        return <span className="tier-badge high"><ShieldAlert size={14} /> HIGH RISK ({report.risk_score}/100)</span>;
      case 'MEDIUM':
        return <span className="tier-badge medium"><AlertTriangle size={14} /> MEDIUM RISK ({report.risk_score}/100)</span>;
      case 'LOW':
      default:
        return <span className="tier-badge low"><CheckCircle size={14} /> LOW RISK ({report.risk_score}/100)</span>;
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content large" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="title-with-badge">
            <h2>Explainable AI (XAI) Report</h2>
            {getTierBadge(report.risk_tier)}
          </div>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>

        <div className="modal-body xai-body">
          <div className="xai-summary-card">
            <h3><FileText size={18} /> Verdict Summary</h3>
            <p className="summary-en"><strong>EN:</strong> {report.verdict_summary}</p>
            {report.verdict_summary_ms && (
              <p className="summary-ms"><strong>MS:</strong> {report.verdict_summary_ms}</p>
            )}
            <div className="xai-meta">
              <span><strong>Action Taken:</strong> {report.action_taken}</span>
              {report.unfreeze_at && <span><strong>Cooling Off Until:</strong> {new Date(report.unfreeze_at).toLocaleTimeString()}</span>}
              {report.case_id && <span><strong>Case ID:</strong> {report.case_id}</span>}
            </div>
          </div>

          {report.recommendation && (
            <div className="xai-recommendation">
              <h4>💡 Recommendation</h4>
              <p>{report.recommendation}</p>
            </div>
          )}

          <div className="activated-workers">
            <h4><Cpu size={16} /> Activated Agents ({report.workers_activated?.length || 0})</h4>
            <div className="worker-tags">
              {report.workers_activated?.map((w) => (
                <span key={w} className="worker-tag">{w} worker</span>
              ))}
            </div>
          </div>

          <div className="worker-findings-section">
            <h4>🔍 Agent Findings & Evidence</h4>
            <div className="findings-grid">
              {report.worker_findings?.map((finding, idx) => (
                <div key={idx} className={`finding-card ${finding.score > 50 ? 'high-risk' : 'normal'}`}>
                  <div className="finding-header">
                    <span className="worker-name">{finding.worker.toUpperCase()} WORKER</span>
                    <span className="finding-score">Score: {finding.score}/100</span>
                    <span className="finding-conf">Conf: {Math.round((finding.confidence || 0) * 100)}%</span>
                  </div>
                  {finding.error ? (
                    <p className="finding-error">Error: {finding.error}</p>
                  ) : (
                    <ul className="evidence-list">
                      {finding.evidence?.map((ev, i) => (
                        <li key={i}>{ev}</li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn-primary" onClick={onClose}>Close Report</button>
        </div>
      </div>
    </div>
  );
};
