import React, { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

interface UserHeaderProps {
  title?: string;
  showBack?: boolean;
}

export const UserHeader: React.FC<UserHeaderProps> = ({ title = 'TranSafe', showBack = false }) => {
  const navigate = useNavigate();
  const bellBtnRef = useRef<HTMLButtonElement>(null);
  const helpBtnRef = useRef<HTMLButtonElement>(null);
  const [showNotificationToast, setShowNotificationToast] = useState(false);
  const [showHelpModal, setShowHelpModal] = useState(false);
  const [notifRightOffset, setNotifRightOffset] = useState<number | null>(null);
  const [helpRightOffset, setHelpRightOffset] = useState<number | null>(null);

  const computeRightOffset = (btnRef: React.RefObject<HTMLButtonElement | null>, dropdownWidth: number): number | null => {
    if (!btnRef.current) return null;
    const clientWidth = document.documentElement.clientWidth;
    const btnRight = Math.round(btnRef.current.getBoundingClientRect().right);
    const rightOffset = Math.round(clientWidth - btnRight);
    // If the dropdown would overflow the left edge (allowance: 16px), fall back to left positioning
    // by returning a sentinel value. The inline style will use 'left' instead of 'right'.
    if (btnRight - dropdownWidth < 16) {
      return -1; // sentinel: use left positioning
    }
    return rightOffset;
  };

  const handleBellClick = () => {
    setShowHelpModal(false);
    const willShow = !showNotificationToast;
    setShowNotificationToast(willShow);
    if (willShow && bellBtnRef.current) {
      setNotifRightOffset(computeRightOffset(bellBtnRef, 320));
    } else if (!willShow) {
      setNotifRightOffset(null);
    }
  };

  const handleHelpClick = () => {
    setShowNotificationToast(false);
    const willShow = !showHelpModal;
    setShowHelpModal(willShow);
    if (willShow && helpBtnRef.current) {
      setHelpRightOffset(computeRightOffset(helpBtnRef, 360));
    } else if (!willShow) {
      setHelpRightOffset(null);
    }
  };

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
        {/* Notification Bell */}
        <button
          ref={bellBtnRef}
          onClick={handleBellClick}
          style={{ color: '#ffffff', padding: '10px', borderRadius: '9999px', border: 'none', background: 'none', cursor: 'pointer', transition: 'background-color 0.15s', position: 'relative' }}
          title="Notifications"
          onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.1)')}
          onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}
        >
          <span className="material-symbols-outlined" style={{ fontSize: '28px', fontVariationSettings: "'FILL' 0" }}>
            notifications
          </span>
          <span style={{ position: 'absolute', top: '8px', right: '8px', width: '8px', height: '8px', backgroundColor: '#f87171', borderRadius: '9999px' }}></span>
        </button>

        {/* Help Question Mark */}
        <button
          ref={helpBtnRef}
          onClick={handleHelpClick}
          style={{ color: '#ffffff', padding: '10px', borderRadius: '9999px', border: 'none', background: 'none', cursor: 'pointer', transition: 'background-color 0.15s' }}
          title="Help"
          onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.1)')}
          onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}
        >
          <span className="material-symbols-outlined" style={{ fontSize: '28px', fontVariationSettings: "'FILL' 0" }}>
            help_outline
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

      {/* Notifications Dropdown */}
      {showNotificationToast && (
        <div className="dropdown-fixed-right" style={{
          position: 'fixed',
          top: '80px',
          right: notifRightOffset !== null && notifRightOffset >= 0 ? notifRightOffset : 'auto',
          left: notifRightOffset !== null && notifRightOffset < 0 ? 16 : 'auto',
          width: '320px',
          maxWidth: 'calc(100% - 32px)',
          backgroundColor: '#ffffff',
          borderRadius: '20px',
          padding: '20px',
          boxShadow: '0 20px 50px rgba(0,0,0,0.15)',
          border: '1px solid #edeeef',
          zIndex: 60,
          color: '#191c1d'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #edeeef', paddingBottom: '12px', marginBottom: '16px' }}>
            <h4 style={{ fontWeight: 700, fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#0050cb' }}>Security Alerts</h4>
            <button onClick={() => setShowNotificationToast(false)} style={{ color: '#9ca3af', background: 'none', border: 'none', cursor: 'pointer', padding: '4px' }}>
              <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>close</span>
            </button>
          </div>
          <div style={{ padding: '14px', borderRadius: '12px', backgroundColor: '#f0f5ff', border: '1px solid #dbeafe', fontSize: '13px' }}>
            <p style={{ fontWeight: 700, color: '#191c1d', marginBottom: '4px' }}>BNM AI Shield Active</p>
            <p style={{ color: '#6b7280', fontSize: '11px', margin: 0 }}>Real-time scam protection enabled.</p>
          </div>
        </div>
      )}

      {/* Help Dropdown */}
      {showHelpModal && (
        <div className="dropdown-fixed-right" style={{
          position: 'fixed',
          top: '80px',
          right: helpRightOffset !== null && helpRightOffset >= 0 ? helpRightOffset : 'auto',
          left: helpRightOffset !== null && helpRightOffset < 0 ? 16 : 'auto',
          width: '360px',
          maxWidth: 'calc(100% - 32px)',
          backgroundColor: '#ffffff',
          borderRadius: '20px',
          padding: '24px',
          boxShadow: '0 20px 50px rgba(0,0,0,0.15)',
          border: '1px solid #edeeef',
          zIndex: 60,
          color: '#191c1d'
        }}>
          <button
            onClick={() => setShowHelpModal(false)}
            style={{ position: 'absolute', top: '16px', right: '16px', color: '#9ca3af', background: 'none', border: 'none', cursor: 'pointer', padding: '4px' }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>close</span>
          </button>
          <div style={{ width: '48px', height: '48px', borderRadius: '16px', backgroundColor: '#dae1ff', color: '#0050cb', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '16px' }}>
            <span className="material-symbols-outlined" style={{ fontSize: '24px' }}>help_outline</span>
          </div>
          <h3 style={{ fontSize: '22px', fontWeight: 700, color: '#191c1d', marginBottom: '8px' }}>TranSafe Support</h3>
          <p style={{ fontSize: '13px', color: '#6b7280', marginBottom: '24px', lineHeight: 1.5 }}>
            TranSafe is an AI multi-agent fraud prevention platform safeguarding transactions and voice calls in real-time.
          </p>
          <div style={{ padding: '16px', borderRadius: '16px', backgroundColor: '#fff5f5', border: '1px solid #fecaca', marginBottom: '24px' }}>
            <p style={{ fontSize: '11px', fontWeight: 700, color: '#991b1b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '4px' }}>National Scam Response Centre</p>
            <p style={{ fontSize: '22px', fontWeight: 800, color: '#dc2626', margin: 0 }}>Dial 997</p>
          </div>
          <button
            onClick={() => setShowHelpModal(false)}
            style={{
              width: '100%',
              backgroundColor: '#0066ff',
              color: '#ffffff',
              border: 'none',
              padding: '14px',
              borderRadius: '20px',
              fontSize: '14px',
              fontWeight: 600,
              cursor: 'pointer',
              fontFamily: 'Inter, sans-serif'
            }}
          >
            Close
          </button>
        </div>
      )}
    </header>
  );
};
