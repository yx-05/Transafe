import React, { useState, useEffect } from 'react';
import type { AccountActionData, AdminAccountItem, BackendConfig } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { Lock, Unlock, ShieldAlert, CheckCircle2, RefreshCw } from 'lucide-react';

interface AccountControlCardProps {
  config: BackendConfig;
}

export const AccountControlCard: React.FC<AccountControlCardProps> = ({ config }) => {
  const [accounts, setAccounts] = useState<AdminAccountItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyAccount, setBusyAccount] = useState<string | null>(null);
  const [actionResult, setActionResult] = useState<AccountActionData | null>(null);

  const fetchAccounts = async () => {
    setLoading(true);
    const client = new TranSafeApiClient(config);
    try {
      const res = await client.listAdminAccounts();
      setAccounts(res.items || []);
    } catch (err: any) {
      console.error('Fetch accounts failed', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAccounts();
  }, [config.baseUrl, config.adminKey]);

  const handleAction = async (accountNumber: string, action: 'freeze' | 'unfreeze') => {
    const reason = action === 'freeze'
      ? window.prompt('Freeze reason:', 'Suspected involvement in active scam activity')
      : window.prompt('Unfreeze reason:', 'Investigation cleared by admin');
    if (reason === null) return;

    setBusyAccount(accountNumber);
    setActionResult(null);
    const client = new TranSafeApiClient(config);
    try {
      const res = action === 'freeze'
        ? await client.freezeAccount(accountNumber, reason)
        : await client.unfreezeAccount(accountNumber, reason);
      setActionResult(res);
      await fetchAccounts();
    } catch (err: any) {
      alert(`${action === 'freeze' ? 'Freeze' : 'Unfreeze'} failed: ${err.message}`);
    } finally {
      setBusyAccount(null);
    }
  };

  return (
    <div className="card test-card admin-card">
      <div className="card-header">
        <div className="card-title">
          <Lock className="card-icon" size={20} />
          <h3>Account Freeze & Unfreeze Controls</h3>
        </div>
        <button className="btn-icon-text" onClick={fetchAccounts} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh
        </button>
      </div>

      {actionResult && (
        <div className={`result-box tier-${actionResult.status === 'frozen' ? 'high' : 'low'}`}>
          <div className="result-header">
            <h4>
              {actionResult.status === 'frozen' ? <ShieldAlert size={18} /> : <CheckCircle2 size={18} />}
              Account {actionResult.account_number} is now {actionResult.status.toUpperCase()}!
            </h4>
          </div>
          <div className="xai-meta">
            <span><strong>Reason:</strong> {actionResult.reason}</span>
            <span><strong>Updated By:</strong> {actionResult.frozen_by || actionResult.unfrozen_by || 'Admin'}</span>
            <span><strong>Timestamp:</strong> {new Date(actionResult.frozen_at || actionResult.unfrozen_at || '').toLocaleString()}</span>
          </div>
        </div>
      )}

      {loading && accounts.length === 0 ? (
        <p>Loading real accounts from database...</p>
      ) : accounts.length === 0 ? (
        <p className="placeholder-text">No accounts found in database.</p>
      ) : (
        <div className="table-responsive">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Account Number</th>
                <th>Type</th>
                <th>Balance (RM)</th>
                <th>Status</th>
                <th>Frozen By</th>
                <th>Frozen At</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((acc, idx) => (
                <tr key={`${acc.account_number}-${idx}`}>
                  <td><code>{acc.account_number}</code></td>
                  <td>{acc.account_type || 'savings'}</td>
                  <td>{Number(acc.balance_myr ?? 0).toLocaleString()}</td>
                  <td><span className={`status-pill ${acc.status}`}>{acc.status}</span></td>
                  <td>{acc.frozen_by || '—'}</td>
                  <td>{acc.frozen_at ? new Date(acc.frozen_at).toLocaleString() : '—'}</td>
                  <td>
                    <div className="action-cell">
                      {acc.status === 'frozen' ? (
                        <button
                          className="btn-tiny btn-tiny-success"
                          onClick={() => handleAction(acc.account_number, 'unfreeze')}
                          disabled={busyAccount === acc.account_number}
                        >
                          <Unlock size={12} /> Unfreeze
                        </button>
                      ) : (
                        <button
                          className="btn-tiny btn-tiny-danger"
                          onClick={() => handleAction(acc.account_number, 'freeze')}
                          disabled={busyAccount === acc.account_number}
                        >
                          <Lock size={12} /> Freeze
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
