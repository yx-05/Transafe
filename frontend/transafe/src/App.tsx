import React from 'react';
import { BrowserRouter as Router, Routes, Route, useLocation, Navigate } from 'react-router-dom';
import { SimulationProvider } from './context/SimulationContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import { UserNavigation } from './components/UserNavigation';

import { HomePage } from './pages/HomePage';
import { TransferPage } from './pages/TransferPage';
import { ScanPage } from './pages/ScanPage';
import { CallActivePage } from './pages/CallActivePage';
import { ProfilePage } from './pages/ProfilePage';
import { SignInPage } from './pages/SignInPage';
import { AdminDashboardPage } from './pages/AdminDashboardPage';
import { ScammerSimulatorPage } from './pages/ScammerSimulatorPage';

/** Wrapper that redirects unauthenticated users to /login for protected routes. */
const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
};

const AppContent: React.FC = () => {
  const location = useLocation();
  const isUserApp = ['/', '/transfer', '/scan', '/call-active', '/profile'].includes(location.pathname);

  return (
    <div className="min-h-screen flex flex-col bg-background">
      <main className="flex-1 relative">
        <Routes>
          {/* Public routes */}
          <Route path="/login" element={<SignInPage />} />
          <Route path="/signin" element={<SignInPage />} />

          {/* Protected user routes */}
          <Route path="/" element={<ProtectedRoute><HomePage /></ProtectedRoute>} />
          <Route path="/transfer" element={<ProtectedRoute><TransferPage /></ProtectedRoute>} />
          <Route path="/scan" element={<ProtectedRoute><ScanPage /></ProtectedRoute>} />
          <Route path="/call-active" element={<ProtectedRoute><CallActivePage /></ProtectedRoute>} />
          <Route path="/profile" element={<ProtectedRoute><ProfilePage /></ProtectedRoute>} />

          {/* Admin & simulator routes (no auth guard for demo) */}
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
    <AuthProvider>
      <SimulationProvider>
        <Router>
          <AppContent />
        </Router>
      </SimulationProvider>
    </AuthProvider>
  );
}
