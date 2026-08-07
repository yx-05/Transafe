import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSimulation } from '../context/SimulationContext';
import { useApi } from '../context/ApiContext';
import { UserHeader } from '../components/UserHeader';
import { XaiReportModal } from '../components/XaiReportModal';
import { BiometricModal } from '../components/BiometricModal';
import { SessionWebSocketClient } from '../services/websocket';
import { PassiveTelemetryTracker } from '../services/telemetryTracker';
import { TranSafeApiClient } from '../services/api';
import type { RecentCaseItem, XaiReport } from '../types/api';

export const TransferPage: React.FC = () => {
  const { accountBalance } = useSimulation();
  const { config, client, userId } = useApi();

  const navigate = useNavigate();

  // Form State matching /backend/mock_frontend TransactionCard
  const [senderAccount, setSenderAccount] = useState<string>('6373-5093-3430-8430 (Maybank Premier)');
  const [bank, setBank] = useState<string>('CIMB Bank');
  const [recipientName, setRecipientName] = useState<string>('JJ Poor to Rich (JJPTR)');
  const [accountNumber, setAccountNumber] = useState<string>('1122-3344-5566-7788');
  const [amount, setAmount] = useState<string>('15000.00');
  const [description, setDescription] = useState<string>('JJPTR Forex Investment Deposit');
  const [associatedCaseId, setAssociatedCaseId] = useState<string>('');

  // Real backend session id for this transfer flow
  const [activeSessionId] = useState<string>(() => `sess-${Date.now()}`);
  const [tracker, setTracker] = useState<PassiveTelemetryTracker | null>(null);

  // Loading / streaming state
  const [loading, setLoading] = useState(false);
  const [statusLog, setStatusLog] = useState<string[]>([]);
  const [currentResult, setCurrentResult] = useState<XaiReport | null>(null);
  const [coolingOffTimer, setCoolingOffTimer] = useState<number | null>(null);

  // Linkable evidence cases (CALL / PHISHING / REPORT — NOT transactions)
  const [linkableCases, setLinkableCases] = useState<RecentCaseItem[]>([]);
  const [casesLoading, setCasesLoading] = useState(false);

  // Modals
  const [activeXaiReport, setActiveXaiReport] = useState<XaiReport | null>(null);
  const [biometricChallenge, setBiometricChallenge] = useState<{
    sessionId: string;
    txId: string;
  } | null>(null);

  const wsRef = useRef<SessionWebSocketClient | null>(null);

  const loadLinkableCases = async () => {
    setCasesLoading(true);
    try {
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

  // Passive telemetry tracker
  useEffect(() => {
    const telemetry = new PassiveTelemetryTracker(config, userId, activeSessionId);
    telemetry.start();
    setTracker(telemetry);
    return () => {
      telemetry.stop();
      wsRef.current?.close();
    };
  }, [config.baseUrl, config.apiKey, userId, activeSessionId]);

  // Auto-lookup Beneficiary Name when recipientAccount changes
  useEffect(() => {
    if (!accountNumber.trim()) return;
    const fetchBeneficiary = async () => {
      try {
        const res = await fetch(
          `${config.baseUrl}/api/v1/recipient/lookup?account_number=${encodeURIComponent(accountNumber)}`,
          { headers: { 'X-API-Key': config.apiKey } }
        );
        const data = await res.json();
        if (data?.data?.beneficiary_name) {
          setRecipientName(data.data.beneficiary_name);
          setBank(data.data.bank_name || 'Malaysian Retail Bank');
        }
      } catch (e) {
        console.error('Beneficiary lookup error', e);
      }
    };
    fetchBeneficiary();
  }, [accountNumber, config.baseUrl, config.apiKey]);

  // Cooling-off countdown
  useEffect(() => {
    if (coolingOffTimer === null) return;
    if (coolingOffTimer <= 0) {
      setCoolingOffTimer(null);
      return;
    }
    const t = setTimeout(() => setCoolingOffTimer((v) => (v === null ? null : v - 1)), 1000);
    return () => clearTimeout(t);
  }, [coolingOffTimer]);

  // Preset quick fill handler matching backend dataset presets
  const applyPreset = (preset: {
    account: string;
    name: string;
    bankName: string;
    amt: string;
    desc: string;
  }) => {
    setAccountNumber(preset.account);
    setRecipientName(preset.name);
    setBank(preset.bankName);
    setAmount(preset.amt);
    setDescription(preset.desc);
    tracker?.trackPaste('recipientAccount');
  };

  const handleBiometricSubmit = async (result: 'PASSED' | 'FAILED' | 'DECLINED') => {
    if (!biometricChallenge) return;
    try {
      await client.submitBiometricResult({
        user_id: userId,
        session_id: biometricChallenge.sessionId,
        transaction_id: biometricChallenge.txId,
        biometric_result: result,
        method: 'TOUCH_ID',
        attempted_at: new Date().toISOString(),
      });
    } catch (e: any) {
      console.error('Biometric submission error', e.message);
    }
    setBiometricChallenge(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const parsedAmount = parseFloat(amount) || 0;
    const senderClean = senderAccount.replace(/\s*\(.*\)$/, '').trim() || senderAccount;

    setLoading(true);
    setStatusLog(['Initiating transaction request & fetching passive telemetry...']);
    setCurrentResult(null);
    setCoolingOffTimer(null);

    const api = new TranSafeApiClient(config);
    const txId = `tx-${Math.random().toString(36).substring(2, 9)}`;

    try {
      // 1. Send REST POST request enriched with beneficiary_name, session_metrics, biometrics & network fingerprint
      const response = await api.triggerTransaction({
        user_id: userId,
        session_id: activeSessionId,
        transaction: {
          transaction_id: txId,
          sender_account: senderClean,
          recipient_account: accountNumber,
          recipient_name: recipientName,
          amount: parsedAmount,
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
      wsRef.current = wsClient;
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
              setBiometricChallenge({ sessionId: activeSessionId, txId });
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

  const handleDismiss = () => {
    setCurrentResult(null);
    navigate('/');
  };

  // Calculate stroke offset for circular dial (Score 0-100)
  const radius = 70;
  const circumference = 2 * Math.PI * radius;
  const score = currentResult?.risk_score || 0;
  const strokeDashoffset = circumference - (score / 100) * circumference;

  const scoreColor =
    score > 70 ? 'var(--risk-high)' : score > 30 ? 'var(--risk-med)' : 'var(--risk-low)';

  return (
    <div className="user-app-layout pb-28 min-h-screen relative bg-[#f8f9fa]">
      {/* Header Banner */}
      <div className="blue-header-bg blue-header-bg--short"></div>

      <div className="main-content-wrapper px-4 sm:px-6 md:px-8">
        <UserHeader title="Secure Transfer" showBack={true} />

        <div className="max-w-2xl mx-auto relative z-10 pt-2">
          {/* ======================================================
              PANEL A: TRANSFER FORM
             ====================================================== */}
          {!loading && !currentResult && (
            <div className="neo-card bg-white shadow-xl rounded-[32px] p-6 md:p-8 border border-gray-100">
              <div className="flex items-center justify-between border-b pb-4 mb-6">
                <div>
                  <h2 className="text-2xl font-bold text-gray-900">Funds Transfer</h2>
                  <p className="text-xs text-gray-500 mt-1">
                    Available Balance: <strong className="text-gray-900">RM {accountBalance.toLocaleString('en-US', { minimumFractionDigits: 2 })}</strong>
                  </p>
                </div>
                <span className="bg-blue-50 text-[#0050cb] px-3 py-1 rounded-full text-xs font-bold font-mono border border-blue-200">
                  FR-T02 ACTIVE
                </span>
              </div>

              {/* Seeded Scam Dataset Presets (10 Real-World Malaysian Scam Companies) */}
              <div className="mb-6 p-4 rounded-2xl bg-gray-50 border border-gray-200">
                <div className="flex items-center gap-2 text-xs font-bold text-gray-700 mb-3 uppercase tracking-wider">
                  <span className="material-symbols-outlined text-red-600 text-base">database</span>
                  <span>Real-World Malaysian Scam Dataset Presets:</span>
                </div>

                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => applyPreset({
                      account: '7653-1234-5678-9012',
                      name: 'Pak Man Telo Enterprise',
                      bankName: 'Maybank',
                      amt: '12000.00',
                      desc: 'Pak Man Telo Deposit'
                    })}
                    className="px-3 py-1.5 rounded-xl bg-red-50 text-red-700 border border-red-200 text-xs font-bold hover:bg-red-100 transition-colors flex items-center gap-1"
                  >
                    🚨 Pak Man Telo
                  </button>

                  <button
                    type="button"
                    onClick={() => applyPreset({
                      account: '8888-0000-1111-2222',
                      name: 'MBI International Sdn Bhd',
                      bankName: 'Public Bank',
                      amt: '25000.00',
                      desc: 'M-Coin Investment Topup'
                    })}
                    className="px-3 py-1.5 rounded-xl bg-red-50 text-red-700 border border-red-200 text-xs font-bold hover:bg-red-100 transition-colors flex items-center gap-1"
                  >
                    🚨 MBI Group (M-Coin)
                  </button>

                  <button
                    type="button"
                    onClick={() => applyPreset({
                      account: '9988-7766-5544-3322',
                      name: 'Genneva Gold Trading',
                      bankName: 'RHB Bank',
                      amt: '15000.00',
                      desc: 'Gold Scheme Investment'
                    })}
                    className="px-3 py-1.5 rounded-xl bg-red-50 text-red-700 border border-red-200 text-xs font-bold hover:bg-red-100 transition-colors flex items-center gap-1"
                  >
                    🚨 Genneva Malaysia
                  </button>

                  <button
                    type="button"
                    onClick={() => applyPreset({
                      account: '1122-3344-5566-7788',
                      name: 'JJ Poor to Rich (JJPTR)',
                      bankName: 'CIMB Bank',
                      amt: '8000.00',
                      desc: 'JJPTR Forex Deposit'
                    })}
                    className="px-3 py-1.5 rounded-xl bg-red-50 text-red-700 border border-red-200 text-xs font-bold hover:bg-red-100 transition-colors flex items-center gap-1"
                  >
                    🚨 JJPTR
                  </button>

                  <button
                    type="button"
                    onClick={() => applyPreset({
                      account: '3344-5566-7788-9900',
                      name: 'Richway Global Forex',
                      bankName: 'Hong Leong Bank',
                      amt: '10000.00',
                      desc: 'Richway Global Deposit'
                    })}
                    className="px-3 py-1.5 rounded-xl bg-red-50 text-red-700 border border-red-200 text-xs font-bold hover:bg-red-100 transition-colors flex items-center gap-1"
                  >
                    🚨 Richway Global
                  </button>

                  <button
                    type="button"
                    onClick={() => applyPreset({
                      account: '1001-2002-3003-4004',
                      name: 'Ali Bin Ahmad',
                      bankName: 'Maybank',
                      amt: '150.00',
                      desc: 'Personal Transfer'
                    })}
                    className="px-3 py-1.5 rounded-xl bg-emerald-50 text-emerald-700 border border-emerald-200 text-xs font-bold hover:bg-emerald-100 transition-colors flex items-center gap-1"
                  >
                    ✅ Normal Safe Transfer
                  </button>
                </div>
              </div>

              <form onSubmit={handleSubmit} className="flex flex-col gap-5">
                {/* Sender Account */}
                <div className="form-group mb-0">
                  <label className="form-label text-xs uppercase tracking-wider text-gray-500 font-bold mb-2">
                    Sender Account (Customer)
                  </label>
                  <input
                    type="text"
                    value={senderAccount}
                    onChange={(e) => setSenderAccount(e.target.value)}
                    className="form-input bg-gray-50 font-mono text-gray-700 text-xs font-semibold"
                    required
                  />
                </div>

                {/* Recipient Account Number */}
                <div className="form-group mb-0">
                  <label className="form-label text-xs uppercase tracking-wider text-gray-500 font-bold mb-2">
                    Recipient Account (Mule / Destination)
                  </label>
                  <input
                    type="text"
                    value={accountNumber}
                    onChange={(e) => setAccountNumber(e.target.value)}
                    onKeyDown={(e) => tracker?.trackKeyDown(e.key)}
                    onKeyUp={() => tracker?.trackKeyUp()}
                    onPaste={() => tracker?.trackPaste('recipientAccount')}
                    placeholder="e.g., 7653-1234-5678-9012"
                    className="form-input font-mono text-xs font-bold text-gray-900"
                    required
                  />
                </div>

                {/* Live Beneficiary Account Lookup Card */}
                <div className="p-3.5 rounded-2xl bg-blue-50/70 border border-blue-100 flex items-center gap-3 text-xs text-blue-900">
                  <span className="material-symbols-outlined text-[#0050cb] text-xl flex-shrink-0">verified_user</span>
                  <div className="flex-1 min-w-0">
                    <span className="text-gray-500 font-semibold mr-1">Verified Beneficiary Name:</span>
                    <strong className="text-gray-900 font-bold">{recipientName || 'Checking...'}</strong>
                    <span className="ml-2 text-[11px] font-bold text-[#0050cb] bg-blue-100 px-2 py-0.5 rounded-full">
                      ({bank})
                    </span>
                  </div>
                </div>

                {/* Beneficiary Bank */}
                <div className="form-group mb-0">
                  <label className="form-label text-xs uppercase tracking-wider text-gray-500 font-bold mb-2">
                    Beneficiary Bank
                  </label>
                  <select
                    value={bank}
                    onChange={(e) => setBank(e.target.value)}
                    className="form-select font-semibold text-xs"
                  >
                    <option value="Maybank">Maybank (Malayan Banking Berhad)</option>
                    <option value="CIMB Bank">CIMB Bank Berhad</option>
                    <option value="Public Bank">Public Bank Berhad</option>
                    <option value="RHB Bank">RHB Bank Berhad</option>
                    <option value="Hong Leong Bank">Hong Leong Bank Berhad</option>
                    <option value="Bank Islam">Bank Islam Malaysia Berhad</option>
                  </select>
                </div>

                {/* Recipient Name Input */}
                <div className="form-group mb-0">
                  <label className="form-label text-xs uppercase tracking-wider text-gray-500 font-bold mb-2">
                    Recipient Name
                  </label>
                  <input
                    type="text"
                    value={recipientName}
                    onChange={(e) => setRecipientName(e.target.value)}
                    placeholder="e.g., JJ Poor to Rich (JJPTR)"
                    className="form-input text-xs font-semibold"
                    required
                  />
                </div>

                {/* Amount */}
                <div className="form-group mb-0">
                  <label className="form-label text-xs uppercase tracking-wider text-gray-500 font-bold mb-2">
                    Amount (MYR)
                  </label>
                  <div className="relative flex items-center">
                    <span className="absolute left-4 text-gray-500 font-bold text-sm pointer-events-none z-10">RM</span>
                    <input
                      type="number"
                      step="0.01"
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                      placeholder="0.00"
                      className="form-input text-base font-extrabold text-gray-900"
                      style={{ paddingLeft: '52px' }}
                      required
                    />
                  </div>
                </div>

                {/* Description */}
                <div className="form-group mb-0">
                  <label className="form-label text-xs uppercase tracking-wider text-gray-500 font-bold mb-2">
                    Transfer Description / Purpose
                  </label>
                  <input
                    type="text"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="e.g., Forex Deposit / Personal Transfer"
                    className="form-input text-xs font-semibold"
                    required
                  />
                </div>

                {/* Context Linkage Selection */}
                <div className="form-group mb-0">
                  <label className="form-label text-xs uppercase tracking-wider text-gray-500 font-bold mb-2">
                    Associated Scam Call / Case ID (Optional Relay)
                  </label>

                  <div className="flex items-center gap-2">
                    <select
                      className="form-select text-xs font-mono flex-1"
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
                      onClick={loadLinkableCases}
                      disabled={casesLoading}
                      title="Refresh linkable cases"
                      className="px-3 py-2 rounded-xl bg-gray-100 border border-gray-200 text-xs font-bold text-gray-700 hover:bg-gray-200 transition-colors flex items-center gap-1"
                    >
                      <span className="material-symbols-outlined text-sm">refresh</span>
                      {casesLoading ? 'Loading…' : 'Refresh'}
                    </button>
                  </div>

                  {associatedCaseId && (
                    <p className="mt-2 text-[11px] text-gray-500 flex items-center gap-1">
                      <span className="material-symbols-outlined text-sm text-[#0050cb]">link</span>
                      {linkableCases.find((c) => c.case_id === associatedCaseId)?.snippet ||
                        'Linked case selected — its transcripts & extracted accounts will be checked against this transfer.'}
                    </p>
                  )}
                  {linkableCases.length === 0 && !casesLoading && (
                    <p className="mt-2 text-[11px] text-gray-400">
                      No call/phishing cases yet — run a scam call or analyze phishing material first, then link it here.
                    </p>
                  )}
                </div>

                {/* Submit Action Button */}
                <div className="mt-4">
                  <button
                    type="submit"
                    disabled={loading}
                    className="btn-primary w-full py-4 justify-center bg-[#0066ff] hover:bg-[#0050cb] text-white font-bold shadow-lg shadow-blue-500/20 text-sm"
                  >
                    <span className="material-symbols-outlined text-xl">shield_lock</span>
                    {loading ? 'Analyzing Risk via Multi-Agent Graph...' : 'Authorize & Scan Transfer'}
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* ======================================================
              PANEL B: LIVE AGENT STATUS STREAM (WebSocket)
             ====================================================== */}
          {(loading || statusLog.length > 0) && !currentResult && (
            <div className="neo-card bg-white shadow-2xl rounded-[32px] p-8 text-center border border-gray-100">
              <div className="w-20 h-20 mx-auto mb-6 relative flex items-center justify-center">
                <div className="w-20 h-20 border-4 border-blue-200 border-t-[#0066ff] rounded-full animate-spin"></div>
                <span className="material-symbols-outlined text-[#0066ff] text-3xl absolute">lock_reset</span>
              </div>

              <h2 className="text-2xl font-extrabold text-gray-900 mb-2">SecureTransfer Active Scan</h2>
              <p className="text-xs text-gray-500 mb-6">
                Executing multi-agent fraud inspection across BNM, NSRC & biometrics engines...
              </p>

              {/* Log Terminal Output */}
              <div className="scanner-terminal text-left mb-6 p-4 rounded-2xl bg-gray-950 text-gray-200 font-mono text-xs space-y-2">
                {statusLog.map((log, idx) => (
                  <div key={idx} className="flex items-start gap-2">
                    <span className="text-emerald-400 font-bold">&gt;</span>
                    <span>{log}</span>
                  </div>
                ))}
              </div>

              <p className="text-xs text-gray-400 animate-pulse font-mono">
                Please do not close this window. Intercepting fraud vectors in real-time...
              </p>
            </div>
          )}

          {/* ======================================================
              PANEL C: MULTI-AGENT SYSTEM VERDICT
             ====================================================== */}
          {currentResult && !loading && (
            <div className="neo-card bg-white shadow-2xl rounded-[32px] p-8 border border-gray-100">
              {/* Header Badge */}
              <div className="flex justify-between items-center border-b pb-4 mb-6 flex-wrap gap-3">
                <h2 className="text-2xl font-extrabold text-gray-900">Multi-Agent System Verdict</h2>
                <span
                  className="px-3.5 py-1 rounded-full text-xs font-bold uppercase tracking-wider"
                  style={{
                    backgroundColor: scoreColor,
                    color: '#ffffff'
                  }}
                >
                  {currentResult.risk_tier} RISK ({currentResult.risk_score}/100)
                </span>
              </div>

              {/* Circular Dial & Verdict Highlights */}
              <div className="grid grid-cols-1 md:grid-cols-12 gap-8 items-center mb-8">
                {/* Score Dial */}
                <div className="md:col-span-5 flex flex-col items-center justify-center">
                  <div className="relative w-44 h-44 flex items-center justify-center">
                    <svg className="w-full h-full transform -rotate-90">
                      <circle
                        cx="88"
                        cy="88"
                        r={radius}
                        stroke="#e5e7eb"
                        strokeWidth="12"
                        fill="transparent"
                      />
                      <circle
                        cx="88"
                        cy="88"
                        r={radius}
                        stroke={scoreColor}
                        strokeWidth="12"
                        fill="transparent"
                        strokeDasharray={circumference}
                        strokeDashoffset={strokeDashoffset}
                        strokeLinecap="round"
                        className="transition-all duration-1000 ease-out"
                      />
                    </svg>
                    <div className="absolute flex flex-col items-center">
                      <span className="text-4xl font-extrabold text-gray-900">{currentResult.risk_score}</span>
                      <span className="text-[10px] font-bold uppercase text-gray-400">Risk Score</span>
                    </div>
                  </div>
                </div>

                {/* English & Malay Verdict Summary */}
                <div className="md:col-span-7 flex flex-col gap-4">
                  <div className="p-4 rounded-2xl bg-red-50/80 border border-red-200 text-red-900 text-xs">
                    <h4 className="font-bold text-sm mb-1 text-red-950">Primary Finding (EN):</h4>
                    <p className="leading-relaxed">{currentResult.verdict_summary}</p>
                  </div>

                  {currentResult.verdict_summary_ms && (
                    <div className="p-4 rounded-2xl bg-blue-50/80 border border-blue-200 text-blue-900 text-xs">
                      <h4 className="font-bold text-sm mb-1 text-blue-950">Ringkasan Keputusan (MS):</h4>
                      <p className="leading-relaxed">{currentResult.verdict_summary_ms}</p>
                    </div>
                  )}

                  {currentResult.recommendation && (
                    <div className="p-4 rounded-2xl bg-amber-50/80 border border-amber-200 text-amber-900 text-xs">
                      <h4 className="font-bold text-sm mb-1 text-amber-950">💡 Recommendation:</h4>
                      <p className="leading-relaxed">{currentResult.recommendation}</p>
                    </div>
                  )}
                </div>
              </div>

              {/* Cooling-Off Period Banner */}
              {coolingOffTimer !== null && (
                <div className="p-4 rounded-2xl bg-red-50 border border-red-200 flex items-center gap-4 mb-6">
                  <span className="material-symbols-outlined text-red-500 text-3xl animate-spin">schedule</span>
                  <div>
                    <h4 className="font-bold text-sm text-red-900 mb-1">High-Risk Transaction Frozen (30-Min Cooling Off)</h4>
                    <p className="text-xs text-red-700">
                      TranSafe Multi-Agent network blocked execution due to confirmed scam activity.
                      Account unfreezes in {Math.floor(coolingOffTimer / 60)}m {coolingOffTimer % 60}s.
                    </p>
                  </div>
                </div>
              )}

              {/* Action Buttons */}
              <div className="flex flex-col sm:flex-row gap-4 border-t pt-6">
                <button
                  onClick={() => setActiveXaiReport(currentResult)}
                  className="btn-primary flex-1 py-4 justify-center bg-[#0066ff] hover:bg-[#0050cb] text-white font-bold"
                >
                  <span className="material-symbols-outlined text-lg">description</span>
                  View Full XAI Report
                </button>
                <button
                  onClick={handleDismiss}
                  className="btn-secondary flex-1 py-4 justify-center border border-gray-300 text-gray-700 font-bold rounded-2xl hover:bg-gray-100 transition-colors"
                >
                  Return to Dashboard
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Modals */}
      <XaiReportModal report={activeXaiReport} onClose={() => setActiveXaiReport(null)} />
      {biometricChallenge && (
        <BiometricModal
          userId={userId}
          transactionId={biometricChallenge.txId}
          onSubmitResult={handleBiometricSubmit}
          onClose={() => setBiometricChallenge(null)}
        />
      )}
    </div>
  );
};
