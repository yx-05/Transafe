import React, { useState } from 'react';
import type { BackendConfig } from '../types/api';
import { Shield, User, Skull, LayoutDashboard, Settings, Server, Key } from 'lucide-react';

interface NavbarProps {
  config: BackendConfig;
  onUpdateConfig: (config: BackendConfig) => void;
  activeTab: 'user' | 'scammer' | 'admin';
  onSelectTab: (tab: 'user' | 'scammer' | 'admin') => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  config,
  onUpdateConfig,
  activeTab,
  onSelectTab,
}) => {
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [baseUrl, setBaseUrl] = useState(config.baseUrl);
  const [apiKey, setApiKey] = useState(config.apiKey);
  const [adminKey, setAdminKey] = useState(config.adminKey);

  const handleSaveConfig = (e: React.FormEvent) => {
    e.preventDefault();
    onUpdateConfig({ baseUrl, apiKey, adminKey });
    setShowConfigModal(false);
  };

  return (
    <header className="app-header">
      <div className="header-brand">
        <Shield className="brand-icon" size={28} />
        <div>
          <h1 className="brand-title">TranSafe Test Workbench</h1>
          <p className="brand-subtitle">Real-Time Multi-Agent Scam Defense Platform</p>
        </div>
      </div>

      <nav className="tab-navigation">
        <button
          className={`tab-btn tab-customer ${activeTab === 'user' ? 'active' : ''}`}
          onClick={() => onSelectTab('user')}
        >
          <User size={18} />
          <span>Bank Customer</span>
        </button>

        <button
          className={`tab-btn tab-scammer ${activeTab === 'scammer' ? 'active' : ''}`}
          onClick={() => onSelectTab('scammer')}
        >
          <Skull size={18} />
          <span>Scammer Simulator</span>
        </button>

        <button
          className={`tab-btn tab-admin ${activeTab === 'admin' ? 'active' : ''}`}
          onClick={() => onSelectTab('admin')}
        >
          <LayoutDashboard size={18} />
          <span>Admin Operations</span>
        </button>
      </nav>

      <div className="header-actions">
        <button
          className="config-btn"
          onClick={() => setShowConfigModal(true)}
          title="Backend API Settings"
        >
          <Settings size={18} />
          <span>Settings</span>
        </button>
      </div>

      {showConfigModal && (
        <div className="modal-overlay" onClick={() => setShowConfigModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2><Server size={20} /> Backend API & Key Credentials</h2>
              <button className="close-btn" onClick={() => setShowConfigModal(false)}>×</button>
            </div>
            <form onSubmit={handleSaveConfig} className="config-form">
              <div className="form-group">
                <label><Server size={14} /> Backend Base URL</label>
                <input
                  type="text"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="http://localhost:8000"
                  required
                />
              </div>

              <div className="form-group">
                <label><Key size={14} /> User API Key (X-API-Key)</label>
                <input
                  type="text"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="transafe-hackathon-key-2026"
                  required
                />
              </div>

              <div className="form-group">
                <label><Key size={14} /> Admin API Key (X-Admin-Key)</label>
                <input
                  type="text"
                  value={adminKey}
                  onChange={(e) => setAdminKey(e.target.value)}
                  placeholder="transafe-admin-key-2026"
                  required
                />
              </div>

              <div className="modal-footer">
                <button type="button" className="btn-secondary" onClick={() => setShowConfigModal(false)}>Cancel</button>
                <button type="submit" className="btn-primary">Save Settings</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </header>
  );
};
