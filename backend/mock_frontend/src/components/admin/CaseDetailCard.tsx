import React, { useState, useEffect } from 'react';
import type { BackendConfig } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { FileText } from 'lucide-react';

interface CaseDetailCardProps {
  config: BackendConfig;
  caseId: string | null;
  onClear: () => void;
}

export const CaseDetailCard: React.FC<CaseDetailCardProps> = ({ config, caseId, onClear }) => {
  const [detail, setDetail] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!caseId) {
      setDetail(null);
      return;
    }

    const fetchDetail = async () => {
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

    fetchDetail();
  }, [config.baseUrl, config.adminKey, caseId]);

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

  return (
    <div className="card test-card admin-card">
      <div className="card-header">
        <div className="card-title">
          <FileText className="card-icon" size={20} />
          <h3>Case Detail Inspector: <code>{caseId}</code></h3>
        </div>
        <button className="btn-secondary" onClick={onClear}>Close Detail</button>
      </div>

      {loading ? (
        <p>Loading case breakdown...</p>
      ) : detail ? (
        <div className="case-detail-content">
          <div className="detail-grid">
            <div className="detail-item"><strong>User ID:</strong> {detail.user_id}</div>
            <div className="detail-item"><strong>Trigger:</strong> {detail.trigger_type}</div>
            <div className="detail-item"><strong>Risk Score:</strong> {detail.risk_score}/100</div>
            <div className="detail-item"><strong>Risk Tier:</strong> <span className={`tier-badge ${detail.risk_tier?.toLowerCase()}`}>{detail.risk_tier}</span></div>
            <div className="detail-item"><strong>Status:</strong> {detail.status}</div>
            <div className="detail-item"><strong>Action Taken:</strong> {detail.action_taken}</div>
          </div>

          {detail.xai_report && (
            <div className="xai-summary-card">
              <h4>Explainable AI (XAI) Report Data</h4>
              <pre className="json-block">{JSON.stringify(detail.xai_report, null, 2)}</pre>
            </div>
          )}
        </div>
      ) : (
        <p>Could not load details for case {caseId}.</p>
      )}
    </div>
  );
};
