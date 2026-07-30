import React, { useState } from 'react';
import type { BackendConfig, ReportTriggerData } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { Database, Plus, Trash2, CheckCircle2 } from 'lucide-react';

interface FraudReportCardProps {
  config: BackendConfig;
  userId: string;
}

export const FraudReportCard: React.FC<FraudReportCardProps> = ({ config, userId }) => {
  const [phones, setPhones] = useState<string[]>(['+60161234567']);
  const [accounts, setAccounts] = useState<string[]>(['7653123456789012']);
  const [description, setDescription] = useState(
    'Received a call claiming to be from Bank Negara Malaysia. Caller instructed me to transfer funds to a secure account due to illegal activity.'
  );

  const [loading, setLoading] = useState(false);
  const [reportResult, setReportResult] = useState<ReportTriggerData | null>(null);

  const addPhone = () => setPhones([...phones, '']);
  const updatePhone = (index: number, val: string) => {
    const copy = [...phones];
    copy[index] = val;
    setPhones(copy);
  };
  const removePhone = (index: number) => setPhones(phones.filter((_, i) => i !== index));

  const addAccount = () => setAccounts([...accounts, '']);
  const updateAccount = (index: number, val: string) => {
    const copy = [...accounts];
    copy[index] = val;
    setAccounts(copy);
  };
  const removeAccount = (index: number) => setAccounts(accounts.filter((_, i) => i !== index));

  const handleSubmitReport = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setReportResult(null);

    const client = new TranSafeApiClient(config);

    try {
      const res = await client.triggerReport({
        user_id: userId,
        report: {
          phone_numbers: phones.filter((p) => p.trim() !== ''),
          bank_accounts: accounts.filter((a) => a.trim() !== ''),
          description,
        },
      });
      setReportResult(res);
    } catch (err: any) {
      alert(`Report failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card test-card">
      <div className="card-header">
        <div className="card-title">
          <Database className="card-icon" size={20} />
          <h3>Submit Fraud Report (Adaptive Memory Update)</h3>
        </div>
        <span className="card-tag">FR-M03</span>
      </div>

      <form onSubmit={handleSubmitReport} className="card-form">
        <div className="form-group">
          <label>Scammer Phone Numbers</label>
          {phones.map((phone, idx) => (
            <div key={idx} className="input-with-action">
              <input
                type="text"
                value={phone}
                onChange={(e) => updatePhone(idx, e.target.value)}
                placeholder="+6016XXXXXXX"
              />
              {phones.length > 1 && (
                <button type="button" className="btn-icon" onClick={() => removePhone(idx)}>
                  <Trash2 size={16} />
                </button>
              )}
            </div>
          ))}
          <button type="button" className="btn-link" onClick={addPhone}>
            <Plus size={14} /> Add Phone Number
          </button>
        </div>

        <div className="form-group">
          <label>Mule Bank Accounts</label>
          {accounts.map((acc, idx) => (
            <div key={idx} className="input-with-action">
              <input
                type="text"
                value={acc}
                onChange={(e) => updateAccount(idx, e.target.value)}
                placeholder="Account number"
              />
              {accounts.length > 1 && (
                <button type="button" className="btn-icon" onClick={() => removeAccount(idx)}>
                  <Trash2 size={16} />
                </button>
              )}
            </div>
          ))}
          <button type="button" className="btn-link" onClick={addAccount}>
            <Plus size={14} /> Add Bank Account
          </button>
        </div>

        <div className="form-group">
          <label>Incident Description (LLM will summarize & embed in pgvector)</label>
          <textarea
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
          />
        </div>

        <button type="submit" className="btn-primary" disabled={loading}>
          {loading ? 'Embedding & Saving to pgvector...' : 'Ingest Report to Fraud Memory'}
        </button>
      </form>

      {reportResult && (
        <div className="result-box tier-low">
          <div className="result-header">
            <h4><CheckCircle2 size={18} /> Ingested into Supabase pgvector Memory!</h4>
          </div>
          <p>{reportResult.message}</p>
          <div className="xai-meta">
            <span><strong>Case ID:</strong> {reportResult.case_id}</span>
            <span><strong>Phones:</strong> {reportResult.entities_recorded?.phone_numbers?.join(', ')}</span>
            <span><strong>Accounts:</strong> {reportResult.entities_recorded?.bank_accounts?.join(', ')}</span>
          </div>
        </div>
      )}
    </div>
  );
};
