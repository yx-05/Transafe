import { useState } from 'react';
import type { BackendConfig, XaiReport } from './types/api';
import { Navbar } from './components/Navbar';
import { XaiReportModal } from './components/XaiReportModal';
import { BiometricModal } from './components/BiometricModal';

// User Page Cards
import { TransactionCard } from './components/user/TransactionCard';
import { TelemetryCard } from './components/user/TelemetryCard';
import { PhishingCard } from './components/user/PhishingCard';
import { FraudReportCard } from './components/user/FraudReportCard';
import { CallCard } from './components/user/CallCard';
import { RecentCasesCard } from './components/user/RecentCasesCard';

// Scammer Page Cards
import { ScammerCallSimulator } from './components/scammer/ScammerCallSimulator';
import { PhishingGenerator } from './components/scammer/PhishingGenerator';
import { CoercionSimulator } from './components/scammer/CoercionSimulator';

// Admin Page Cards
import { CaseListCard } from './components/admin/CaseListCard';
import { CaseDetailCard } from './components/admin/CaseDetailCard';
import { AccountControlCard } from './components/admin/AccountControlCard';
import { AnalyticsCard } from './components/admin/AnalyticsCard';
import { AlertsCard } from './components/admin/AlertsCard';

import { TranSafeApiClient } from './services/api';
import './App.css';

function App() {
  const [config, setConfig] = useState<BackendConfig>({
    baseUrl: 'http://localhost:8000',
    apiKey: 'transafe-hackathon-key-2026',
    adminKey: 'transafe-admin-key-2026',
  });

  const [activeTab, setActiveTab] = useState<'user' | 'scammer' | 'admin'>('user');
  const [userId, setUserId] = useState('usr-123');

  // Modals
  const [activeXaiReport, setActiveXaiReport] = useState<XaiReport | null>(null);
  const [biometricChallenge, setBiometricChallenge] = useState<{
    sessionId: string;
    txId: string;
  } | null>(null);

  // Admin selected case
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);

  const handleBiometricSubmit = async (result: 'PASSED' | 'FAILED' | 'DECLINED') => {
    if (!biometricChallenge) return;
    const client = new TranSafeApiClient(config);
    await client.submitBiometricResult({
      user_id: userId,
      session_id: biometricChallenge.sessionId,
      transaction_id: biometricChallenge.txId,
      biometric_result: result,
    });
    setBiometricChallenge(null);
  };

  return (
    <div className="app-container">
      <Navbar
        config={config}
        onUpdateConfig={setConfig}
        activeTab={activeTab}
        onSelectTab={setActiveTab}
      />

      <main className="main-content">
        {/* USER PAGE */}
        {activeTab === 'user' && (
          <div className="page-section">
            <div className="section-header">
              <h2>🏦 Bank Customer Test Interface</h2>
              <div className="user-id-selector">
                <label>Active Customer User ID:</label>
                <input
                  type="text"
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                />
              </div>
            </div>

            <div className="cards-grid">
              <TransactionCard
                config={config}
                userId={userId}
                onOpenXaiReport={setActiveXaiReport}
                onTriggerBiometrics={(sessionId, txId) =>
                  setBiometricChallenge({ sessionId, txId })
                }
              />

              <CallCard config={config} userId={userId} />

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

              <FraudReportCard config={config} userId={userId} />

              <RecentCasesCard config={config} userId={userId} />
            </div>
          </div>
        )}

        {/* SCAMMER PAGE */}
        {activeTab === 'scammer' && (
          <div className="page-section">
            <div className="section-header">
              <h2>💀 Scammer Attack Simulator</h2>
              <p>Simulate scam calls, malicious links, and coercion attacks to test backend agent interception.</p>
            </div>

            <div className="cards-grid">
              <ScammerCallSimulator config={config} victimUserId={userId} />
              <CoercionSimulator config={config} victimUserId={userId} />
              <PhishingGenerator config={config} victimUserId={userId} />
            </div>
          </div>
        )}

        {/* ADMIN PAGE */}
        {activeTab === 'admin' && (
          <div className="page-section">
            <div className="section-header">
              <h2>📊 Bank Fraud Operations Dashboard</h2>
              <p>Monitor cases, review XAI evidence breakdown, freeze accounts, and analyze scam trends.</p>
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
          transactionId={biometricChallenge.txId}
          onSubmitResult={handleBiometricSubmit}
          onClose={() => setBiometricChallenge(null)}
        />
      )}
    </div>
  );
}

export default App;
