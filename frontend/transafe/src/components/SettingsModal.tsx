import React, { useState } from 'react';
import type { BackendConfig } from '../types/api';

interface SettingsModalProps {
  open: boolean;
  config: BackendConfig;
  onSave: (config: BackendConfig) => void;
  onClose: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({ open, config, onSave, onClose }) => {
  const [baseUrl, setBaseUrl] = useState(config.baseUrl);
  const [apiKey, setApiKey] = useState(config.apiKey);
  const [adminKey, setAdminKey] = useState(config.adminKey);
  const [saved, setSaved] = useState(false);

  if (!open) return null;

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({ baseUrl, apiKey, adminKey });
    setSaved(true);
    setTimeout(() => {
      setSaved(false);
      onClose();
    }, 900);
  };

  return (
    <div
      className="modal-overlay"
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
        padding: '16px',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: '#ffffff',
          borderRadius: '24px',
          padding: '28px',
          width: '100%',
          maxWidth: '460px',
          boxShadow: '0 24px 60px rgba(0,0,0,0.2)',
          fontFamily: 'Inter, sans-serif',
          color: '#191c1d',
          maxHeight: '90vh',
          overflowY: 'auto',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <h3 style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '18px', fontWeight: 700, margin: 0 }}>
            <span className="material-symbols-outlined" style={{ color: '#0050cb', fontSize: '22px' }}>settings</span>
            Backend API &amp; Key Credentials
          </h3>
          <button
            onClick={onClose}
            style={{ color: '#9ca3af', background: 'none', border: 'none', cursor: 'pointer', padding: '4px', fontSize: '18px' }}
            aria-label="Close settings"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div className="form-group" style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '12px', fontWeight: 600, color: '#374151' }}>
              <span className="material-symbols-outlined" style={{ fontSize: '14px', verticalAlign: 'text-bottom', marginRight: '4px' }}>dns</span>
              Backend Base URL
            </label>
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="http://localhost:8000"
              required
              className="form-input"
              style={{ width: '100%', padding: '12px 14px', borderRadius: '14px', border: '1px solid #d1d5db', fontSize: '13px', fontFamily: 'monospace' }}
            />
          </div>

          <div className="form-group" style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '12px', fontWeight: 600, color: '#374151' }}>
              <span className="material-symbols-outlined" style={{ fontSize: '14px', verticalAlign: 'text-bottom', marginRight: '4px' }}>key</span>
              User API Key (X-API-Key)
            </label>
            <input
              type="text"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="transafe-hackathon-key-2026"
              required
              className="form-input"
              style={{ width: '100%', padding: '12px 14px', borderRadius: '14px', border: '1px solid #d1d5db', fontSize: '13px', fontFamily: 'monospace' }}
            />
          </div>

          <div className="form-group" style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '12px', fontWeight: 600, color: '#374151' }}>
              <span className="material-symbols-outlined" style={{ fontSize: '14px', verticalAlign: 'text-bottom', marginRight: '4px' }}>admin_panel_settings</span>
              Admin API Key (X-Admin-Key)
            </label>
            <input
              type="text"
              value={adminKey}
              onChange={(e) => setAdminKey(e.target.value)}
              placeholder="transafe-admin-key-2026"
              required
              className="form-input"
              style={{ width: '100%', padding: '12px 14px', borderRadius: '14px', border: '1px solid #d1d5db', fontSize: '13px', fontFamily: 'monospace' }}
            />
          </div>

          {saved && (
            <div style={{ padding: '10px 14px', borderRadius: '12px', backgroundColor: '#ecfdf5', border: '1px solid #a7f3d0', fontSize: '12px', fontWeight: 600, color: '#047857' }}>
              ✓ Settings saved — reconnecting to backend...
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '8px' }}>
            <button
              type="button"
              onClick={onClose}
              style={{ padding: '12px 20px', borderRadius: '16px', border: '1px solid #d1d5db', backgroundColor: '#ffffff', color: '#374151', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}
            >
              Cancel
            </button>
            <button
              type="submit"
              style={{ padding: '12px 20px', borderRadius: '16px', border: 'none', backgroundColor: '#0066ff', color: '#ffffff', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}
            >
              Save Settings
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
