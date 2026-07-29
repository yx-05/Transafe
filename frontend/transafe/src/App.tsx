import React from 'react';
import { BrowserRouter as Router, Routes, Route, useLocation } from 'react-router-dom';
import { SimulationProvider } from './context/SimulationContext';
import { UserNavigation } from './components/UserNavigation';

import { HomePage } from './pages/HomePage';
import { TransferPage } from './pages/TransferPage';
import { ScanPage } from './pages/ScanPage';
import { CallActivePage } from './pages/CallActivePage';
import { AdminDashboardPage } from './pages/AdminDashboardPage';
import { ScammerSimulatorPage } from './pages/ScammerSimulatorPage';

const AppContent: React.FC = () => {
  const location = useLocation();
  const isUserApp = ['/', '/transfer', '/scan', '/call-active'].includes(location.pathname);

  return (
    <div className="min-h-screen flex flex-col bg-background">
      <main className="flex-1 relative">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/transfer" element={<TransferPage />} />
          <Route path="/scan" element={<ScanPage />} />
          <Route path="/call-active" element={<CallActivePage />} />
          <Route path="/admin" element={<AdminDashboardPage />} />
          <Route path="/admin/case/:id" element={<AdminDashboardPage />} />
          <Route path="/scammer" element={<ScammerSimulatorPage />} />
        </Routes>

        {isUserApp && <UserNavigation />}
      </main>
    </div>
  );
};

export default function App() {
  return (
    <SimulationProvider>
      <Router>
        <AppContent />
      </Router>
    </SimulationProvider>
  );
}
