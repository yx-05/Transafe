import React, { useState, useEffect } from 'react';
import type { AdminCaseItem, BackendConfig } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { ShieldAlert, Filter, RefreshCw, Eye, Lock, Unlock } from 'lucide-react';

interface CaseListCardProps {
  config: BackendConfig;
  onSelectCase: (caseId: string) => void;
}

export const CaseListCard: React.FC<CaseListCardProps> = ({ config, onSelectCase }) => {
  const [cases, setCases] = useState<AdminCaseItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [riskTier, setRiskTier] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [triggerFilter, setTriggerFilter] = useState('all');
  const [loading, setLoading] = useState(false);
  const [busyCase, setBusyCase] = useState<string | null>(null);

  const fetchCases = async () => {
    setLoading(true);
    const client = new TranSafeApiClient(config);
    try {
      const res = await client.listAdminCases(page, 10, riskTier, statusFilter, triggerFilter);
      setCases(res.items || []);
      setTotal(res.total || 0);
    } catch (err: any) {
      console.error('Fetch admin cases failed', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCases();
  }, [config.baseUrl, config.adminKey, page, riskTier, statusFilter, triggerFilter]);

  const handleCaseAction = async (caseId: string, action: 'freeze' | 'unfreeze') => {
    const reason = action === 'freeze'
      ? window.prompt('Freeze reason:', 'Suspected fraud - admin freeze')
      : window.prompt('Unfreeze reason:', 'Cleared by admin');
    if (reason === null) return;

    setBusyCase(caseId);
    const client = new TranSafeApiClient(config);
    try {
      if (action === 'freeze') {
        await client.freezeCase(caseId, reason);
      } else {
        await client.unfreezeCase(caseId, reason);
      }
      await fetchCases();
    } catch (err: any) {
      alert(`${action === 'freeze' ? 'Freeze' : 'Unfreeze'} failed: ${err.message}`);
    } finally {
      setBusyCase(null);
    }
  };

  return (
    <div className="card test-card admin-card">
      <div className="card-header">
        <div className="card-title">
          <ShieldAlert className="card-icon" size={20} />
          <h3>Fraud Case Management</h3>
        </div>
        <button className="btn-icon-text" onClick={fetchCases} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh
        </button>
      </div>

      <div className="filter-bar">
        <div className="filter-item">
          <label><Filter size={14} /> Risk Tier</label>
          <select value={riskTier} onChange={(e) => setRiskTier(e.target.value)}>
            <option value="all">All Tiers</option>
            <option value="HIGH">HIGH Risk</option>
            <option value="MEDIUM">MEDIUM Risk</option>
            <option value="LOW">LOW Risk</option>
          </select>
        </div>

        <div className="filter-item">
          <label><Filter size={14} /> Case Status</label>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="all">All Statuses</option>
            <option value="frozen">Frozen</option>
            <option value="reported">Reported</option>
            <option value="approved">Approved</option>
            <option value="pending">Pending</option>
          </select>
        </div>

        <div className="filter-item">
          <label><Filter size={14} /> Trigger Type</label>
          <select value={triggerFilter} onChange={(e) => setTriggerFilter(e.target.value)}>
            <option value="all">All Triggers</option>
            <option value="TRANSACTION">Transaction</option>
            <option value="CALL">Call</option>
            <option value="PHISHING">Phishing</option>
            <option value="TELEMETRY">Telemetry</option>
          </select>
        </div>
      </div>

      <div className="table-responsive">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Case ID</th>
              <th>Trigger Type</th>
              <th>Risk Score</th>
              <th>Tier</th>
              <th>Status</th>
              <th>Verdict Summary</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {cases.length === 0 ? (
              <tr>
                <td colSpan={7} className="text-center">No fraud cases matching filters.</td>
              </tr>
            ) : (
              cases.map((item, idx) => (
                <tr key={`${item.case_id}-${idx}`}>
                  <td><code>{item.case_id}</code></td>
                  <td><span className="type-badge">{item.trigger_type}</span></td>
                  <td><strong>{item.risk_score}/100</strong></td>
                  <td><span className={`tier-badge ${item.risk_tier.toLowerCase()}`}>{item.risk_tier}</span></td>
                  <td><span className={`status-pill ${item.status}`}>{item.status}</span></td>
                  <td className="summary-cell">{item.verdict_summary || 'No verdict summary.'}</td>
                  <td>
                    <div className="action-cell">
                      <button className="btn-tiny" onClick={() => onSelectCase(item.case_id)}>
                        <Eye size={12} /> Inspect XAI
                      </button>
                      {item.status === 'frozen' ? (
                        <button
                          className="btn-tiny btn-tiny-success"
                          onClick={() => handleCaseAction(item.case_id, 'unfreeze')}
                          disabled={busyCase === item.case_id}
                        >
                          <Unlock size={12} /> Unfreeze
                        </button>
                      ) : (
                        <button
                          className="btn-tiny btn-tiny-danger"
                          onClick={() => handleCaseAction(item.case_id, 'freeze')}
                          disabled={busyCase === item.case_id}
                        >
                          <Lock size={12} /> Freeze
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="pagination-bar">
        <span>Total: {total} cases</span>
        <div className="page-buttons">
          <button disabled={page === 1} onClick={() => setPage(page - 1)}>Prev</button>
          <span>Page {page}</span>
          <button disabled={cases.length < 10} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      </div>
    </div>
  );
};
