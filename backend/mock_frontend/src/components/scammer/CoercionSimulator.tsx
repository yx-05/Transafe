import React, { useState } from 'react';
import type { BackendConfig } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { SessionWebSocketClient } from '../../services/websocket';
import { Zap, ShieldAlert } from 'lucide-react';

interface CoercionSimulatorProps {
  config: BackendConfig;
  victimUserId: string;
}

export const CoercionSimulator: React.FC<CoercionSimulatorProps> = ({
  config,
  victimUserId,
}) => {
  const [coercionAmount, setCoercionAmount] = useState('15000.00');
  const [muleAccount, setMuleAccount] = useState('7653123456789012');
  const [scenario, setScenario] = useState('MACAU_POLICE_DIRECTIVE');

  const [loading, setLoading] = useState(false);
  const [resultLog, setResultLog] = useState<string[]>([]);

  const handleSimulateCoercion = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setResultLog(['Simulating active coercion transaction call...']);

    const client = new TranSafeApiClient(config);
    const sessionId = `sess-coercion-${Date.now()}`;
    const txId = `tx-coercion-${Date.now()}`;

    try {
      // Trigger transaction with anomalous telemetry & high amount
      await client.triggerTransaction({
        user_id: victimUserId,
        session_id: sessionId,
        transaction: {
          transaction_id: txId,
          sender_account: '12345678',
          recipient_account: muleAccount,
          amount: parseFloat(coercionAmount),
          currency: 'MYR',
          description: `Urgent bail transfer - ${scenario}`,
          initiated_at: new Date().toISOString(),
        },
      });

      const wsClient = new SessionWebSocketClient();
      wsClient.connect(
        config.baseUrl,
        sessionId,
        config.apiKey,
        (msg) => {
          if (msg.message || msg.status) {
            setResultLog((prev) => [...prev, msg.message || msg.status || '']);
          }
          if (msg.type === 'result' && msg.data) {
            setResultLog((prev) => [
              ...prev,
              `FINAL VERDICT: ${msg.data?.risk_tier} RISK (${msg.data?.risk_score}/100) — Action: ${msg.data?.action_taken}`,
            ]);
            setLoading(false);
            wsClient.close();
          }
        },
        (err) => {
          const errMsg = typeof err === 'string' ? err : 'WebSocket connection error';
          setResultLog((prev) => [...prev, `▸ Error: ${errMsg}`]);
          setLoading(false);
        },
        () => {}
      );
    } catch (err: any) {
      setResultLog((prev) => [...prev, `Error: ${err.message}`]);
      setLoading(false);
    }
  };

  return (
    <div className="card test-card scammer-card">
      <div className="card-header">
        <div className="card-title">
          <Zap className="card-icon text-red" size={20} />
          <h3>Coercion Transfer Simulator</h3>
        </div>
        <span className="card-tag red">SCAMMER ROLE</span>
      </div>

      <form onSubmit={handleSimulateCoercion} className="card-form">
        <div className="form-row">
          <div className="form-group">
            <label>Coerced Transfer Amount (MYR)</label>
            <input
              type="number"
              value={coercionAmount}
              onChange={(e) => setCoercionAmount(e.target.value)}
              required
            />
            <small>High amount relative to user's 90-day baseline</small>
          </div>

          <div className="form-group">
            <label>Target Mule Bank Account</label>
            <input
              type="text"
              value={muleAccount}
              onChange={(e) => setMuleAccount(e.target.value)}
              required
            />
          </div>
        </div>

        <div className="form-group">
          <label>Coercion Script Context</label>
          <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
            <option value="MACAU_POLICE_DIRECTIVE">Fake Police Inspector demanding immediate bail transfer</option>
            <option value="LHDN_TAX_THREAT">Fake Tax Officer threatening immediate arrest</option>
            <option value="INVESTMENT_LOCK_IN">Fake Broker pressuring top-up before profit forfeiture</option>
          </select>
        </div>

        <button type="submit" className="btn-danger-submit" disabled={loading}>
          <ShieldAlert size={16} /> Execute Coerced Transfer (Test High Risk Freeze)
        </button>
      </form>

      {resultLog.length > 0 && (
        <div className="status-log-box">
          <div className="log-entries">
            {resultLog.map((log, idx) => (
              <div key={idx} className="log-line">▸ {log}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
