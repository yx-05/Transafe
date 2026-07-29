import React from 'react';
import { useSimulation } from '../context/SimulationContext';
import { UserHeader } from '../components/UserHeader';

export const CallActivePage: React.FC = () => {
  const {
    isCallRinging,
    isCallConnected,
    callMode,
    callerId,
    suspicionScore,
    transcript,
    verificationAnchors,
    answerCall,
    declineCall,
    endCall,
    switchCallMode
  } = useSimulation();

  // Highlight phrase formatter
  const renderHighlightedText = (text: string, highlights?: Array<{ phrase: string; tag: string }>) => {
    if (!highlights || highlights.length === 0) return text;

    let parts: Array<{ text: string; isHighlight: boolean; tag?: string }> = [{ text, isHighlight: false }];

    highlights.forEach(({ phrase, tag }) => {
      const nextParts: typeof parts = [];
      parts.forEach((part) => {
        if (part.isHighlight) {
          nextParts.push(part);
        } else {
          const index = part.text.indexOf(phrase);
          if (index !== -1) {
            const before = part.text.substring(0, index);
            const match = part.text.substring(index, index + phrase.length);
            const after = part.text.substring(index + phrase.length);
            if (before) nextParts.push({ text: before, isHighlight: false });
            nextParts.push({ text: match, isHighlight: true, tag });
            if (after) nextParts.push({ text: after, isHighlight: false });
          } else {
            nextParts.push(part);
          }
        }
      });
      parts = nextParts;
    });

    return parts.map((part, idx) =>
      part.isHighlight ? (
        <span key={idx} className="risk-highlight" title={`Threat Flag: ${part.tag}`}>
          {part.text}
          <span className="risk-tag">[{part.tag}]</span>
        </span>
      ) : (
        <span key={idx}>{part.text}</span>
      )
    );
  };

  const getSuspicionColor = (score: number) => {
    if (score > 70) return '#ef4444';
    if (score > 35) return '#f59e0b';
    return '#10b981';
  };

  return (
    <div className="dark-container" style={{ minHeight: '100vh', paddingBottom: '100px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <div className="header-padding-wrapper" style={{ width: '100%', paddingTop: '16px' }}>
        <UserHeader title="Safety Copilot" showBack={true} />
      </div>
      <div style={{ width: '100%', maxWidth: '768px', padding: '0 16px' }}>
        {/* ======================================================
            1. INCOMING CALL HUD MODAL
           ====================================================== */}
        {isCallRinging && (
          <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.8)', backdropFilter: 'blur(8px)', zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
            <div className="dark-card" style={{ textAlign: 'center', padding: '32px', width: '100%', maxWidth: '448px' }}>
              <div style={{ width: '96px', height: '96px', backgroundColor: 'rgba(37, 99, 235, 0.2)', color: '#3b82f6', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 24px', animation: 'pulse-red 2s infinite' }}>
                <span className="material-symbols-outlined" style={{ fontSize: '48px' }}>phone_callback</span>
              </div>

              <h2 style={{ fontSize: '24px', fontWeight: 800, color: '#ffffff', marginBottom: '4px' }}>{callerId}</h2>
              <p style={{ fontSize: '12px', color: '#60a5fa', fontFamily: 'monospace', marginBottom: '16px' }}>
                Secure Line Connection: WebRTC Call Session
              </p>

              <div style={{ padding: '12px', backgroundColor: 'rgba(127, 29, 29, 0.6)', border: '1px solid rgba(153, 27, 27, 0.6)', borderRadius: '12px', color: '#fca5a5', fontSize: '12px', marginBottom: '32px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="material-symbols-outlined" style={{ color: '#f87171' }}>warning</span>
                <span>Warning: Caller ID mimics CIMB/Maybank support prefixes. Exercise caution.</span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ display: 'flex', gap: '12px' }}>
                  <button
                    onClick={() => answerCall('copilot')}
                    className="btn-primary"
                    style={{ flex: 1, padding: '14px', fontSize: '14px', justifyContent: 'center', backgroundColor: '#059669', boxShadow: 'none' }}
                    onMouseEnter={e => { e.currentTarget.style.backgroundColor = '#047857'; }}
                    onMouseLeave={e => { e.currentTarget.style.backgroundColor = '#059669'; }}
                  >
                    <span className="material-symbols-outlined">headset_mic</span>
                    Listen & Monitor
                  </button>

                  <button
                    onClick={() => answerCall('autotalk')}
                    className="btn-primary"
                    style={{ flex: 1, padding: '14px', fontSize: '14px', justifyContent: 'center', backgroundColor: '#2563eb', boxShadow: 'none' }}
                    onMouseEnter={e => { e.currentTarget.style.backgroundColor = '#1d4ed8'; }}
                    onMouseLeave={e => { e.currentTarget.style.backgroundColor = '#2563eb'; }}
                  >
                    <span className="material-symbols-outlined">smart_toy</span>
                    Let AI Answer
                  </button>
                </div>

                <button
                  onClick={declineCall}
                  className="btn-danger"
                  style={{ width: '100%', padding: '14px', justifyContent: 'center', backgroundColor: '#dc2626', boxShadow: 'none' }}
                  onMouseEnter={e => { e.currentTarget.style.backgroundColor = '#b91c1c'; }}
                  onMouseLeave={e => { e.currentTarget.style.backgroundColor = '#dc2626'; }}
                >
                  <span className="material-symbols-outlined">call_end</span>
                  Decline Call
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ======================================================
            2. ACTIVE CALL DASHBOARD (COPILOT vs AUTO-TALK)
           ====================================================== */}
        {isCallConnected ? (
          <div className="dark-card" style={{ padding: '24px' }}>
            {/* Call Header */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', borderBottom: '1px solid #374151', paddingBottom: '16px', marginBottom: '24px' }}>
              <div style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <span style={{ width: '12px', height: '12px', backgroundColor: '#ef4444', borderRadius: '50%', animation: 'ping 1.5s infinite' }}></span>
                    <h2 style={{ fontSize: '20px', fontWeight: 700, color: '#ffffff', margin: 0 }}>{callerId}</h2>
                  </div>
                  <p style={{ fontSize: '12px', color: '#9ca3af', marginTop: '4px', fontFamily: 'monospace' }}>
                    Mode: <strong style={{ color: '#60a5fa', textTransform: 'uppercase' }}>{callMode}</strong> • WebRTC Encrypted Stream
                  </p>
                </div>

                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {callMode === 'copilot' ? (
                    <button
                      onClick={() => switchCallMode('autotalk')}
                      className="btn-secondary"
                      style={{ padding: '8px 12px', fontSize: '12px', backgroundColor: 'rgba(30, 58, 138, 0.4)', color: '#93c5fd', border: '1px solid #1d4ed8' }}
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>smart_toy</span>
                      Switch to Auto-Talk
                    </button>
                  ) : (
                    <button
                      onClick={() => switchCallMode('copilot')}
                      className="btn-primary"
                      style={{ padding: '8px 12px', fontSize: '12px', backgroundColor: '#2563eb', boxShadow: 'none' }}
                      onMouseEnter={e => { e.currentTarget.style.backgroundColor = '#1d4ed8'; }}
                      onMouseLeave={e => { e.currentTarget.style.backgroundColor = '#2563eb'; }}
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>mic</span>
                      Take Over Call
                    </button>
                  )}

                  <button onClick={endCall} className="btn-danger" style={{ padding: '8px 16px', fontSize: '12px' }}>
                    <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>call_end</span>
                    End Call
                  </button>
                </div>
              </div>
            </div>

            {/* Suspicion Score Gauge */}
            <div style={{ marginBottom: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px', color: '#9ca3af' }}>
                <span>Call Suspicion Level</span>
                <span style={{ color: getSuspicionColor(suspicionScore), fontSize: '14px', fontWeight: 800 }}>
                  {suspicionScore} / 100
                </span>
              </div>
              <div style={{ width: '100%', height: '12px', backgroundColor: '#1f2937', borderRadius: '9999px', overflow: 'hidden' }}>
                <div
                  style={{
                    height: '100%',
                    width: `${suspicionScore}%`,
                    backgroundColor: getSuspicionColor(suspicionScore),
                    transition: 'width 0.5s'
                  }}
                ></div>
              </div>
            </div>

            {/* High Suspicion Alert Banner */}
            {suspicionScore >= 70 && (
              <div style={{ padding: '16px', borderRadius: '12px', backgroundColor: 'rgba(127, 29, 29, 0.8)', border: '2px solid #dc2626', color: '#fecaca', marginBottom: '24px', display: 'flex', alignItems: 'flex-start', gap: '12px', animation: 'pulse-red 2s infinite' }}>
                <span className="material-symbols-outlined" style={{ color: '#ef4444', fontSize: '24px' }}>warning</span>
                <div>
                  <h4 style={{ fontWeight: 700, fontSize: '14px', margin: 0 }}>HIGH SCAM PROBABILITY DETECTED</h4>
                  <p style={{ fontSize: '12px', marginTop: '2px', opacity: 0.9 }}>
                    Caller is using authority impersonation and coercion techniques. Do NOT perform any bank transfer!
                  </p>
                </div>
              </div>
            )}

            {/* Auto-Talk Verification Checklist */}
            {callMode === 'autotalk' && (
              <div style={{ marginBottom: '24px', padding: '16px', borderRadius: '12px', backgroundColor: '#0b0f19', border: '1px solid #374151' }}>
                <h4 style={{ fontSize: '12px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#60a5fa', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>checklist</span>
                  AI Verification Question Checklist
                </h4>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
                  {verificationAnchors.map((anchor) => (
                    <div
                      key={anchor.id}
                      className="dark-bg-element"
                      style={{ padding: '10px', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '12px' }}
                    >
                      <span style={{ fontWeight: 500, color: '#d1d5db' }}>
                        {anchor.code} {anchor.title.substring(0, 24)}...
                      </span>
                      <span
                        className={`${
                          anchor.status === 'PASSED'
                            ? 'dark-badge-pass'
                            : anchor.status === 'EVADED' || anchor.status === 'FAILED'
                            ? 'dark-badge-fail'
                            : anchor.status === 'FLAG_TRIGGERED'
                            ? 'dark-badge-flag'
                            : 'dark-badge-pending'
                        }`}
                        style={{ padding: '2px 8px', borderRadius: '4px', fontWeight: 700, textTransform: 'uppercase', fontSize: '10px', whiteSpace: 'nowrap' }}
                      >
                        {anchor.status}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Live Transcript Container */}
            <div>
              <h4 style={{ fontSize: '12px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#9ca3af', marginBottom: '12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>Live Speech Transcript & Threat Highlights</span>
                <span style={{ fontSize: '10px', color: '#6b7280', fontFamily: 'monospace' }}>Whisper STT Stream</span>
              </h4>

              <div style={{ backgroundColor: '#0b0f19', padding: '16px', borderRadius: '16px', border: '1px solid #374151', maxHeight: '320px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {transcript.length === 0 ? (
                  <p style={{ fontSize: '12px', color: '#6b7280', textAlign: 'center', padding: '32px 0' }}>
                    Listening to incoming audio stream... (Trigger speech from Scammer Simulator)
                  </p>
                ) : (
                  transcript.map((line) => (
                    <div
                      key={line.id}
                      className={`speech-bubble ${
                        line.speaker === 'caller' ? 'caller' : line.speaker === 'ai' ? 'ai' : 'user'
                      }`}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '10px', opacity: 0.6, marginBottom: '4px', fontFamily: 'monospace' }}>
                        <span style={{ fontWeight: 700, textTransform: 'uppercase' }}>
                          {line.speaker === 'caller'
                            ? 'Caller (Scammer)'
                            : line.speaker === 'ai'
                            ? 'AI Agent'
                            : 'User'}
                        </span>
                        <span>{line.timestamp}</span>
                      </div>
                      <p style={{ margin: 0 }}>{renderHighlightedText(line.text, line.highlights)}</p>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        ) : (
          /* Call Not Active View */
          <div className="dark-card" style={{ textAlign: 'center', padding: '64px 24px' }}>
            <div style={{ width: '80px', height: '80px', backgroundColor: '#1f2937', color: '#9ca3af', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 24px' }}>
              <span className="material-symbols-outlined" style={{ fontSize: '36px' }}>phone_disabled</span>
            </div>
            <h2 style={{ fontSize: '24px', fontWeight: 700, color: '#ffffff', marginBottom: '8px' }}>No Active Call Session</h2>
            <p style={{ fontSize: '12px', color: '#9ca3af', maxWidth: '448px', margin: '0 auto 32px' }}>
              TranSafe Real-Time Safety Copilot will automatically intercept incoming phone calls, transcribe conversations, and highlight scam keyphrases.
            </p>
            <button
              onClick={() => answerCall('copilot')}
              className="btn-primary"
              style={{ padding: '14px 24px', justifyContent: 'center', backgroundColor: '#2563eb', boxShadow: 'none', display: 'inline-flex' }}
              onMouseEnter={e => { e.currentTarget.style.backgroundColor = '#1d4ed8'; }}
              onMouseLeave={e => { e.currentTarget.style.backgroundColor = '#2563eb'; }}
            >
              <span className="material-symbols-outlined">call</span>
              Simulate Active Call
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
