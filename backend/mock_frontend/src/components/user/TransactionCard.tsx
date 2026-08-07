import React, { useState, useEffect } from 'react';
import type { BackendConfig, RecentCaseItem, XaiReport } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { SessionWebSocketClient } from '../../services/websocket';
import { PassiveTelemetryTracker } from '../../services/telemetryTracker';
import { Send, Clock, FileSpreadsheet, Database, User, RefreshCw, Link2 } from 'lucide-react';

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
  const [senderAccount, setSenderAccount] = useState('6373-5093-3430-8430');
  const [recipientAccount, setRecipientAccount] = useState('1122-3344-5566-7788');
  const [beneficiaryName, setBeneficiaryName] = useState('JJ Poor to Rich (JJPTR)');
  const [bankName, setBankName] = useState('CIMB Bank');
  const [amount, setAmount] = useState('15000.00');
  const [description, setDescription] = useState('JJPTR Forex Investment Deposit');
  const [associatedCaseId, setAssociatedCaseId] = useState('');

  const [activeSessionId] = useState<string>(() => `sess-${Date.now()}`);
  const [tracker, setTracker] = useState<PassiveTelemetryTracker | null>(null);

  const [loading, setLoading] = useState(false);
  const [statusLog, setStatusLog] = useState<string[]>([]);
  const [currentResult, setCurrentResult] = useState<XaiReport | null>(null);
  const [coolingOffTimer, setCoolingOffTimer] = useState<number | null>(null);

  // Linkable evidence cases (CALL / PHISHING / REPORT — NOT transactions, those
  // are the result of this flow, not the source evidence).
  const [linkableCases, setLinkableCases] = useState<RecentCaseItem[]>([]);
  const [casesLoading, setCasesLoading] = useState(false);

  const loadLinkableCases = async () => {
    setCasesLoading(true);
    try {
      const client = new TranSafeApiClient(config);
      const data = await client.getRecentCases(userId);
      const cases = (data?.recent_cases ?? []).filter(
        (c) => c.trigger_type !== 'TRANSACTION' && c.case_id
      );
      setLinkableCases(cases);
    } catch (e) {
      console.error('Failed to load linkable cases', e);
      setLinkableCases([]);
    } finally {
      setCasesLoading(false);
    }
  };

  useEffect(() => {
    loadLinkableCases();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.baseUrl, config.apiKey, userId]);

  useEffect(() => {
    const telemetry = new PassiveTelemetryTracker(config, userId, activeSessionId);
    telemetry.start();
    setTracker(telemetry);
    return () => telemetry.stop();
  }, [config.baseUrl, config.apiKey, userId, activeSessionId]);

  // Auto-lookup Beneficiary Name when recipientAccount changes
  useEffect(() => {
    if (!recipientAccount.trim()) return;
    const fetchBeneficiary = async () => {
      try {
        const res = await fetch(`${config.baseUrl}/api/v1/recipient/lookup?account_number=${encodeURIComponent(recipientAccount)}`, {
          headers: { 'X-API-Key': config.apiKey },
        });
        const data = await res.json();
        if (data?.data?.beneficiary_name) {
          setBeneficiaryName(data.data.beneficiary_name);
          setBankName(data.data.bank_name || 'Malaysian Retail Bank');
        }
      } catch (e) {
        console.error('Beneficiary lookup error', e);
      }
    };
    fetchBeneficiary();
  }, [recipientAccount, config.baseUrl, config.apiKey]);

  const handleExecuteTransaction = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setStatusLog(['Initiating transaction request & fetching passive telemetry...']);
    setCurrentResult(null);

    const client = new TranSafeApiClient(config);
    const txId = `tx-${Math.random().toString(36).substring(2, 9)}`;

    try {
      // 1. Send REST POST request enriched with beneficiary_name, session_metrics, biometrics & network fingerprint
      const response = await client.triggerTransaction({
        user_id: userId,
        session_id: activeSessionId,
        transaction: {
          transaction_id: txId,
          sender_account: senderAccount,
          recipient_account: recipientAccount,
          recipient_name: beneficiaryName,
          amount: parseFloat(amount),
          currency: 'MYR',
          description,
          initiated_at: new Date().toISOString(),
        },
        session_metrics: tracker?.getSessionMetrics(),
        behavioral_biometrics: tracker?.getBehavioralBiometrics(),
        browser_network_fingerprint: tracker?.getBrowserNetworkFingerprint(),
        associated_case_id: associatedCaseId.trim() || undefined,
      });

      setStatusLog((prev) => [...prev, response.message]);

      // 2. Connect WebSocket to stream LangGraph progress and XAI report
      const wsClient = new SessionWebSocketClient();
      wsClient.connect(
        config.baseUrl,
        activeSessionId,
        config.apiKey,
        (msg) => {
          if (msg.message || msg.status) {
            setStatusLog((prev) => [...prev, msg.message || msg.status || '']);
          }
          if (msg.type === 'result' && msg.data) {
            setCurrentResult(msg.data);
            setLoading(false);
            wsClient.close();

            if (msg.data.risk_tier === 'MEDIUM') {
              onTriggerBiometrics(activeSessionId, txId);
            } else if (msg.data.risk_tier === 'HIGH') {
              setCoolingOffTimer(1800);
            }
          }
        },
        (err) => {
          const errMsg = typeof err === 'string' ? err : 'WebSocket connection error';
          setStatusLog((prev) => [...prev, `▸ Error: ${errMsg}`]);
          setLoading(false);
        },
        () => {}
      );
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
        <span>Seeded 10 Real-World Malaysian Scam Companies:</span>
        <div className="preset-buttons">
          <button
            type="button"
            className="btn-tiny btn-scam-preset"
            onClick={() => {
              setRecipientAccount('7653-1234-5678-9012');
              setAmount('12000.00');
              setDescription('Pak Man Telo Deposit');
              tracker?.trackPaste();
            }}
          >
            🚨 Pak Man Telo
          </button>

          <button
            type="button"
            className="btn-tiny btn-scam-preset"
            onClick={() => {
              setRecipientAccount('8888-0000-1111-2222');
              setAmount('25000.00');
              setDescription('M-Coin Investment Topup');
              tracker?.trackPaste();
            }}
          >
            🚨 MBI Group (M-Coin)
          </button>

          <button
            type="button"
            className="btn-tiny btn-scam-preset"
            onClick={() => {
              setRecipientAccount('9988-7766-5544-3322');
              setAmount('15000.00');
              setDescription('Gold Scheme Investment');
              tracker?.trackPaste();
            }}
          >
            🚨 Genneva Malaysia
          </button>

          <button
            type="button"
            className="btn-tiny btn-scam-preset"
            onClick={() => {
              setRecipientAccount('1122-3344-5566-7788');
              setAmount('8000.00');
              setDescription('JJPTR Forex Deposit');
              tracker?.trackPaste();
            }}
          >
            🚨 JJPTR
          </button>

          <button
            type="button"
            className="btn-tiny btn-scam-preset"
            onClick={() => {
              setRecipientAccount('3344-5566-7788-9900');
              setAmount('10000.00');
              setDescription('Richway Global Deposit');
              tracker?.trackPaste();
            }}
          >
            🚨 Richway Global
          </button>

          <button
            type="button"
            className="btn-tiny"
            onClick={() => {
              setRecipientAccount('1001-2002-3003-4004');
              setAmount('150.00');
              setDescription('Personal Transfer');
            }}
          >
            ✅ Normal Safe Transfer
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
              onKeyDown={() => tracker?.trackKeyDown()}
              onKeyUp={() => tracker?.trackKeyUp()}
              required
            />
          </div>
          <div className="form-group">
            <label>Recipient Account (Mule / Destination)</label>
            <input
              type="text"
              value={recipientAccount}
              onChange={(e) => setRecipientAccount(e.target.value)}
              onKeyDown={(e) => tracker?.trackKeyDown(e.key)}
              onKeyUp={() => tracker?.trackKeyUp()}
              onPaste={() => tracker?.trackPaste('recipientAccount')}
              placeholder="e.g. 7653-1234-5678-9012"
              required
            />
          </div>
        </div>

        {/* Live Beneficiary Account Name Lookup Card */}
        <div className="beneficiary-lookup-card">
          <User size={15} className="text-blue-400" />
          <div className="beneficiary-info-text">
            <span>Verified Beneficiary Name:</span>
            <strong>{beneficiaryName}</strong>
            <span className="bank-tag">({bankName})</span>
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
              onKeyDown={(e) => tracker?.trackKeyDown(e.key)}
              onKeyUp={() => tracker?.trackKeyUp()}
              required
            />
          </div>
          <div className="form-group">
            <label>Transfer Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onKeyDown={(e) => tracker?.trackKeyDown(e.key)}
              onKeyUp={() => tracker?.trackKeyUp()}
              placeholder="Purpose of transfer"
              required
            />
          </div>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label>
              Associated Scam Call / Case ID (Optional Relay)
            </label>
            <div className="case-relay-row">
              <select
                className="case-relay-select"
                value={associatedCaseId}
                onChange={(e) => setAssociatedCaseId(e.target.value)}
                disabled={casesLoading}
              >
                <option value="">— No linked case —</option>
                {linkableCases.map((c) => (
                  <option key={c.case_id} value={c.case_id}>
                    {c.trigger_type} · {c.case_id.slice(0, 12)}… · {c.risk_tier}
                    {c.user_label === 'fraud' ? ' · ⚑ confirmed fraud' : ''}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="btn-tiny case-relay-refresh"
                onClick={loadLinkableCases}
                disabled={casesLoading}
                title="Refresh linkable cases"
              >
                <RefreshCw size={13} />
                {casesLoading ? 'Loading…' : 'Refresh'}
              </button>
            </div>
            {associatedCaseId && (
              <div className="case-relay-hint">
                <Link2 size={12} />
                <span>
                  {linkableCases.find((c) => c.case_id === associatedCaseId)?.snippet ||
                    'Linked case selected — its transcripts & extracted accounts will be checked against this transfer.'}
                </span>
              </div>
            )}
            {linkableCases.length === 0 && !casesLoading && (
              <div className="case-relay-hint muted">
                No call/phishing cases yet — run a scam call or analyze phishing material first, then link it here.
              </div>
            )}
          </div>
        </div>

        <button type="submit" className="btn-primary" disabled={loading}>
          {loading ? 'Analyzing Risk via Multi-Agent Graph...' : 'Simulate Fund Transfer'}
        </button>
      </form>

      {/* Real-time Status Progress Output */}
      {statusLog.length > 0 && (
        <div className="status-log-container">
          <h4>Live Agent Status Stream</h4>
          <div className="status-log-list">
            {statusLog.map((log, index) => (
              <div key={index} className="status-log-item">
                <Clock size={14} />
                <span>{log}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Cooling-Off Period Banner */}
      {coolingOffTimer !== null && (
        <div className="cooling-off-banner">
          <Clock className="text-red-400 animate-spin" size={24} />
          <div>
            <h4>High-Risk Transaction Frozen (30-Min Cooling Off)</h4>
            <p>
              TranSafe Multi-Agent network blocked execution due to confirmed scam activity.
              Account unfreezes in {Math.floor(coolingOffTimer / 60)}m {coolingOffTimer % 60}s.
            </p>
          </div>
        </div>
      )}

      {/* XAI Result Brief */}
      {currentResult && (
        <div className={`xai-brief-banner risk-${currentResult.risk_tier.toLowerCase()}`}>
          <div className="xai-brief-header">
            <div>
              <span className="risk-badge">{currentResult.risk_tier} RISK</span>
              <strong>Score: {currentResult.risk_score} / 100</strong>
            </div>
            <button
              className="btn-secondary btn-sm"
              onClick={() => onOpenXaiReport(currentResult)}
            >
              <FileSpreadsheet size={16} /> View Full XAI Report
            </button>
          </div>
          <p>{currentResult.recommendation}</p>
        </div>
      )}
    </div>
  );
};
