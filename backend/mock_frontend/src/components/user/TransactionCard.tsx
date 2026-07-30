import React, { useState } from 'react';
import type { BackendConfig, XaiReport } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { SessionWebSocketClient } from '../../services/websocket';
import { Send, Clock, FileSpreadsheet, Database } from 'lucide-react';

interface TransactionCardProps {
  config: BackendConfig;
  userId: string;
  onOpenXaiReport: (report: XaiReport) => void;
  onTriggerBiometrics: (sessionId: string, txId: string) => void;
}

export const TransactionCard: React.FC<TransactionCardProps> = ({
  config,
  userId,
  onOpenXaiReport,
  onTriggerBiometrics,
}) => {
  const [senderAccount, setSenderAccount] = useState('12345678');
  const [recipientAccount, setRecipientAccount] = useState('7653-1234-5678-9012'); // Seeded Macau scammer mule account
  const [amount, setAmount] = useState('9800.00');
  const [description, setDescription] = useState('Investment deposit transfer');
  const [associatedCaseId, setAssociatedCaseId] = useState('');

  const [loading, setLoading] = useState(false);
  const [statusLog, setStatusLog] = useState<string[]>([]);
  const [currentResult, setCurrentResult] = useState<XaiReport | null>(null);
  const [coolingOffTimer, setCoolingOffTimer] = useState<number | null>(null);

  const handleExecuteTransaction = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setStatusLog(['Initiating transaction request...']);
    setCurrentResult(null);

    const client = new TranSafeApiClient(config);
    const sessionId = `sess-${Date.now()}`;
    const txId = `tx-${Math.random().toString(36).substring(2, 9)}`;

    try {
      const wsClient = new SessionWebSocketClient();
      wsClient.connect(
        config.baseUrl,
        sessionId,
        (msg) => {
          if (msg.message || msg.status) {
            setStatusLog((prev) => [...prev, msg.message || msg.status || '']);
          }
          if (msg.type === 'result' && msg.data) {
            setCurrentResult(msg.data);
            setLoading(false);
            wsClient.close();

            if (msg.data.risk_tier === 'MEDIUM') {
              onTriggerBiometrics(sessionId, txId);
            } else if (msg.data.risk_tier === 'HIGH') {
              setCoolingOffTimer(1800);
            }
          }
        },
        (_err) => {
          setStatusLog((prev) => [...prev, 'WebSocket connection error']);
          setLoading(false);
        },
        () => {}
      );

      const response = await client.triggerTransaction({
        user_id: userId,
        session_id: sessionId,
        transaction: {
          transaction_id: txId,
          sender_account: senderAccount,
          recipient_account: recipientAccount,
          amount: parseFloat(amount),
          currency: 'MYR',
          description,
          initiated_at: new Date().toISOString(),
        },
        associated_case_id: associatedCaseId.trim() || undefined,
      });

      setStatusLog((prev) => [...prev, response.message]);
    } catch (err: any) {
      setStatusLog((prev) => [...prev, `Error: ${err.message}`]);
      setLoading(false);
    }
  };

  return (
    <div className="card test-card">
      <div className="card-header">
        <div className="card-title">
          <Send className="card-icon" size={20} />
          <h3>Transaction Risk Interception</h3>
        </div>
        <span className="card-tag">FR-T02</span>
      </div>

      <div className="seeded-dataset-info">
        <Database size={14} />
        <span>Seeded Dataset Scenarios:</span>
        <div className="preset-buttons">
          <button
            type="button"
            className="btn-tiny"
            onClick={() => {
              setRecipientAccount('7653-1234-5678-9012');
              setAmount('12000.00');
              setDescription('Macau Scam Bail Transfer');
            }}
          >
            Seeded Macau Mule (7653-1234-5678-9012)
          </button>

          <button
            type="button"
            className="btn-tiny"
            onClick={() => {
              setRecipientAccount('8888-0000-1111-2222');
              setAmount('25000.00');
              setDescription('Crypto Investment Topup');
            }}
          >
            Seeded Investment Mule (8888-0000-1111-2222)
          </button>

          <button
            type="button"
            className="btn-tiny"
            onClick={() => {
              setRecipientAccount('9999-5555-4444-3333');
              setAmount('50.00');
              setDescription('Grocery Shop Payment');
            }}
          >
            Normal Transfer (Safe Account)
          </button>
        </div>
      </div>

      <form onSubmit={handleExecuteTransaction} className="card-form">
        <div className="form-row">
          <div className="form-group">
            <label>Sender Account (Customer)</label>
            <input
              type="text"
              value={senderAccount}
              onChange={(e) => setSenderAccount(e.target.value)}
              required
            />
          </div>
          <div className="form-group">
            <label>Recipient Account (Mule / Destination)</label>
            <input
              type="text"
              value={recipientAccount}
              onChange={(e) => setRecipientAccount(e.target.value)}
              placeholder="e.g. 7653-1234-5678-9012"
              required
            />
          </div>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label>Amount (MYR)</label>
            <input
              type="number"
              step="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              required
            />
          </div>
          <div className="form-group">
            <label>Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
        </div>

        <div className="form-group">
          <label>Optional Associated Case ID (Link with active call/phishing case)</label>
          <input
            type="text"
            value={associatedCaseId}
            onChange={(e) => setAssociatedCaseId(e.target.value)}
            placeholder="e.g. case-abc123"
          />
        </div>

        <button type="submit" className="btn-primary" disabled={loading}>
          {loading ? 'Evaluating Risk via LangGraph & Supabase RAG...' : 'Simulate Fund Transfer'}
        </button>
      </form>

      {statusLog.length > 0 && (
        <div className="status-log-box">
          <label>Live Agent Status Stream:</label>
          <div className="log-entries">
            {statusLog.map((log, index) => (
              <div key={index} className="log-line">▸ {log}</div>
            ))}
          </div>
        </div>
      )}

      {currentResult && (
        <div className={`result-box tier-${currentResult.risk_tier.toLowerCase()}`}>
          <div className="result-header">
            <h4>Outcome: {currentResult.risk_tier} RISK (Score: {currentResult.risk_score})</h4>
            <button className="btn-small" onClick={() => onOpenXaiReport(currentResult)}>
              <FileSpreadsheet size={14} /> View XAI Report
            </button>
          </div>
          <p>{currentResult.verdict_summary}</p>
          {coolingOffTimer && (
            <div className="cooling-off-alert">
              <Clock size={18} />
              <span>Cooling-off freeze active. Unfreezes in {Math.floor(coolingOffTimer / 60)} minutes.</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
