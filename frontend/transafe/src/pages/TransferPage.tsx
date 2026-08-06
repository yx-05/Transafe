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

  // Form State matching /backend/mock_frontend TransactionCard
  const [senderAccount, setSenderAccount] = useState<string>('6373-5093-3430-8430 (Maybank Premier)');
  const [bank, setBank] = useState<string>('CIMB Bank');
  const [recipientName, setRecipientName] = useState<string>('JJ Poor to Rich (JJPTR)');
  const [accountNumber, setAccountNumber] = useState<string>('1122-3344-5566-7788');
  const [amount, setAmount] = useState<string>('15000.00');
  const [description, setDescription] = useState<string>('JJPTR Forex Investment Deposit');
  const [associatedCaseId, setAssociatedCaseId] = useState<string>('case-891');
  const [linkageMode, setLinkageMode] = useState<'auto' | 'manual' | 'none'>('auto');

  // Preset quick fill handler matching backend dataset presets
  const applyPreset = (preset: {
    account: string;
    name: string;
    bankName: string;
    amt: string;
    desc: string;
    caseId?: string;
  }) => {
    setAccountNumber(preset.account);
    setRecipientName(preset.name);
    setBank(preset.bankName);
    setAmount(preset.amt);
    setDescription(preset.desc);
    if (preset.caseId) setAssociatedCaseId(preset.caseId);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const parsedAmount = parseFloat(amount) || 0;
    
    await submitTransferScan({
      bank,
      recipientName,
      accountNumber,
      amount: parsedAmount,
      description,
      associatedCaseId: linkageMode === 'manual' ? associatedCaseId : linkageMode === 'auto' ? (associatedCaseId || 'case-891') : undefined
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
    <div className="user-app-layout pb-28 min-h-screen relative bg-[#f8f9fa]">
      {/* Header Banner */}
      <div className="blue-header-bg blue-header-bg--short"></div>

      <div className="main-content-wrapper px-4 sm:px-6 md:px-8">
        <UserHeader title="Secure Transfer" showBack={true} />

        <div className="max-w-2xl mx-auto relative z-10 pt-2">
          {/* ======================================================
              PANEL A: TRANSFER FORM
             ====================================================== */}
          {!isScanningTransfer && !lastScanVerdict && (
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
                      desc: 'Pak Man Telo Deposit',
                      caseId: 'case-891'
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
                      desc: 'M-Coin Investment Topup',
                      caseId: 'case-891'
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
                      desc: 'Gold Scheme Investment',
                      caseId: 'case-891'
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
                      desc: 'JJPTR Forex Deposit',
                      caseId: 'case-891'
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
                      desc: 'Richway Global Deposit',
                      caseId: 'case-891'
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

                {/* Recipient Account Number */}
                <div className="form-group mb-0">
                  <label className="form-label text-xs uppercase tracking-wider text-gray-500 font-bold mb-2">
                    Recipient Account (Mule / Destination)
                  </label>
                  <input
                    type="text"
                    value={accountNumber}
                    onChange={(e) => setAccountNumber(e.target.value)}
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
                    Link Transaction to Recent Activity (Fraud Correlation)
                  </label>

                  <div className="flex flex-col gap-2">
                    <div
                      onClick={() => setLinkageMode('auto')}
                      className={`p-3.5 rounded-2xl border transition-all cursor-pointer flex items-start gap-3 ${
                        linkageMode === 'auto'
                          ? 'bg-blue-50/80 border-[#0066ff] shadow-sm'
                          : 'bg-gray-50 border-gray-200'
                      }`}
                    >
                      <input type="radio" checked={linkageMode === 'auto'} onChange={() => setLinkageMode('auto')} className="mt-1" />
                      <div>
                        <p className="text-xs font-bold text-gray-900">
                          (Recommended) Automatically check recent calls & phishing checks
                        </p>
                        <p className="text-[11px] text-gray-500 mt-0.5">
                          Correlates bank details against recent active phone calls or uploaded WhatsApp screenshots (Past 2 Hours).
                        </p>
                      </div>
                    </div>

                    <div
                      onClick={() => setLinkageMode('manual')}
                      className={`p-3.5 rounded-2xl border transition-all cursor-pointer flex items-start gap-3 ${
                        linkageMode === 'manual'
                          ? 'bg-blue-50/80 border-[#0066ff] shadow-sm'
                          : 'bg-gray-50 border-gray-200'
                      }`}
                    >
                      <input type="radio" checked={linkageMode === 'manual'} onChange={() => setLinkageMode('manual')} className="mt-1" />
                      <div className="w-full">
                        <p className="text-xs font-bold text-gray-900">Select a specific context manually</p>
                        {linkageMode === 'manual' && (
                          <select
                            value={associatedCaseId}
                            onChange={(e) => setAssociatedCaseId(e.target.value)}
                            className="form-select text-xs font-mono mt-2"
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
                      className={`p-3.5 rounded-2xl border transition-all cursor-pointer flex items-start gap-3 ${
                        linkageMode === 'none'
                          ? 'bg-blue-50/80 border-[#0066ff] shadow-sm'
                          : 'bg-gray-50 border-gray-200'
                      }`}
                    >
                      <input type="radio" checked={linkageMode === 'none'} onChange={() => setLinkageMode('none')} className="mt-1" />
                      <div>
                        <p className="text-xs font-bold text-gray-900">No prior call/phishing activity relates to this transfer</p>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Submit Action Button */}
                <div className="mt-4">
                  <button
                    type="submit"
                    className="btn-primary w-full py-4 justify-center bg-[#0066ff] hover:bg-[#0050cb] text-white font-bold shadow-lg shadow-blue-500/20 text-sm"
                  >
                    <span className="material-symbols-outlined text-xl">shield_lock</span>
                    Authorize & Scan Transfer
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* ======================================================
              PANEL B: LIVE SECURITY SCANNER OVERLAY
             ====================================================== */}
          {isScanningTransfer && (
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
                {scannerLogs.map((log, idx) => (
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
          {lastScanVerdict && !isScanningTransfer && (
            <div className="neo-card bg-white shadow-2xl rounded-[32px] p-8 border border-gray-100">
              {/* Header Badge */}
              <div className="flex justify-between items-center border-b pb-4 mb-6">
                <h2 className="text-2xl font-extrabold text-gray-900">Multi-Agent System Verdict</h2>
                <span
                  className="px-3.5 py-1 rounded-full text-xs font-bold uppercase tracking-wider"
                  style={{
                    backgroundColor: scoreColor,
                    color: '#ffffff'
                  }}
                >
                  {lastScanVerdict.riskTier} RISK ({lastScanVerdict.riskScore}/100)
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
                      <span className="text-4xl font-extrabold text-gray-900">{lastScanVerdict.riskScore}</span>
                      <span className="text-[10px] font-bold uppercase text-gray-400">Risk Score</span>
                    </div>
                  </div>
                </div>

                {/* English & Malay Verdict Summary */}
                <div className="md:col-span-7 flex flex-col gap-4">
                  <div className="p-4 rounded-2xl bg-red-50/80 border border-red-200 text-red-900 text-xs">
                    <h4 className="font-bold text-sm mb-1 text-red-950">Primary Finding (EN):</h4>
                    <p className="leading-relaxed">{lastScanVerdict.summaryEn}</p>
                  </div>

                  <div className="p-4 rounded-2xl bg-blue-50/80 border border-blue-200 text-blue-900 text-xs">
                    <h4 className="font-bold text-sm mb-1 text-blue-950">Ringkasan Keputusan (MS):</h4>
                    <p className="leading-relaxed">{lastScanVerdict.summaryMs}</p>
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-col sm:flex-row gap-4 border-t pt-6">
                <button
                  onClick={handleDismiss}
                  className="btn-primary flex-1 py-4 justify-center bg-[#0066ff] hover:bg-[#0050cb] text-white font-bold"
                >
                  Return to Dashboard
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
