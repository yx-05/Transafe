import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSimulation } from '../context/SimulationContext';
import { UserHeader } from '../components/UserHeader';

export const TransferPage: React.FC = () => {
  const {
    isScanningTransfer,
    scannerLogs,
    lastScanVerdict,
    submitTransferScan,
    clearScanVerdict,
    fraudCases,
    accountBalance
  } = useSimulation();

  const navigate = useNavigate();

  // Form State
  const [bank, setBank] = useState<string>('Maybank');
  const [recipientName, setRecipientName] = useState<string>('Ali Bin Ahmad');
  const [accountNumber, setAccountNumber] = useState<string>('7653-1234-5678');
  const [amount, setAmount] = useState<string>('5000.00');
  const [description, setDescription] = useState<string>('Emergency Investment Transfer');
  const [linkageMode, setLinkageMode] = useState<'auto' | 'manual' | 'none'>('auto');
  const [selectedCaseId, setSelectedCaseId] = useState<string>('case-891');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const parsedAmount = parseFloat(amount) || 0;
    
    await submitTransferScan({
      bank,
      recipientName,
      accountNumber,
      amount: parsedAmount,
      description,
      associatedCaseId: linkageMode === 'manual' ? selectedCaseId : linkageMode === 'auto' ? 'case-891' : undefined
    });
  };

  const handleDismiss = () => {
    clearScanVerdict();
    navigate('/');
  };

  // Calculate stroke offset for circular dial (Score 0-100)
  const radius = 70;
  const circumference = 2 * Math.PI * radius;
  const score = lastScanVerdict?.riskScore || 0;
  const strokeDashoffset = circumference - (score / 100) * circumference;

  const scoreColor =
    score > 70 ? 'var(--risk-high)' : score > 30 ? 'var(--risk-med)' : 'var(--risk-low)';

  return (
    <div className="user-app-layout" style={{ paddingBottom: '100px' }}>
      {/* Header Banner */}
      <div className="blue-header-bg blue-header-bg--short"></div>

      <div className="header-padding-wrapper">
        <UserHeader title="Secure Transfer" showBack={true} />
      </div>

      <div className="main-content-wrapper px-4 sm:px-6">
        <div className="max-w-2xl mx-auto relative z-10" style={{ marginTop: '8px' }}>
          {/* ======================================================
              PANEL A: TRANSFER FORM
             ====================================================== */}
          {!isScanningTransfer && !lastScanVerdict && (
            <div className="neo-card bg-white shadow-xl">
              <div className="flex items-center justify-between border-b pb-4" style={{ marginBottom: '24px' }}>
                <div>
                  <h2 className="text-2xl font-bold text-gray-900">Funds Transfer</h2>
                  <p className="text-xs text-gray-500" style={{ marginTop: '8px' }}>
                    Available Balance: <strong className="text-gray-900">RM {accountBalance.toFixed(2)}</strong>
                  </p>
                </div>
              </div>

              <form onSubmit={handleSubmit}>
                {/* Beneficiary Bank */}
                <div className="form-group">
                  <label className="form-label">Beneficiary Bank</label>
                  <select
                    value={bank}
                    onChange={(e) => setBank(e.target.value)}
                    className="form-select"
                  >
                    <option value="Maybank">Maybank (Malayan Banking Berhad)</option>
                    <option value="CIMB Bank">CIMB Bank Berhad</option>
                    <option value="Public Bank">Public Bank Berhad</option>
                    <option value="RHB Bank">RHB Bank Berhad</option>
                    <option value="Hong Leong Bank">Hong Leong Bank Berhad</option>
                    <option value="Bank Islam">Bank Islam Malaysia Berhad</option>
                  </select>
                </div>

                {/* Recipient Name */}
                <div className="form-group">
                  <label className="form-label">Recipient Name</label>
                  <input
                    type="text"
                    value={recipientName}
                    onChange={(e) => setRecipientName(e.target.value)}
                    placeholder="e.g., JOHN DOE"
                    className="form-input"
                    required
                  />
                </div>

                {/* Account Number */}
                <div className="form-group">
                  <label className="form-label">Account Number</label>
                  <input
                    type="text"
                    value={accountNumber}
                    onChange={(e) => setAccountNumber(e.target.value)}
                    placeholder="e.g., 1641-2345-6789"
                    className="form-input font-mono"
                    required
                  />
                </div>

                {/* Amount */}
                <div className="form-group">
                  <label className="form-label">Amount (MYR)</label>
                  <div style={{ position: 'relative' }}>
                    <span style={{ position: 'absolute', left: '16px', top: '50%', transform: 'translateY(-50%)', color: '#4b5563', fontWeight: 'bold', fontSize: '18px', pointerEvents: 'none' }}>RM</span>
                    <input
                      type="number"
                      step="0.01"
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                      placeholder="0.00"
                      className="form-input text-lg font-bold"
                      style={{ paddingLeft: '48px' }}
                      required
                    />
                  </div>
                </div>

                {/* Description */}
                <div className="form-group">
                  <label className="form-label">Description / Reference</label>
                  <input
                    type="text"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="e.g., Monthly Rent / Crypto Buy"
                    className="form-input"
                  />
                </div>

                {/* Case Linkage Selector (Fraud Context Correlation) */}
                <div className="form-group mt-6">
                  <label className="form-label font-bold text-gray-900 mb-2">
                    Link Transaction to Recent Activity (Fraud Correlation)
                  </label>

                  <div
                    onClick={() => setLinkageMode('auto')}
                    className={`radio-card ${linkageMode === 'auto' ? 'selected' : ''}`}
                  >
                    <input type="radio" checked={linkageMode === 'auto'} onChange={() => setLinkageMode('auto')} style={{ marginTop: '4px' }} />
                    <div style={{ paddingTop: 0, marginTop: 0 }}>
                      <p className="text-sm font-bold text-gray-900">
                        (Recommended) Automatically check recent calls & phishing checks
                      </p>
                      <p className="text-xs text-gray-500">
                        Correlates bank details against recent active phone calls or uploaded WhatsApp screenshots (Past 2 Hours).
                      </p>
                    </div>
                  </div>

                  <div
                    onClick={() => setLinkageMode('manual')}
                    className={`radio-card ${linkageMode === 'manual' ? 'selected' : ''}`}
                  >
                    <input type="radio" checked={linkageMode === 'manual'} onChange={() => setLinkageMode('manual')} style={{ marginTop: '4px' }} />
                    <div className="w-full">
                      <p className="text-sm font-bold text-gray-900">Select a specific context manually</p>
                      {linkageMode === 'manual' && (
                        <select
                          value={selectedCaseId}
                          onChange={(e) => setSelectedCaseId(e.target.value)}
                          className="form-select text-xs"
                          style={{ marginTop: '12px' }}
                        >
                          {fraudCases.map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.triggerType}: Case {c.id} ({c.summaryEn.substring(0, 45)}...)
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                  </div>

                  <div
                    onClick={() => setLinkageMode('none')}
                    className={`radio-card ${linkageMode === 'none' ? 'selected' : ''}`}
                  >
                    <input type="radio" checked={linkageMode === 'none'} onChange={() => setLinkageMode('none')} style={{ marginTop: '4px' }} />
                    <div>
                      <p className="text-sm font-bold text-gray-900">No prior call/phishing activity relates to this transfer</p>
                    </div>
                  </div>
                </div>

                {/* Action Buttons */}
                <div className="flex flex-col sm:flex-row gap-4 mt-8">
                  <button type="submit" className="btn-primary flex-1 py-4 justify-center">
                    <span className="material-symbols-outlined">shield_lock</span>
                    Authorize Transfer
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* ======================================================
              PANEL B: LIVE SECURITY SCANNER OVERLAY
             ====================================================== */}
          {isScanningTransfer && (
            <div className="neo-card bg-white shadow-2xl text-center py-10 px-6">
              <div className="w-20 h-20 mx-auto mb-6 relative flex items-center justify-center">
                <div className="w-20 h-20 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin"></div>
                <span className="material-symbols-outlined text-blue-600 text-3xl absolute">lock_reset</span>
              </div>

              <h2 className="text-2xl font-extrabold text-gray-900 mb-2">SecureTransfer Active Scan</h2>
              <p className="text-sm text-gray-500 mb-6">
                Executing multi-agent fraud inspection across BNM, NSRC & biometrics engines...
              </p>

              {/* Log Terminal Output */}
              <div className="scanner-terminal text-left mb-6">
                {scannerLogs.map((log, idx) => (
                  <div key={idx} className="scanner-log-line">
                    <span className="text-green-400 font-bold">&gt;</span>
                    <span>{log}</span>
                  </div>
                ))}
              </div>

              <p className="text-xs text-gray-400 animate-pulse">
                Please do not close this window. Intercepting fraud vectors in real-time...
              </p>
            </div>
          )}

          {/* ======================================================
              PANEL C: MULTI-AGENT SYSTEM VERDICT
             ====================================================== */}
          {lastScanVerdict && !isScanningTransfer && (
            <div className="neo-card bg-white shadow-2xl">
              {/* Header Badge */}
              <div className="flex justify-between items-center border-b pb-4 mb-6">
                <h2 className="text-2xl font-extrabold text-gray-900">Multi-Agent System Verdict</h2>
                <span className={`risk-pill ${lastScanVerdict.riskTier.toLowerCase()}`}>
                  {lastScanVerdict.riskTier === 'HIGH' && 'HIGH RISK — ACTION DISPATCHED'}
                  {lastScanVerdict.riskTier === 'MEDIUM' && 'MEDIUM RISK — REVIEW TRIGGERED'}
                  {lastScanVerdict.riskTier === 'LOW' && 'LOW RISK — APPROVED'}
                </span>
              </div>

              {/* Risk Gauge Dial */}
              <div className="score-gauge-container">
                <svg className="score-gauge-svg" viewBox="0 0 160 160">
                  <circle className="score-gauge-circle-bg" cx="80" cy="80" r={radius} />
                  <circle
                    className="score-gauge-circle-val"
                    cx="80"
                    cy="80"
                    r={radius}
                    style={{
                      stroke: scoreColor,
                      strokeDasharray: circumference,
                      strokeDashoffset
                    }}
                  />
                </svg>
                <div className="score-gauge-value" style={{ color: scoreColor }}>
                  <span>{lastScanVerdict.riskScore}</span>
                  <span className="score-gauge-label">Risk Index</span>
                </div>
              </div>

              {/* Dynamic Active Protection Action Banner */}
              <div className="my-6">
                {lastScanVerdict.actionTaken === 'FREEZE_30_MIN' && (
                  <div className="p-4 rounded-2xl bg-red-50 border-2 border-red-200 text-red-900 flex items-start gap-3 pulse-red">
                    <span className="material-symbols-outlined text-red-600 text-3xl flex-shrink-0">warning</span>
                    <div>
                      <h4 className="font-bold text-base">🚨 Protection Triggered</h4>
                      <p className="text-xs mt-1">
                        Your banking account has been temporarily frozen for a 30-minute cooling-off period to prevent potential scam loss under BNM guidelines.
                      </p>
                    </div>
                  </div>
                )}

                {lastScanVerdict.actionTaken === 'BLOCK_TRANSACTION' && (
                  <div className="p-4 rounded-2xl bg-red-50 border-2 border-red-300 text-red-900 flex items-start gap-3">
                    <span className="material-symbols-outlined text-red-600 text-3xl flex-shrink-0">block</span>
                    <div>
                      <h4 className="font-bold text-base">🚫 Transaction Intercepted</h4>
                      <p className="text-xs mt-1">
                        The recipient account matches a known fraudulent account in the NSRC national database.
                      </p>
                    </div>
                  </div>
                )}

                {lastScanVerdict.actionTaken === 'ALERT_ADMIN' && (
                  <div className="p-4 rounded-2xl bg-amber-50 border-2 border-amber-300 text-amber-900 flex items-start gap-3">
                    <span className="material-symbols-outlined text-amber-600 text-3xl flex-shrink-0">pending_actions</span>
                    <div>
                      <h4 className="font-bold text-base">⚠️ Held for Verification</h4>
                      <p className="text-xs mt-1">
                        The transaction is pending review by our security operations team. You will be contacted shortly.
                      </p>
                    </div>
                  </div>
                )}

                {lastScanVerdict.actionTaken === 'ALLOW' && (
                  <div className="p-4 rounded-2xl bg-emerald-50 border-2 border-emerald-300 text-emerald-900 flex items-start gap-3">
                    <span className="material-symbols-outlined text-emerald-600 text-3xl flex-shrink-0">check_circle</span>
                    <div>
                      <h4 className="font-bold text-base">✅ Safe to Proceed</h4>
                      <p className="text-xs mt-1">Transaction verified and processed successfully.</p>
                    </div>
                  </div>
                )}
              </div>

              {/* Explainable AI Explanation Card */}
              <div className="p-5 rounded-2xl bg-gray-50 border border-gray-200 mb-8">
                <h4 className="text-xs uppercase font-bold text-gray-500 tracking-wider mb-2">Verdict Explanation (Bilingual XAI)</h4>
                <p className="text-sm font-semibold text-gray-900 mb-3">{lastScanVerdict.summaryEn}</p>
                <div className="border-t border-gray-200 pt-2 text-xs text-gray-600 italic">
                  <strong>Bahasa Melayu:</strong> {lastScanVerdict.summaryMs}
                </div>
              </div>

              {/* Verdict Action Buttons */}
              <div className="flex flex-col sm:flex-row gap-4">
                <button onClick={handleDismiss} className="btn-primary flex-1 py-4 justify-center">
                  Dismiss & Return to Home
                </button>
                {['HIGH', 'MEDIUM'].includes(lastScanVerdict.riskTier) && (
                  <a href="tel:997" className="btn-danger py-4 justify-center text-center">
                    <span className="material-symbols-outlined">call</span>
                    Call NSRC Hotline (997)
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
