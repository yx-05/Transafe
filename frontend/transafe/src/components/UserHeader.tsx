import React, { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApi } from '../context/ApiContext';
import { SettingsModal } from './SettingsModal';

interface UserHeaderProps {
  title?: string;
  showBack?: boolean;
}

export const UserHeader: React.FC<UserHeaderProps> = ({ title = 'TranSafe', showBack = false }) => {
  const navigate = useNavigate();
  const { config, setConfig } = useApi();
  const [showSettings, setShowSettings] = useState(false);

  return (
    <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', padding: '24px 0', position: 'relative', zIndex: 20, color: '#ffffff' }}>
      {/* App Title & Optional Back Button */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: '1 1 auto', minWidth: 0, overflow: 'hidden' }}>
        {showBack && (
          <button
            onClick={() => navigate('/')}
            style={{ color: '#ffffff', padding: '6px', borderRadius: '9999px', border: 'none', background: 'none', cursor: 'pointer', transition: 'background-color 0.15s', flexShrink: 0 }}
            title="Go Back"
            onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.1)')}
            onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}
          >
            <span className="material-symbols-outlined" style={{ fontSize: '24px' }}>arrow_back</span>
          </button>
        )}
        
        <h1
          onClick={() => navigate('/')}
          className="tran-safe-title"
          style={{ fontWeight: 700, color: '#ffffff', letterSpacing: '-0.01em', cursor: 'pointer', margin: 0, overflowWrap: 'break-word', wordBreak: 'break-word', minWidth: 0 }}
        >
          {title}
        </h1>
      </div>

      {/* Header Action Buttons */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', paddingRight: '4px', flexShrink: 0 }}>
        {/* Settings Gear */}
        <button
          onClick={() => {
            setShowSettings(true);
          }}
          style={{ color: '#ffffff', padding: '10px', borderRadius: '9999px', border: 'none', background: 'none', cursor: 'pointer', transition: 'background-color 0.15s' }}
          title="Backend API Settings"
          onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.1)')}
          onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}
        >
          <span className="material-symbols-outlined" style={{ fontSize: '28px', fontVariationSettings: "'FILL' 0" }}>
            settings
          </span>
        </button>



        {/* Profile Button */}
        <button
          onClick={() => navigate('/profile')}
          style={{ color: '#ffffff', display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 12px', borderRadius: '12px', border: 'none', background: 'none', cursor: 'pointer', transition: 'background-color 0.15s', fontFamily: 'Inter, sans-serif', fontWeight: 500, fontSize: '14px' }}
          title="Profile"
          onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.1)')}
          onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}
        >
          <span className="material-symbols-outlined" style={{ fontSize: '24px', fontVariationSettings: "'FILL' 0" }}>person</span>
          <span className="hidden sm:inline">Profile</span>
        </button>
      </div>



      {/* Backend Settings Modal */}
      <SettingsModal
        open={showSettings}
        config={config}
        onSave={(newConfig) => setConfig(newConfig)}
        onClose={() => setShowSettings(false)}
      />
    </header>
  );
};
