import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useApi } from '../context/ApiContext';
import { SettingsModal } from '../components/SettingsModal';
import type {
  AdminAlertItem,
  AdminCaseItem,
  AdminAccountItem,
  AnalyticsSummary,
  AnalyticsTrendPoint,
} from '../types/api';

type AdminTab = 'inspect' | 'analytics' | 'accounts' | 'alerts';

export const AdminDashboardPage: React.FC = () => {
  const { config, client, setConfig } = useApi();
  const { id: paramCaseId } = useParams();
  const navigate = useNavigate();
  const [showSettings, setShowSettings] = useState(false);

  // ---- Case feed state ----
  const [cases, setCases] = useState<AdminCaseItem[]>([]);
  const [totalCases, setTotalCases] = useState(0);
  const [hasNext, setHasNext] = useState(false);
  const [page, setPage] = useState(1);
  const [riskTier, setRiskTier] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [triggerFilter, setTriggerFilter] = useState('all');
  const [casesLoading, setCasesLoading] = useState(false);
  const [busyCase, setBusyCase] = useState<string | null>(null);

  // ---- Inspector state ----
  const [activeTab, setActiveTab] = useState<AdminTab>('inspect');
  const [detail, setDetail] = useState<Record<string, any> | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // ---- Accounts state ----
  const [accounts, setAccounts] = useState<AdminAccountItem[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(false);
  const [busyAccount, setBusyAccount] = useState<string | null>(null);
  const [actionResult, setActionResult] = useState<any>(null);

  // ---- Alerts state ----
  const [alerts, setAlerts] = useState<AdminAlertItem[]>([]);
  const [alertsLoading, setAlertsLoading] = useState(false);

  // ---- Analytics state ----
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [trend, setTrend] = useState<AnalyticsTrendPoint[]>([]);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);

  // ---- Fetch case feed ----
  const fetchCases = async () => {
    setCasesLoading(true);
    try {
      const res = await client.listAdminCases(page, 10, riskTier, statusFilter, triggerFilter);
      setCases(res.items || []);
      setTotalCases(res.total || 0);
      setHasNext(!!res.has_next);
    } catch (err: any) {
      console.error('Fetch admin cases failed', err);
    } finally {
      setCasesLoading(false);
    }
  };

  // Handle direct URL navigation /admin/case/:id
  const activeCaseId = paramCaseId || (cases.length > 0 ? cases[0].case_id : null);

  useEffect(() => {
    fetchCases();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.baseUrl, config.adminKey, page, riskTier, statusFilter, triggerFilter]);

  // ---- Fetch case detail ----
  const fetchDetail = async (caseId: string) => {
    setDetailLoading(true);
    try {
      const res = await client.getCaseDetail(caseId);
      setDetail(res);
    } catch (err: any) {
      console.error('Fetch case detail error', err);
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    if (!activeCaseId) {
      setDetail(null);
      return;
    }
    fetchDetail(activeCaseId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.baseUrl, config.adminKey, activeCaseId]);

  // ---- Fetch accounts ----
  const fetchAccounts = async () => {
    setAccountsLoading(true);
    try {
      const res = await client.listAdminAccounts();
      setAccounts(res.items || []);
    } catch (err: any) {
      console.error('Fetch accounts failed', err);
    } finally {
      setAccountsLoading(false);
    }
  };

  // ---- Fetch alerts ----
  const fetchAlerts = async () => {
    setAlertsLoading(true);
    try {
      const res = await client.listAdminAlerts();
      setAlerts(res.items || []);
    } catch (err: any) {
      console.error('Fetch alerts error', err);
    } finally {
      setAlertsLoading(false);
    }
  };

  // ---- Fetch analytics ----
  const fetchAnalytics = async () => {
    setAnalyticsLoading(true);
    try {
      const sumRes = await client.getAnalyticsSummary();
      setSummary(sumRes);
      const trendRes = await client.getAnalyticsTrend();
      setTrend(trendRes.series || []);
    } catch (err: any) {
      console.error('Analytics fetch failed', err);
    } finally {
      setAnalyticsLoading(false);
    }
  };

  // ---- Actions ----
  const handleCaseAction = async (caseId: string, action: 'freeze' | 'unfreeze') => {
    const reason =
      action === 'freeze'
        ? window.prompt('Freeze reason:', 'Suspected fraud - admin freeze')
        : window.prompt('Unfreeze reason:', 'Cleared by admin');
    if (reason === null) return;

    setBusyCase(caseId);
    try {
      if (action === 'freeze') {
        await client.freezeCase(caseId, reason);
      } else {
        await client.unfreezeCase(caseId, reason);
      }
      await fetchCases();
      await fetchDetail(caseId);
    } catch (err: any) {
      window.alert(`${action === 'freeze' ? 'Freeze' : 'Unfreeze'} failed: ${err.message}`);
    } finally {
      setBusyCase(null);
    }
  };

  const handleAccountAction = async (accountNumber: string, action: 'freeze' | 'unfreeze') => {
    const reason =
      action === 'freeze'
        ? window.prompt('Freeze reason:', 'Suspected involvement in active scam activity')
        : window.prompt('Unfreeze reason:', 'Investigation cleared by admin');
    if (reason === null) return;

    setBusyAccount(accountNumber);
    setActionResult(null);
    try {
      const res =
        action === 'freeze'
          ? await client.freezeAccount(accountNumber, reason)
          : await client.unfreezeAccount(accountNumber, reason);
      setActionResult(res);
      await fetchAccounts();
    } catch (err: any) {
      window.alert(`${action === 'freeze' ? 'Freeze' : 'Unfreeze'} failed: ${err.message}`);
    } finally {
      setBusyAccount(null);
    }
  };

  const handleResolveAlert = async (alertId: string) => {
    try {
      await client.updateAdminAlert(alertId, 'reviewed');
      setAlerts(alerts.filter((a) => a.alert_id !== alertId));
    } catch (err: any) {
      window.alert(`Update failed: ${err.message}`);
    }
  };

  const handleTabSwitch = (tab: AdminTab) => {
    setActiveTab(tab);
    if (tab === 'accounts') fetchAccounts();
    if (tab === 'alerts') fetchAlerts();
    if (tab === 'analytics') fetchAnalytics();
  };

  // Handle direct URL navigation /admin/case/:id
  const activeCase = cases.find((c) => c.case_id === activeCaseId) || null;

  const getRiskColor = (score: number) => {
    if (score >= 70) return '#ef4444';
    if (score >= 30) return '#f59e0b';
    return '#10b981';
  };

  const handleSelectCase = (id: string) => {
    navigate(`/admin/case/${id}`);
  };

  // ---- Analytics helpers ----
  const maxTier = (t: AnalyticsTrendPoint[]) => t.reduce((m, p) => Math.max(m, p.total), 1);
  const totalCasesAn = summary?.total_cases || 1;

  return (
    <div className="admin-layout">
      {/* ======================================================
          LEFT PANE: REAL-TIME CASE FEED (real backend)
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
          <button
            onClick={() => setShowSettings(true)}
            title="Backend API Settings"
            className="p-2 rounded-full hover:bg-gray-800 transition-colors"
            style={{ color: '#9ca3af' }}
          >
            <span className="material-symbols-outlined text-lg">settings</span>
          </button>
          <span className="text-[10px] font-mono bg-blue-900/50 text-blue-400 px-2 py-1 rounded border border-blue-700">
            {totalCases} CASES
          </span>
        </div>

        {/* Filter Row */}
        <div className="flex flex-col gap-2 pb-2 border-b border-gray-800 mb-3">
          <div className="flex gap-1.5 overflow-x-auto pb-1">
            {(['all', 'HIGH', 'MEDIUM', 'LOW'] as const).map((f) => (
              <button
                key={f}
                onClick={() => { setPage(1); setRiskTier(f); }}
                className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${
                  riskTier === f
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white'
                }`}
              >
                {f === 'all' ? 'ALL' : f}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <select
              value={statusFilter}
              onChange={(e) => { setPage(1); setStatusFilter(e.target.value); }}
              className="bg-gray-800 text-gray-300 text-[11px] rounded-lg px-2 py-1 border border-gray-700 flex-1 min-w-0"
            >
              <option value="all">All Statuses</option>
              <option value="frozen">Frozen</option>
              <option value="reported">Reported</option>
              <option value="approved">Approved</option>
              <option value="pending">Pending</option>
            </select>
            <select
              value={triggerFilter}
              onChange={(e) => { setPage(1); setTriggerFilter(e.target.value); }}
              className="bg-gray-800 text-gray-300 text-[11px] rounded-lg px-2 py-1 border border-gray-700 flex-1 min-w-0"
            >
              <option value="all">All Triggers</option>
              <option value="TRANSACTION">Transaction</option>
              <option value="CALL">Call</option>
              <option value="PHISHING">Phishing</option>
              <option value="TELEMETRY">Telemetry</option>
            </select>
          </div>
        </div>

        {/* Case Cards List */}
        <div className="flex flex-col gap-3 overflow-y-auto pr-1">
          {casesLoading && cases.length === 0 ? (
            <p className="text-xs text-gray-500 text-center py-8">Loading real cases from database...</p>
          ) : cases.length === 0 ? (
            <p className="text-xs text-gray-500 text-center py-8">No cases found matching filters.</p>
          ) : (
            cases.map((c) => {
              const isSelected = c.case_id === activeCaseId;
              const color = getRiskColor(c.risk_score);

              return (
                <div
                  key={c.case_id}
                  onClick={() => handleSelectCase(c.case_id)}
                  className={`case-card ${isSelected ? 'active' : ''}`}
                >
                  <div className="flex justify-between items-start mb-2">
                    <div className="min-w-0">
                      <span className="text-xs font-mono font-bold text-blue-400 break-all">
                        {c.case_id.length > 16 ? `${c.case_id.slice(0, 16)}…` : c.case_id}
                      </span>
                      <h4 className="text-sm font-bold text-white mt-0.5">
                        {c.user_id.length > 20 ? `${c.user_id.slice(0, 20)}…` : c.user_id}
                      </h4>
                    </div>

                    <span
                      className="px-2 py-0.5 rounded text-xs font-extrabold flex-shrink-0"
                      style={{
                        backgroundColor: `${color}20`,
                        color,
                        border: `1px solid ${color}40`
                      }}
                    >
                      SCORE {c.risk_score}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-xs text-gray-400 gap-2">
                    <span className="flex items-center gap-1 font-mono uppercase text-[10px] bg-gray-900 px-2 py-0.5 rounded">
                      <span className="material-symbols-outlined text-xs text-gray-400">
                        {c.trigger_type === 'CALL'
                          ? 'phone_in_talk'
                          : c.trigger_type === 'PHISHING'
                          ? 'image'
                          : 'sync_alt'}
                      </span>
                      {c.trigger_type}
                    </span>
                    <span
                      className="text-[10px] font-bold px-2 py-0.5 rounded"
                      style={{
                        backgroundColor: `${color}15`,
                        color,
                        border: `1px solid ${color}30`
                      }}
                    >
                      {c.risk_tier}
                    </span>
                  </div>
                  {c.verdict_summary && (
                    <p className="text-[11px] text-gray-500 mt-2 line-clamp-2">{c.verdict_summary}</p>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between pt-3 border-t border-gray-800 mt-2">
          <span className="text-[10px] text-gray-500 font-mono">{totalCases} total</span>
          <div className="flex items-center gap-2">
            <button
              disabled={page === 1}
              onClick={() => setPage(page - 1)}
              className="px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-gray-800 text-gray-400 hover:bg-gray-700 disabled:opacity-40"
            >
              Prev
            </button>
            <span className="text-[11px] text-gray-400">Page {page}</span>
            <button
              disabled={!hasNext}
              onClick={() => setPage(page + 1)}
              className="px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-gray-800 text-gray-400 hover:bg-gray-700 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      </aside>

      {/* ======================================================
          RIGHT PANE: TABBED INSPECTOR / ANALYTICS / ACCOUNTS / ALERTS
         ====================================================== */}
      <main className="admin-main">
        {/* Tab Switcher */}
        <div className="flex gap-2 mb-6 overflow-x-auto pb-1">
          {([
            { id: 'inspect', label: 'Case Inspector', icon: 'search' },
            { id: 'analytics', label: 'Analytics', icon: 'bar_chart' },
            { id: 'accounts', label: 'Accounts', icon: 'account_balance' },
            { id: 'alerts', label: 'Alerts', icon: 'notifications' },
          ] as const).map((tab) => (
            <button
              key={tab.id}
              onClick={() => handleTabSwitch(tab.id)}
              className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-1.5 ${
                activeTab === tab.id
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white'
              }`}
            >
              <span className="material-symbols-outlined text-sm">{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </div>

        {/* ============ TAB: CASE INSPECTOR ============ */}
        {activeTab === 'inspect' && (
          <div className="max-w-4xl mx-auto flex flex-col gap-6">
            {activeCase ? (
              <div className="neo-card bg-gray-900 border border-gray-800 text-white p-6 shadow-2xl">
                <div className="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-gray-800 pb-4 mb-6 gap-4">
                  <div>
                    <div className="flex items-center gap-3 flex-wrap">
                      <h1 className="text-2xl font-extrabold text-white">Case Inspection: {activeCase.case_id}</h1>
                      <span
                        className="risk-pill text-xs"
                        style={{
                          backgroundColor: `${getRiskColor(activeCase.risk_score)}20`,
                          color: getRiskColor(activeCase.risk_score),
                          border: `1px solid ${getRiskColor(activeCase.risk_score)}40`
                        }}
                      >
                        RISK {activeCase.risk_score} / 100
                      </span>
                    </div>
                    <p className="text-xs text-gray-400 mt-1">
                      User ID: <strong className="text-gray-200">{activeCase.user_id}</strong> • {activeCase.trigger_type} • {new Date(activeCase.created_at).toLocaleString()}
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-400 uppercase font-mono">Status:</span>
                    <span className="px-3 py-1 rounded-full text-xs font-bold bg-blue-950 text-blue-300 border border-blue-700">
                      {activeCase.status}
                    </span>
                  </div>
                </div>

                {detailLoading ? (
                  <p className="text-sm text-gray-400">Loading case breakdown...</p>
                ) : detail ? (
                  <>
                    {/* XAI Verdict Summary */}
                    <div className="p-4 rounded-xl bg-gray-950 border border-gray-800 mb-6">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-blue-400 mb-2">
                        Explainable AI (XAI) Synthesis
                      </h4>
                      <p className="text-sm font-semibold text-gray-200 mb-2">
                        {activeCase.verdict_summary || 'No verdict summary stored.'}
                      </p>
                      {detail.xai_report && typeof detail.xai_report === 'object' && (
                        <p className="text-xs text-gray-400 italic">
                          Action Taken: {detail.action_taken || '—'} • Unfreeze At:{' '}
                          {(detail.xai_report as any).unfreeze_at || '—'}
                        </p>
                      )}
                    </div>

                    {/* Detail Grid */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3 mb-6">
                      {[
                        ['Trigger', detail.trigger_type],
                        ['Risk Score', `${detail.risk_score}/100`],
                        ['Status', detail.status],
                        ['Action Taken', detail.action_taken],
                        ['User Label', detail.user_label],
                        ['Caller Number', detail.caller_number],
                        ['Phishing Source', detail.phishing_source],
                        ['Created', new Date(detail.created_at || '').toLocaleString()],
                      ]
                        .filter(([, v]) => v !== undefined && v !== null && v !== '')
                        .map(([k, v], i) => (
                          <div key={i} className="p-3 rounded-xl bg-gray-950 border border-gray-800">
                            <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">{k}</p>
                            <p className="text-xs font-mono text-gray-200 mt-1 break-all">{String(v)}</p>
                          </div>
                        ))}
                    </div>

                    {/* XAI Report JSON */}
                    {detail.xai_report && (
                      <div className="mb-6">
                        <h3 className="text-sm font-bold text-gray-300 uppercase tracking-wider mb-3">
                          Multi-Agent XAI Report
                        </h3>
                        <pre className="bg-gray-950 p-4 rounded-xl border border-gray-800 text-[11px] text-green-400 max-h-72 overflow-y-auto">
                          {JSON.stringify(detail.xai_report, null, 2)}
                        </pre>
                      </div>
                    )}

                    {/* Fraud Officer Action Bar */}
                    <div className="border-t border-gray-800 pt-6 flex flex-wrap gap-3">
                      <button
                        onClick={() => handleCaseAction(activeCase.case_id, 'freeze')}
                        disabled={busyCase === activeCase.case_id || activeCase.status === 'frozen'}
                        className="btn-danger py-3 text-xs disabled:opacity-50"
                      >
                        <span className="material-symbols-outlined text-sm">ac_unit</span>
                        Freeze Account (30 Min)
                      </button>

                      <button
                        onClick={() => handleCaseAction(activeCase.case_id, 'freeze')}
                        disabled={busyCase === activeCase.case_id || activeCase.status === 'frozen'}
                        className="btn-danger py-3 text-xs bg-red-800 hover:bg-red-900 disabled:opacity-50"
                      >
                        <span className="material-symbols-outlined text-sm">block</span>
                        Block Recipient NSRC
                      </button>

                      <button
                        onClick={() => handleCaseAction(activeCase.case_id, 'freeze')}
                        disabled={busyCase === activeCase.case_id || activeCase.status === 'frozen'}
                        className="btn-secondary py-3 text-xs bg-amber-900/40 text-amber-300 border border-amber-700 disabled:opacity-50"
                      >
                        <span className="material-symbols-outlined text-sm">flag</span>
                        Flag for Senior Review
                      </button>

                      <button
                        onClick={() => handleCaseAction(activeCase.case_id, 'unfreeze')}
                        disabled={busyCase === activeCase.case_id || activeCase.status !== 'frozen'}
                        className="btn-secondary py-3 text-xs bg-emerald-950 text-emerald-300 border border-emerald-700 ml-auto disabled:opacity-50"
                      >
                        <span className="material-symbols-outlined text-sm">check_circle</span>
                        Dismiss Alert & Allow
                      </button>
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-gray-400">Could not load details for case {activeCase.case_id}.</p>
                )}
              </div>
            ) : (
              <div className="text-center py-20 text-gray-500">Select a case from the left feed to inspect.</div>
            )}
          </div>
        )}

        {/* ============ TAB: ANALYTICS ============ */}
        {activeTab === 'analytics' && (
          <div className="max-w-4xl mx-auto neo-card bg-gray-900 border border-gray-800 text-white p-6 shadow-2xl">
            <div className="flex justify-between items-center border-b border-gray-800 pb-4 mb-6">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <span className="material-symbols-outlined text-blue-400">bar_chart</span>
                Fraud Operations Analytics
              </h3>
              <button
                onClick={fetchAnalytics}
                disabled={analyticsLoading}
                className="flex items-center gap-1 text-xs font-bold text-blue-400 hover:underline"
              >
                <span className="material-symbols-outlined text-sm" style={{ animation: analyticsLoading ? 'spin 1s linear infinite' : 'none' }}>
                  refresh
                </span>
                Refresh
              </button>
            </div>

            {analyticsLoading && !summary ? (
              <p className="text-sm text-gray-400">Loading analytics summary data...</p>
            ) : summary ? (
              <>
                {/* Metrics Grid */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                  <div className="p-4 rounded-2xl bg-gray-950 border border-gray-800">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Total Fraud Cases</p>
                    <p className="text-2xl font-extrabold text-white mt-1">{summary.total_cases}</p>
                  </div>
                  <div className="p-4 rounded-2xl bg-gray-950 border border-emerald-800/50">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Amount Protected</p>
                    <p className="text-2xl font-extrabold text-emerald-400 mt-1">
                      RM {Number(summary.total_amount_protected_myr ?? 0).toLocaleString()}
                    </p>
                  </div>
                  <div className="p-4 rounded-2xl bg-gray-950 border border-red-800/50">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Accounts Frozen</p>
                    <p className="text-2xl font-extrabold text-red-400 mt-1">{summary.accounts_frozen}</p>
                  </div>
                  <div className="p-4 rounded-2xl bg-gray-950 border border-gray-800">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Avg Risk Score</p>
                    <p className="text-2xl font-extrabold text-white mt-1">{summary.avg_risk_score}/100</p>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                  {/* Risk Tier Distribution */}
                  <div className="p-4 rounded-2xl bg-gray-950 border border-gray-800">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-gray-300 mb-3">Risk Tier Distribution</h4>
                    <div className="flex flex-col gap-2">
                      {(['HIGH', 'MEDIUM', 'LOW'] as const).map((tier) => {
                        const count = (summary.by_risk_tier as Record<string, number>)[tier] || 0;
                        const color = tier === 'HIGH' ? '#ef4444' : tier === 'MEDIUM' ? '#f59e0b' : '#10b981';
                        return (
                          <div key={tier} className="flex items-center gap-2 text-xs">
                            <span className="text-gray-400 w-28 flex-shrink-0">{tier} ({count})</span>
                            <div className="flex-1 h-2 rounded-full bg-gray-800 overflow-hidden">
                              <div
                                className="h-full rounded-full"
                                style={{ width: `${(count / totalCasesAn) * 100}%`, backgroundColor: color }}
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Worker Activation Counts */}
                  <div className="p-4 rounded-2xl bg-gray-950 border border-gray-800">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-gray-300 mb-3">Agent Activation Counts</h4>
                    {Object.keys(summary.worker_activation_counts || {}).length === 0 ? (
                      <p className="text-xs text-gray-500">No worker activations recorded yet.</p>
                    ) : (
                      <ul className="flex flex-col gap-1.5 text-xs text-gray-300">
                        {Object.entries(summary.worker_activation_counts || {}).map(([worker, count]) => (
                          <li key={worker} className="flex justify-between border-b border-gray-800/60 pb-1">
                            <strong>{worker.toUpperCase()} Worker</strong>
                            <span className="text-blue-400">{count} activations</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>

                {/* Trend Chart */}
                {trend.length > 0 && (
                  <div className="p-4 rounded-2xl bg-gray-950 border border-gray-800">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-gray-300 mb-3">Case Trend (Last {trend.length} Days)</h4>
                    <div className="flex items-end gap-1.5 h-32 overflow-x-auto pb-1">
                      {trend.map((point) => (
                        <div key={point.date} className="flex flex-col items-center gap-1 flex-shrink-0" title={`${point.date}: ${point.total} cases`}>
                          <div className="flex items-end gap-0.5 h-24">
                            <div className="w-2 rounded-t" style={{ height: `${(point.HIGH / maxTier(trend)) * 100}%`, backgroundColor: '#ef4444' }} />
                            <div className="w-2 rounded-t" style={{ height: `${(point.MEDIUM / maxTier(trend)) * 100}%`, backgroundColor: '#f59e0b' }} />
                            <div className="w-2 rounded-t" style={{ height: `${(point.LOW / maxTier(trend)) * 100}%`, backgroundColor: '#10b981' }} />
                          </div>
                          <span className="text-[9px] text-gray-500">{point.date.slice(5)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <p className="text-sm text-gray-400">No analytics data available.</p>
            )}
          </div>
        )}

        {/* ============ TAB: ACCOUNTS ============ */}
        {activeTab === 'accounts' && (
          <div className="max-w-4xl mx-auto neo-card bg-gray-900 border border-gray-800 text-white p-6 shadow-2xl">
            <div className="flex justify-between items-center border-b border-gray-800 pb-4 mb-6">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <span className="material-symbols-outlined text-blue-400">account_balance</span>
                Account Freeze & Unfreeze Controls
              </h3>
              <button
                onClick={fetchAccounts}
                disabled={accountsLoading}
                className="flex items-center gap-1 text-xs font-bold text-blue-400 hover:underline"
              >
                <span className="material-symbols-outlined text-sm" style={{ animation: accountsLoading ? 'spin 1s linear infinite' : 'none' }}>
                  refresh
                </span>
                Refresh
              </button>
            </div>

            {actionResult && (
              <div
                className="p-4 rounded-2xl border mb-6 text-xs"
                style={{
                  backgroundColor: actionResult.status === 'frozen' ? 'rgba(239,68,68,0.1)' : 'rgba(16,185,129,0.1)',
                  borderColor: actionResult.status === 'frozen' ? '#ef4444' : '#10b981',
                }}
              >
                <p className="font-bold text-sm mb-2" style={{ color: actionResult.status === 'frozen' ? '#f87171' : '#34d399' }}>
                  {actionResult.status === 'frozen' ? '🔒' : '✅'} Account {actionResult.account_number} is now {actionResult.status.toUpperCase()}!
                </p>
                <div className="flex flex-col gap-1 text-gray-400">
                  <span><strong>Reason:</strong> {actionResult.reason}</span>
                  <span><strong>Updated By:</strong> {actionResult.frozen_by || actionResult.unfrozen_by || 'admin'}</span>
                  <span><strong>Timestamp:</strong> {new Date(actionResult.frozen_at || actionResult.unfrozen_at || '').toLocaleString()}</span>
                </div>
              </div>
            )}

            {accountsLoading && accounts.length === 0 ? (
              <p className="text-sm text-gray-400">Loading real accounts from database...</p>
            ) : accounts.length === 0 ? (
              <p className="text-sm text-gray-400">No accounts found in database.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-gray-500 uppercase tracking-wider text-[10px] border-b border-gray-800">
                      <th className="py-2 pr-3">Account Number</th>
                      <th className="py-2 pr-3">Type</th>
                      <th className="py-2 pr-3">Balance (RM)</th>
                      <th className="py-2 pr-3">Status</th>
                      <th className="py-2 pr-3">Frozen By</th>
                      <th className="py-2 pr-3">Frozen At</th>
                      <th className="py-2">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {accounts.map((acc, idx) => (
                      <tr key={`${acc.account_number}-${idx}`} className="border-b border-gray-800/60">
                        <td className="py-2.5 pr-3 font-mono text-blue-400">{acc.account_number}</td>
                        <td className="py-2.5 pr-3 text-gray-300">{acc.account_type || 'savings'}</td>
                        <td className="py-2.5 pr-3 text-gray-300">{Number(acc.balance_myr ?? 0).toLocaleString()}</td>
                        <td className="py-2.5 pr-3">
                          <span
                            className="px-2 py-0.5 rounded-full text-[10px] font-bold"
                            style={{
                              color: acc.status === 'frozen' ? '#f87171' : '#34d399',
                              backgroundColor: acc.status === 'frozen' ? 'rgba(239,68,68,0.15)' : 'rgba(16,185,129,0.15)',
                              border: `1px solid ${acc.status === 'frozen' ? '#ef4444' : '#10b981'}`,
                            }}
                          >
                            {acc.status}
                          </span>
                        </td>
                        <td className="py-2.5 pr-3 text-gray-400">{acc.frozen_by || '—'}</td>
                        <td className="py-2.5 pr-3 text-gray-400">{acc.frozen_at ? new Date(acc.frozen_at).toLocaleString() : '—'}</td>
                        <td className="py-2.5">
                          {acc.status === 'frozen' ? (
                            <button
                              onClick={() => handleAccountAction(acc.account_number, 'unfreeze')}
                              disabled={busyAccount === acc.account_number}
                              className="px-3 py-1.5 rounded-lg text-[11px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-700 hover:bg-emerald-900 disabled:opacity-50"
                            >
                              Unfreeze
                            </button>
                          ) : (
                            <button
                              onClick={() => handleAccountAction(acc.account_number, 'freeze')}
                              disabled={busyAccount === acc.account_number}
                              className="px-3 py-1.5 rounded-lg text-[11px] font-bold bg-red-950 text-red-300 border border-red-700 hover:bg-red-900 disabled:opacity-50"
                            >
                              Freeze
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ============ TAB: ALERTS ============ */}
        {activeTab === 'alerts' && (
          <div className="max-w-4xl mx-auto neo-card bg-gray-900 border border-gray-800 text-white p-6 shadow-2xl">
            <div className="flex justify-between items-center border-b border-gray-800 pb-4 mb-6">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <span className="material-symbols-outlined text-red-400">notifications</span>
                Real-Time Admin Operations Alerts Queue
              </h3>
              <button
                onClick={fetchAlerts}
                disabled={alertsLoading}
                className="flex items-center gap-1 text-xs font-bold text-blue-400 hover:underline"
              >
                <span className="material-symbols-outlined text-sm" style={{ animation: alertsLoading ? 'spin 1s linear infinite' : 'none' }}>
                  refresh
                </span>
                Refresh
              </button>
            </div>

            {alertsLoading && alerts.length === 0 ? (
              <p className="text-sm text-gray-400">Loading alerts...</p>
            ) : alerts.length === 0 ? (
              <p className="text-sm text-gray-400">No unreviewed alerts in queue.</p>
            ) : (
              <div className="flex flex-col gap-3">
                {alerts.map((alert) => (
                  <div key={alert.alert_id} className="p-4 rounded-2xl bg-gray-950 border border-gray-800">
                    <div className="flex justify-between items-center gap-2 mb-1">
                      <strong className="text-sm text-red-400">ALERT: {alert.alert_type}</strong>
                      <span className="text-xs font-bold text-amber-400 flex-shrink-0">Risk Score: {alert.risk_score}/100</span>
                    </div>
                    <p className="text-xs text-gray-300 mb-2">{alert.verdict_summary}</p>
                    <div className="flex flex-wrap items-center gap-3 text-[11px] text-gray-500 font-mono">
                      <span>Case ID: {alert.case_id}</span>
                      <span>Time: {new Date(alert.created_at).toLocaleTimeString()}</span>
                    </div>
                    <div className="mt-3">
                      {alert.status === 'pending' ? (
                        <button
                          onClick={() => handleResolveAlert(alert.alert_id)}
                          className="px-3 py-1.5 rounded-lg text-[11px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-700 hover:bg-emerald-900"
                        >
                          ✓ Mark Reviewed
                        </button>
                      ) : (
                        <span className="text-[11px] font-bold text-emerald-400">✓ Reviewed</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </main>

      {/* Backend Settings Modal */}
      <SettingsModal
        open={showSettings}
        config={config}
        onSave={(newConfig) => setConfig(newConfig)}
        onClose={() => setShowSettings(false)}
      />
    </div>
  );
};
