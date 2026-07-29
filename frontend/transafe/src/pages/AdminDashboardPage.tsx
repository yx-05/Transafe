import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useSimulation } from '../context/SimulationContext';

export const AdminDashboardPage: React.FC = () => {
  const { fraudCases, selectedCaseId, setSelectedCaseId, updateCaseStatus } = useSimulation();
  const { id: paramCaseId } = useParams();
  const navigate = useNavigate();

  const [filter, setFilter] = useState<'ALL' | 'HIGH' | 'PENDING' | 'FROZEN'>('ALL');

  // Handle direct URL navigation /admin/case/:id
  const activeCaseId = paramCaseId || selectedCaseId || (fraudCases.length > 0 ? fraudCases[0].id : null);
  const activeCase = fraudCases.find((c) => c.id === activeCaseId) || fraudCases[0];

  const filteredCases = fraudCases.filter((c) => {
    if (filter === 'HIGH') return c.riskScore >= 70;
    if (filter === 'PENDING') return c.status === 'PENDING_REVIEW';
    if (filter === 'FROZEN') return c.status === 'FROZEN';
    return true;
  });

  const getRiskColor = (score: number) => {
    if (score >= 70) return '#ef4444';
    if (score >= 30) return '#f59e0b';
    return '#10b981';
  };

  const handleSelectCase = (id: string) => {
    setSelectedCaseId(id);
    navigate(`/admin/case/${id}`);
  };

  return (
    <div className="admin-layout">
      {/* ======================================================
          LEFT PANE: REAL-TIME CASE FEED
         ====================================================== */}
      <aside className="admin-sidebar">
        <div className="flex justify-between items-center pb-2 border-b border-gray-800">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <span className="material-symbols-outlined text-blue-500">space_dashboard</span>
              Fraud Operations
            </h2>
            <p className="text-xs text-gray-400">Real-Time Case Feed</p>
          </div>
          <span className="text-[10px] font-mono bg-blue-900/50 text-blue-400 px-2 py-1 rounded border border-blue-700">
            {fraudCases.length} ACTIVE
          </span>
        </div>

        {/* Filter Chips */}
        <div className="flex gap-1.5 overflow-x-auto pb-1">
          {(['ALL', 'HIGH', 'PENDING', 'FROZEN'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${
                filter === f
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white'
              }`}
            >
              {f}
            </button>
          ))}
        </div>

        {/* Case Cards List */}
        <div className="flex flex-col gap-3 overflow-y-auto pr-1">
          {filteredCases.length === 0 ? (
            <p className="text-xs text-gray-500 text-center py-8">No cases found matching filter.</p>
          ) : (
            filteredCases.map((c) => {
              const isSelected = c.id === activeCaseId;
              const color = getRiskColor(c.riskScore);

              return (
                <div
                  key={c.id}
                  onClick={() => handleSelectCase(c.id)}
                  className={`case-card ${isSelected ? 'active' : ''}`}
                >
                  <div className="flex justify-between items-start mb-2">
                    <div>
                      <span className="text-xs font-mono font-bold text-blue-400">{c.id}</span>
                      <h4 className="text-sm font-bold text-white">{c.userName}</h4>
                    </div>

                    <span
                      className="px-2 py-0.5 rounded text-xs font-extrabold"
                      style={{
                        backgroundColor: `${color}20`,
                        color,
                        border: `1px solid ${color}40`
                      }}
                    >
                      SCORE {c.riskScore}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-xs text-gray-400">
                    <span className="flex items-center gap-1 font-mono uppercase text-[10px] bg-gray-900 px-2 py-0.5 rounded">
                      <span className="material-symbols-outlined text-xs text-gray-400">
                        {c.triggerType === 'CALL'
                          ? 'phone_in_talk'
                          : c.triggerType === 'PHISHING'
                          ? 'image'
                          : 'sync_alt'}
                      </span>
                      {c.triggerType}
                    </span>
                    <span>{c.timestamp}</span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </aside>

      {/* ======================================================
          RIGHT PANE: CASE INSPECTOR
         ====================================================== */}
      <main className="admin-main">
        {activeCase ? (
          <div className="max-w-4xl mx-auto flex flex-col gap-6">
            {/* Header Deck */}
            <div className="neo-card bg-gray-900 border border-gray-800 text-white p-6 shadow-2xl">
              <div className="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-gray-800 pb-4 mb-6 gap-4">
                <div>
                  <div className="flex items-center gap-3">
                    <h1 className="text-2xl font-extrabold text-white">Case Inspection: {activeCase.id}</h1>
                    <span
                      className="risk-pill text-xs"
                      style={{
                        backgroundColor: `${getRiskColor(activeCase.riskScore)}20`,
                        color: getRiskColor(activeCase.riskScore),
                        border: `1px solid ${getRiskColor(activeCase.riskScore)}40`
                      }}
                    >
                      RISK {activeCase.riskScore} / 100
                    </span>
                  </div>
                  <p className="text-xs text-gray-400 mt-1">
                    User ID: <strong className="text-gray-200">{activeCase.userId} ({activeCase.userName})</strong> • Triggered {activeCase.timestamp}
                  </p>
                </div>

                {/* Status Badge */}
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-400 uppercase font-mono">Status:</span>
                  <span className="px-3 py-1 rounded-full text-xs font-bold bg-blue-950 text-blue-300 border border-blue-700">
                    {activeCase.status}
                  </span>
                </div>
              </div>

              {/* XAI Verdict Summary Card */}
              <div className="p-4 rounded-xl bg-gray-950 border border-gray-800 mb-6">
                <h4 className="text-xs font-bold uppercase tracking-wider text-blue-400 mb-2">
                  Explainable AI (XAI) Synthesis
                </h4>
                <p className="text-sm font-semibold text-gray-200 mb-2">{activeCase.summaryEn}</p>
                <p className="text-xs text-gray-400 italic">Bahasa Melayu: {activeCase.summaryMs}</p>
              </div>

              {/* Worker Findings Accordion Grid */}
              <h3 className="text-sm font-bold text-gray-300 uppercase tracking-wider mb-3">
                Multi-Agent Worker Evaluation Breakdown
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                {activeCase.workerFindings.map((worker, idx) => (
                  <div
                    key={idx}
                    className="p-4 rounded-xl bg-gray-950 border border-gray-800 flex flex-col justify-between"
                  >
                    <div>
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-xs font-bold text-white">{worker.workerName}</span>
                        <span
                          className={`text-[10px] font-bold px-2 py-0.5 rounded ${
                            worker.status === 'CRITICAL'
                              ? 'bg-red-950 text-red-400 border border-red-800'
                              : worker.status === 'WARNING'
                              ? 'bg-amber-950 text-amber-400 border border-amber-800'
                              : 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                          }`}
                        >
                          {worker.score}% SCORE
                        </span>
                      </div>
                      <ul className="text-xs text-gray-400 space-y-1 mt-2 list-disc list-inside">
                        {worker.evidence.map((ev, eIdx) => (
                          <li key={eIdx}>{ev}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                ))}
              </div>

              {/* Media Viewer: Transcript or Screenshot */}
              <div className="mb-6">
                <h3 className="text-sm font-bold text-gray-300 uppercase tracking-wider mb-3">
                  Evidence Media Viewer
                </h3>

                {activeCase.triggerType === 'CALL' && activeCase.transcript && (
                  <div className="bg-gray-950 p-4 rounded-xl border border-gray-800 max-h-60 overflow-y-auto flex flex-col gap-2">
                    {activeCase.transcript.map((line) => (
                      <div key={line.id} className="text-xs font-mono">
                        <span className="text-gray-500">[{line.timestamp}] </span>
                        <strong className={line.speaker === 'caller' ? 'text-red-400' : 'text-blue-400'}>
                          {line.speaker.toUpperCase()}:
                        </strong>{' '}
                        <span className="text-gray-300">{line.text}</span>
                      </div>
                    ))}
                  </div>
                )}

                {activeCase.triggerType === 'PHISHING' && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {activeCase.screenshotUrl && (
                      <img
                        src={activeCase.screenshotUrl}
                        alt="Screenshot Evidence"
                        className="rounded-xl border border-gray-800 max-h-60 object-cover w-full"
                      />
                    )}
                    <div className="bg-gray-950 p-4 rounded-xl border border-gray-800 text-xs font-mono text-green-400">
                      <p className="text-gray-500 font-bold uppercase text-[10px] mb-2">OCR Text Capture:</p>
                      <p>{activeCase.ocrText || 'No OCR text extracted.'}</p>
                    </div>
                  </div>
                )}

                {activeCase.triggerType === 'TRANSACTION' && (
                  <div className="bg-gray-950 p-4 rounded-xl border border-gray-800 text-xs text-gray-300">
                    <p className="font-bold text-blue-400 mb-1">Transaction Vector Correlation:</p>
                    <p>Associated Case ID: {activeCase.associatedCaseId || 'Auto-correlated via 2-Hour Window'}</p>
                    <p>Financial Deviation: 420% above 90-day baseline</p>
                  </div>
                )}
              </div>

              {/* Fraud Officer Action Bar */}
              <div className="border-t border-gray-800 pt-6 flex flex-wrap gap-3">
                <button
                  onClick={() => updateCaseStatus(activeCase.id, 'FROZEN', 'FREEZE_30_MIN')}
                  className="btn-danger py-3 text-xs"
                >
                  <span className="material-symbols-outlined text-sm">ac_unit</span>
                  Freeze Account (30 Min)
                </button>

                <button
                  onClick={() => updateCaseStatus(activeCase.id, 'BLOCKED', 'BLOCK_TRANSACTION')}
                  className="btn-danger py-3 text-xs bg-red-800 hover:bg-red-900"
                >
                  <span className="material-symbols-outlined text-sm">block</span>
                  Block Recipient NSRC
                </button>

                <button
                  onClick={() => updateCaseStatus(activeCase.id, 'PENDING_REVIEW', 'ALERT_ADMIN')}
                  className="btn-secondary py-3 text-xs bg-amber-900/40 text-amber-300 border border-amber-700"
                >
                  <span className="material-symbols-outlined text-sm">flag</span>
                  Flag for Senior Review
                </button>

                <button
                  onClick={() => updateCaseStatus(activeCase.id, 'APPROVED', 'ALLOW')}
                  className="btn-secondary py-3 text-xs bg-emerald-950 text-emerald-300 border border-emerald-700 ml-auto"
                >
                  <span className="material-symbols-outlined text-sm">check_circle</span>
                  Dismiss Alert & Allow
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="text-center py-20 text-gray-500">Select a case from the left feed to inspect.</div>
        )}
      </main>
    </div>
  );
};
