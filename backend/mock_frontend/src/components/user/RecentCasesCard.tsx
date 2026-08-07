import React, { useState, useEffect } from 'react';
import type { BackendConfig, RecentCaseItem, UserLabel } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { History, RefreshCw, Clock, CheckCircle2, XCircle, RotateCcw } from 'lucide-react';

interface RecentCasesCardProps {
  config: BackendConfig;
  userId: string;
}

const labelCopy: Record<UserLabel, string> = {
  unlabeled: 'Unlabeled',
  fraud: 'Confirmed fraud',
  benign: 'Not fraud',
};

export const RecentCasesCard: React.FC<RecentCasesCardProps> = ({ config, userId }) => {
  const [cases, setCases] = useState<RecentCaseItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [labeling, setLabeling] = useState<string | null>(null);

  const fetchCases = async () => {
    setLoading(true);
    const client = new TranSafeApiClient(config);
    try {
      const data = await client.getRecentCases(userId);
      setCases(data.recent_cases || []);
    } catch (err: any) {
      console.error('Fetch cases failed', err);
    } finally {
      setLoading(false);
    }
  };

  const labelCase = async (caseId: string, label: UserLabel) => {
    setLabeling(caseId);
    const client = new TranSafeApiClient(config);
    try {
      await client.labelCase(caseId, label);
      // Optimistic update, then re-fetch to get fresh label state
      setCases((prev) =>
        prev.map((c) => (c.case_id === caseId ? { ...c, user_label: label } : c))
      );
      await fetchCases();
    } catch (err: any) {
      console.error('Label case failed', err);
    } finally {
      setLabeling(null);
    }
  };

  useEffect(() => {
    fetchCases();
  }, [config.baseUrl, userId]);

  return (
    <div className="card test-card">
      <div className="card-header">
        <div className="card-title">
          <History className="card-icon" size={20} />
          <h3>Case History & Fraud Labeling</h3>
        </div>
        <button className="btn-icon-text" onClick={fetchCases} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh
        </button>
      </div>

      <div className="cases-list">
        {cases.length === 0 ? (
          <p className="placeholder-text">
            No cases yet — run a call, phishing, or report trigger to build your history.
          </p>
        ) : (
          cases.map((c, idx) => (
            <div key={`${c.case_id}-${idx}`} className="case-item-row">
              <div className="case-main">
                <strong className="case-id-short">
                  {c.case_id.length > 12 ? `${c.case_id.slice(0, 12)}…` : c.case_id}
                </strong>
                <span className="case-type">{c.trigger_type}</span>
                {c.caller_number && <span className="case-caller">📞 {c.caller_number}</span>}
                {c.archetype && <span className="case-archetype">🧠 {c.archetype}</span>}
                {c.risk_score > 0 && <span className="case-score">Score {c.risk_score}</span>}
                {c.snippet && <span className="case-snippet">“{c.snippet}”</span>}
              </div>
              <div className="case-side">
                <span className={`tier-badge ${c.risk_tier.toLowerCase()}`}>{c.risk_tier}</span>
                <span
                  className={`label-badge ${c.user_label === 'fraud' ? 'label-fraud' : c.user_label === 'benign' ? 'label-benign' : 'label-unlabeled'}`}
                >
                  {labelCopy[c.user_label]}
                </span>
                <span className="case-time">
                  <Clock size={12} /> {new Date(c.created_at).toLocaleString()}
                </span>
                <div className="label-actions">
                  <button
                    className="btn-label btn-label-fraud"
                    disabled={labeling === c.case_id || c.user_label === 'fraud'}
                    onClick={() => labelCase(c.case_id, 'fraud')}
                    title="Mark this case as fraud — TranSafe will learn from it"
                  >
                    <CheckCircle2 size={14} /> Fraud
                  </button>
                  <button
                    className="btn-label btn-label-benign"
                    disabled={labeling === c.case_id || c.user_label === 'benign'}
                    onClick={() => labelCase(c.case_id, 'benign')}
                    title="Mark this case as not fraud"
                  >
                    <XCircle size={14} /> Not Fraud
                  </button>
                  <button
                    className="btn-label btn-label-reset"
                    disabled={labeling === c.case_id || c.user_label === 'unlabeled'}
                    onClick={() => labelCase(c.case_id, 'unlabeled')}
                    title="Reset label"
                  >
                    <RotateCcw size={14} />
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
