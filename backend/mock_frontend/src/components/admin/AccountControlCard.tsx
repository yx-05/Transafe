import React, { useState } from 'react';
import type { AccountActionData, BackendConfig } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { Lock, Unlock, ShieldAlert, CheckCircle2 } from 'lucide-react';

interface AccountControlCardProps {
  config: BackendConfig;
}

export const AccountControlCard: React.FC<AccountControlCardProps> = ({ config }) => {
  const [accountNumber, setAccountNumber] = useState('7653123456789012');
  const [reason, setReason] = useState('Suspected involvement in active Macau scam call');

  const [loading, setLoading] = useState(false);
  const [actionResult, setActionResult] = useState<AccountActionData | null>(null);

  const handleFreeze = async () => {
    setLoading(true);
    setActionResult(null);
    const client = new TranSafeApiClient(config);
    try {
      const res = await client.freezeAccount(accountNumber, reason);
      setActionResult(res);
    } catch (err: any) {
      alert(`Freeze failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleUnfreeze = async () => {
    setLoading(true);
    setActionResult(null);
    const client = new TranSafeApiClient(config);
    try {
      const res = await client.unfreezeAccount(accountNumber, reason);
      setActionResult(res);
    } catch (err: any) {
      alert(`Unfreeze failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card test-card admin-card">
      <div className="card-header">
        <div className="card-title">
          <Lock className="card-icon" size={20} />
          <h3>Account Freeze & Unfreeze Controls</h3>
        </div>
        <span className="card-tag">FR-A03 / FR-A04</span>
      </div>

      <div className="card-form">
        <div className="form-group">
          <label>Target Bank Account Number</label>
          <input
            type="text"
            value={accountNumber}
            onChange={(e) => setAccountNumber(e.target.value)}
            placeholder="Account number"
            required
          />
        </div>

        <div className="form-group">
          <label>Action Rationale / Reason</label>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Freeze/Unfreeze justification"
            required
          />
        </div>

        <div className="button-group-row">
          <button
            type="button"
            className="btn-danger-submit"
            onClick={handleFreeze}
            disabled={loading}
          >
            <Lock size={16} /> Freeze Account (Block Transfers)
          </button>

          <button
            type="button"
            className="btn-success"
            onClick={handleUnfreeze}
            disabled={loading}
          >
            <Unlock size={16} /> Unfreeze Account (Restore Active Status)
          </button>
        </div>
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
    </div>
  );
};
