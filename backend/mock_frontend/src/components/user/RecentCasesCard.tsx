import React, { useState, useEffect } from 'react';
import type { BackendConfig, RecentCaseItem } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { History, RefreshCw, Clock } from 'lucide-react';

interface RecentCasesCardProps {
  config: BackendConfig;
  userId: string;
}

export const RecentCasesCard: React.FC<RecentCasesCardProps> = ({ config, userId }) => {
  const [cases, setCases] = useState<RecentCaseItem[]>([]);
  const [loading, setLoading] = useState(false);

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

  useEffect(() => {
    fetchCases();
  }, [config.baseUrl, userId]);

  return (
    <div className="card test-card">
      <div className="card-header">
        <div className="card-title">
          <History className="card-icon" size={20} />
          <h3>User Active Cases & History</h3>
        </div>
        <button className="btn-icon-text" onClick={fetchCases} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh
        </button>
      </div>

      <div className="cases-list">
        {cases.length === 0 ? (
          <p className="placeholder-text">No active user cases found in session memory.</p>
        ) : (
          cases.map((c, idx) => (
            <div key={`${c.case_id}-${idx}`} className="case-item-row">
              <div className="case-main">
                <strong>{c.case_id}</strong>
                <span className="case-type">{c.trigger_type}</span>
                {c.caller_number && <span className="case-caller">📞 {c.caller_number}</span>}
              </div>
              <div className="case-side">
                <span className={`tier-badge ${c.risk_tier.toLowerCase()}`}>{c.risk_tier}</span>
                <span className="case-time"><Clock size={12} /> {new Date(c.created_at).toLocaleTimeString()}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
