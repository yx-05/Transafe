import { useState, useEffect } from 'react';
import type { BackendConfig, XaiReport } from './types/api';
import { Navbar } from './components/Navbar';
import { XaiReportModal } from './components/XaiReportModal';
import { BiometricModal } from './components/BiometricModal';
import { Shield, Skull, LayoutDashboard, User, AlertOctagon } from 'lucide-react';

// User Page Cards
import { TransactionCard } from './components/user/TransactionCard';
import { BiometricRegistrationCard } from './components/user/BiometricRegistrationCard';
import { TelemetryCard } from './components/user/TelemetryCard';
import { PhishingCard } from './components/user/PhishingCard';
import { CallCard } from './components/user/CallCard';
import { StepByStepUserCall } from './components/user/StepByStepUserCall';
import { RecentCasesCard } from './components/user/RecentCasesCard';

// Scammer Page Cards
import { ScammerCallSimulator } from './components/scammer/ScammerCallSimulator';
import { StepByStepScammerCall } from './components/scammer/StepByStepScammerCall';

// Admin Page Cards
import { CaseListCard } from './components/admin/CaseListCard';
import { CaseDetailCard } from './components/admin/CaseDetailCard';
import { AccountControlCard } from './components/admin/AccountControlCard';
import { AnalyticsCard } from './components/admin/AnalyticsCard';
import { AlertsCard } from './components/admin/AlertsCard';

import { TranSafeApiClient } from './services/api';
import './App.css';

function App() {
  const getInitialBaseUrl = () => {
    if (typeof window !== 'undefined' && window.location) {
      const host = window.location.hostname;
      // If running through cloudflare/localtunnel tunnel, use origin so Vite proxy forwards requests
      if (host.includes('trycloudflare') || host.includes('loca.lt') || host.includes('ngrok')) {
        return window.location.origin;
      }
      // Direct local connection on laptop or Wi-Fi IP
      const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
      return `${protocol}//${host || 'localhost'}:8000`;
    }
    return 'http://localhost:8000';
  };

  const [config, setConfig] = useState<BackendConfig>({
    baseUrl: getInitialBaseUrl(),
    apiKey: 'transafe-hackathon-key-2026',
    adminKey: 'transafe-admin-key-2026',
  });

  const [activeTab, setActiveTab] = useState<'user' | 'scammer' | 'admin'>('user');
  const [userId, setUserId] = useState('619ebd02-82fc-4a13-81f6-ff575c20278d'); // Seeded user (Bobby Ayala)

  // Modals
  const [activeXaiReport, setActiveXaiReport] = useState<XaiReport | null>(null);
  const [biometricChallenge, setBiometricChallenge] = useState<{
    sessionId: string;
    txId: string;
  } | null>(null);

  // Admin selected case
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);

  // URL Hash Sync for standalone pages (#/customer, #/scammer, #/admin)
  useEffect(() => {
    const syncHashToTab = () => {
      const hash = window.location.hash.replace(/^#\/?/, '');
      if (hash === 'scammer') {
        setActiveTab('scammer');
      } else if (hash === 'admin') {
        setActiveTab('admin');
      } else if (hash === 'customer' || hash === 'user') {
        setActiveTab('user');
      } else {
        window.location.hash = '#/customer';
      }
    };

    syncHashToTab();
    window.addEventListener('hashchange', syncHashToTab);
    return () => window.removeEventListener('hashchange', syncHashToTab);
  }, []);

  const handleSelectTab = (tab: 'user' | 'scammer' | 'admin') => {
    setActiveTab(tab);
    if (tab === 'scammer') window.location.hash = '#/scammer';
    else if (tab === 'admin') window.location.hash = '#/admin';
    else window.location.hash = '#/customer';
  };

  const handleBiometricSubmit = async (result: 'PASSED' | 'FAILED' | 'DECLINED') => {
    if (!biometricChallenge) return;
    const client = new TranSafeApiClient(config);
    try {
      const res = await client.submitBiometricResult({
        user_id: userId,
        session_id: biometricChallenge.sessionId,
        transaction_id: biometricChallenge.txId,
        biometric_result: result,
        method: 'TOUCH_ID',
        attempted_at: new Date().toISOString(),
      });
      alert(res.message);
    } catch (e: any) {
      alert(`Biometric submission error: ${e.message}`);
    }
    setBiometricChallenge(null);
  };

  return (
    <div className="app-container">
      <Navbar
        config={config}
        onUpdateConfig={setConfig}
        activeTab={activeTab}
        onSelectTab={handleSelectTab}
      />

      <main className="main-content">
        {/* BANK CUSTOMER PORTAL PAGE (#/customer) */}
        {activeTab === 'user' && (
          <div className="page-section page-customer">
            <div className="page-banner page-banner-customer">
              <div className="page-banner-title">
                <User size={24} className="text-blue" />
                <div>
                  <h2>🏦 Bank Customer Test Portal</h2>
                  <p>Continuous telemetry tracking, WebRTC call copilot, and multi-signal fraud interception.</p>
                </div>
              </div>
              <div className="user-id-selector">
                <span className="page-banner-badge badge-customer">
                  <Shield size={14} /> ACTIVE CUSTOMER SESSION
                </span>
                <label>User ID:</label>
                <input
                  type="text"
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                />
              </div>
            </div>

            <div className="cards-grid">
              <BiometricRegistrationCard userId={userId} />

              <TransactionCard
                config={config}
                userId={userId}
                onOpenXaiReport={setActiveXaiReport}
                onTriggerBiometrics={(sessionId, txId) =>
                  setBiometricChallenge({ sessionId, txId })
                }
              />

              <StepByStepUserCall config={config} userId={userId} />

              {/* Legacy CallCard disabled to prevent duplicate audio stream conflicts */}
              {/* <CallCard config={config} userId={userId} onOpenXaiReport={setActiveXaiReport} /> */}

              <PhishingCard
                config={config}
                userId={userId}
                onOpenXaiReport={setActiveXaiReport}
              />

              <TelemetryCard
                config={config}
                userId={userId}
                onOpenXaiReport={setActiveXaiReport}
              />

              <RecentCasesCard config={config} userId={userId} />
            </div>
          </div>
        )}

        {/* SCAMMER ATTACK SIMULATOR WORKBENCH PAGE (#/scammer) */}
        {activeTab === 'scammer' && (
          <div className="page-section page-scammer">
            <div className="page-banner page-banner-scammer">
              <div className="page-banner-title">
                <Skull size={24} className="text-red" />
                <div>
                  <h2>💀 Scammer Threat Attack Simulator Workbench</h2>
                  <p>Simulate scam calls, malicious phishing links, and financial coercion attacks to test agent interception.</p>
                </div>
              </div>
              <span className="page-banner-badge badge-scammer">
                <AlertOctagon size={14} /> ATTACK SIMULATOR MODE
              </span>
            </div>

            <div className="cards-grid">
              <StepByStepScammerCall config={config} victimUserId={userId} />
              {/* Legacy ScammerCallSimulator disabled to prevent duplicate audio stream conflicts */}
              {/* <ScammerCallSimulator config={config} victimUserId={userId} /> */}
            </div>
          </div>
        )}

        {/* ADMIN OPERATIONS DASHBOARD PAGE (#/admin) */}
        {activeTab === 'admin' && (
          <div className="page-section page-admin">
            <div className="page-banner page-banner-admin">
              <div className="page-banner-title">
                <LayoutDashboard size={24} className="text-purple" />
                <div>
                  <h2>📊 Bank Fraud Operations & Analyst Workbench</h2>
                  <p>Monitor cases in real-time, review XAI evidence breakdowns, manage account freezes, and track scam trends.</p>
                </div>
              </div>
              <span className="page-banner-badge badge-admin">
                <Shield size={14} /> SECURE OPS WORKBENCH
              </span>
            </div>

            <div className="admin-grid">
              <AlertsCard config={config} />
              <AnalyticsCard config={config} />
              <AccountControlCard config={config} />
              <CaseListCard config={config} onSelectCase={setSelectedCaseId} />
              <CaseDetailCard
                config={config}
                caseId={selectedCaseId}
                onClear={() => setSelectedCaseId(null)}
              />
            </div>
          </div>
        )}
      </main>

      {/* XAI Report Modal */}
      <XaiReportModal
        report={activeXaiReport}
        onClose={() => setActiveXaiReport(null)}
      />

      {/* Biometric Challenge Modal */}
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
}

export default App;
