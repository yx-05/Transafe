import React, { useState, useEffect } from 'react';
import type { BackendConfig } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { FileText, Lock, Unlock, RefreshCw } from 'lucide-react';

interface CaseDetailCardProps {
  config: BackendConfig;
  caseId: string | null;
  onClear: () => void;
}

export const CaseDetailCard: React.FC<CaseDetailCardProps> = ({ config, caseId, onClear }) => {
  const [detail, setDetail] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const fetchDetail = async () => {
    if (!caseId) return;
    setLoading(true);
    const client = new TranSafeApiClient(config);
    try {
      const res = await client.getCaseDetail(caseId);
      setDetail(res);
    } catch (err: any) {
      console.error('Fetch case detail error', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!caseId) {
      setDetail(null);
      return;
    }
    fetchDetail();
  }, [config.baseUrl, config.adminKey, caseId]);

  const handleAction = async (action: 'freeze' | 'unfreeze') => {
    if (!caseId) return;
    const reason = action === 'freeze'
      ? window.prompt('Freeze reason:', 'Suspected fraud - admin freeze')
      : window.prompt('Unfreeze reason:', 'Cleared by admin');
    if (reason === null) return;

    setBusy(true);
    const client = new TranSafeApiClient(config);
    try {
      if (action === 'freeze') {
        await client.freezeCase(caseId, reason);
      } else {
        await client.unfreezeCase(caseId, reason);
      }
      await fetchDetail();
    } catch (err: any) {
      alert(`${action === 'freeze' ? 'Freeze' : 'Unfreeze'} failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  };

  if (!caseId) {
    return (
      <div className="card test-card admin-card">
        <div className="card-header">
          <div className="card-title">
            <FileText className="card-icon" size={20} />
            <h3>Case Detail Inspector</h3>
          </div>
        </div>
        <p className="placeholder-text">Click "Inspect XAI" on any case in the list above to view full details.</p>
      </div>
    );
  }

  const xai = detail?.xai_report && typeof detail.xai_report === 'object' ? detail.xai_report : null;
  const verdictSummary = xai?.verdict_summary as string | undefined;

  return (
    <div className="card test-card admin-card">
      <div className="card-header">
        <div className="card-title">
          <FileText className="card-icon" size={20} />
          <h3>Case Detail Inspector: <code>{caseId}</code></h3>
        </div>
        <div className="header-actions">
          <button className="btn-icon-text" onClick={fetchDetail} disabled={loading}>
            <RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh
          </button>
          <button className="btn-secondary" onClick={onClear}>Close Detail</button>
        </div>
      </div>

      {loading ? (
        <p>Loading case breakdown...</p>
      ) : detail ? (
        <div className="case-detail-content">
          <div className="detail-grid">
            <div className="detail-item"><strong>User ID:</strong> <code>{detail.user_id}</code></div>
            <div className="detail-item"><strong>Trigger:</strong> {detail.trigger_type}</div>
            <div className="detail-item"><strong>Risk Score:</strong> {detail.risk_score}/100</div>
            <div className="detail-item"><strong>Risk Tier:</strong> <span className={`tier-badge ${detail.risk_tier?.toLowerCase()}`}>{detail.risk_tier}</span></div>
            <div className="detail-item"><strong>Status:</strong> <span className={`status-pill ${detail.status}`}>{detail.status}</span></div>
            <div className="detail-item"><strong>Action Taken:</strong> {detail.action_taken}</div>
            <div className="detail-item"><strong>Created:</strong> {new Date(detail.created_at || '').toLocaleString()}</div>
            {detail.user_label && <div className="detail-item"><strong>User Label:</strong> {detail.user_label}</div>}
            {detail.transaction_id && <div className="detail-item"><strong>Transaction ID:</strong> <code>{detail.transaction_id}</code></div>}
            {detail.caller_number && <div className="detail-item"><strong>Caller:</strong> {detail.caller_number}</div>}
            {detail.phishing_source && <div className="detail-item"><strong>Phishing Source:</strong> {detail.phishing_source}</div>}
          </div>

          <div className="xai-summary-card">
            <h4>Explainable AI (XAI) Report Data</h4>
            {verdictSummary && (
              <p className="xai-verdict"><strong>Verdict:</strong> {verdictSummary}</p>
            )}
            <pre className="json-block">{JSON.stringify(detail.xai_report ?? 'No XAI report stored for this case.', null, 2)}</pre>
          </div>

          <div className="button-group-row detail-actions">
            <button
              type="button"
              className="btn-danger-submit"
              onClick={() => handleAction('freeze')}
              disabled={busy || detail.status === 'frozen'}
            >
              <Lock size={16} /> Freeze Case
            </button>
            <button
              type="button"
              className="btn-success"
              onClick={() => handleAction('unfreeze')}
              disabled={busy || detail.status !== 'frozen'}
            >
              <Unlock size={16} /> Unfreeze Case
            </button>
          </div>
        </div>
      ) : (
        <p>Could not load details for case {caseId}.</p>
      )}
    </div>
  );
};
