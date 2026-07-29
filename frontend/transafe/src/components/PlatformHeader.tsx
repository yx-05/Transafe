import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useSimulation } from '../context/SimulationContext';

export const PlatformHeader: React.FC = () => {
  const { isCallRinging, isCallConnected, triggerIncomingCall } = useSimulation();
  const location = useLocation();

  return (
    <header className="platform-nav-bar">
      <div className="flex items-center gap-4">
        <NavLink to="/" className="platform-logo">
          <span className="material-symbols-outlined text-primary text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>
            shield_lock
          </span>
          <span>TranSafe</span>
          <span className="badge-ai">Multi-Agent AI</span>
        </NavLink>
      </div>

      <nav className="platform-links">
        <NavLink
          to="/"
          className={({ isActive }) =>
            `platform-tab ${isActive || ['/transfer', '/scan', '/call-active'].includes(location.pathname) ? 'active' : ''}`
          }
        >
          <span className="material-symbols-outlined text-lg">smartphone</span>
          <span>User App</span>
        </NavLink>

        <NavLink
          to="/admin"
          className={({ isActive }) => `platform-tab ${isActive ? 'active' : ''}`}
        >
          <span className="material-symbols-outlined text-lg">admin_panel_settings</span>
          <span>Admin Ops</span>
        </NavLink>

        <NavLink
          to="/scammer"
          className={({ isActive }) => `platform-tab ${isActive ? 'active' : ''}`}
        >
          <span className="material-symbols-outlined text-lg">phone_in_talk</span>
          <span>Scammer Dialer</span>
        </NavLink>
      </nav>

      <div className="flex items-center gap-3">
        {/* Call Trigger Quick Shortcut */}
        {!isCallConnected && !isCallRinging && (
          <button
            onClick={() => triggerIncomingCall()}
            className="btn-danger py-1.5 px-3 text-xs"
            title="Simulate incoming scam call"
          >
            <span className="material-symbols-outlined text-sm">ring_volume</span>
            Simulate Call
          </button>
        )}
      </div>
    </header>
  );
};
