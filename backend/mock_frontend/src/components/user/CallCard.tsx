import React, { useState, useRef, useEffect } from 'react';
import type { BackendConfig, CallMode, WsCallEventMessage, CallPreCheck } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { CallEventsWebSocketClient } from '../../services/websocket';
import { CallAudioStreamer } from '../../services/audioRecorder';
import { PhoneCall, Mic, MicOff, ShieldAlert, Radio, AlertTriangle, Zap } from 'lucide-react';

interface CallCardProps {
  config: BackendConfig;
  userId: string;
}

export const CallCard: React.FC<CallCardProps> = ({ config, userId }) => {
  const [callerNumber, setCallerNumber] = useState('+60161234567');
  const [callerName, setCallerName] = useState('Unknown Caller');
  const [callMode, setCallMode] = useState<CallMode>('LISTEN');

  const [activeCallSessionId, setActiveCallSessionId] = useState<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [audioStatus, setAudioStatus] = useState('Idle');
  const [preCheck, setPreCheck] = useState<CallPreCheck | null>(null);

  const [transcripts, setTranscripts] = useState<Array<{ speaker: string; text: string }>>([]);
  const [highlights, setHighlights] = useState<Array<{ phrase: string; risk_level: string; reason: string }>>([]);
  const [currentMode, setCurrentMode] = useState<CallMode>('LISTEN');

  const audioStreamerRef = useRef<CallAudioStreamer>(new CallAudioStreamer());
  const eventsWsClientRef = useRef<CallEventsWebSocketClient>(new CallEventsWebSocketClient());

  useEffect(() => {
    return () => {
      audioStreamerRef.current.stopStreaming();
      eventsWsClientRef.current.close();
    };
  }, []);

  const handleStartCall = async (e: React.FormEvent) => {
    e.preventDefault();
    setTranscripts([]);
    setHighlights([]);
    setPreCheck(null);

    const client = new TranSafeApiClient(config);
    const sessionId = `sess-call-${Date.now()}`;

    try {
      // 1. Trigger REST API
      const res = await client.triggerCall({
        user_id: userId,
        session_id: sessionId,
        call: {
          caller_number: callerNumber,
          caller_name: callerName,
          call_mode: callMode,
          call_channel: 'WEBRTC',
        },
      });

      setActiveCallSessionId(res.call_session_id);
      setActiveSessionId(sessionId);
      setCurrentMode(res.call_mode);
      setPreCheck(res.pre_check);

      // 2. Connect Events WebSocket
      eventsWsClientRef.current.connect(
        config.baseUrl,
        res.call_session_id,
        (msg: WsCallEventMessage) => {
          if (msg.type === 'transcript' && msg.text) {
            setTranscripts((prev) => [...prev, { speaker: msg.speaker || 'CALLER', text: msg.text || '' }]);
          }
          if (msg.type === 'highlight' && msg.highlighted_spans) {
            setHighlights((prev) => [...prev, ...msg.highlighted_spans!]);
          }
          if (msg.type === 'mode_change' && msg.call_mode) {
            setCurrentMode(msg.call_mode);
          }
        },
        (err) => console.error('Events WS error:', err),
        () => console.log('Events WS closed')
      );

      // 3. Start real-time microphone recording & WebSocket streaming
      await audioStreamerRef.current.startStreaming(
        config.baseUrl,
        res.call_session_id,
        (status) => setAudioStatus(status),
        (err) => alert(`Microphone Streaming Error: ${err}`)
      );

      setStreaming(true);
    } catch (err: any) {
      alert(`Start call failed: ${err.message}`);
    }
  };

  const handleTakeover = async () => {
    if (!activeSessionId) return;
    const client = new TranSafeApiClient(config);
    try {
      const res = await client.takeoverCall(activeSessionId);
      setCurrentMode('AUTO_TALK');
      alert(res.message);
    } catch (err: any) {
      alert(`Takeover failed: ${err.message}`);
    }
  };

  const handleEndCall = () => {
    audioStreamerRef.current.stopStreaming();
    eventsWsClientRef.current.close();
    setStreaming(false);
    setAudioStatus('Call Ended');
  };

  return (
    <div className="card test-card">
      <div className="card-header">
        <div className="card-title">
          <PhoneCall className="card-icon" size={20} />
          <h3>Real-Time WebRTC Call Safety Copilot</h3>
        </div>
        <span className="card-tag">FR-T03 / FR-C01</span>
      </div>

      {!streaming ? (
        <form onSubmit={handleStartCall} className="card-form">
          <div className="form-row">
            <div className="form-group">
              <label>Caller Phone Number</label>
              <input
                type="text"
                value={callerNumber}
                onChange={(e) => setCallerNumber(e.target.value)}
                placeholder="+60161234567"
                required
              />
              <small>Try <code>+60161234567</code> (Blacklisted in DB)</small>
            </div>
            <div className="form-group">
              <label>Caller Display Name</label>
              <input
                type="text"
                value={callerName}
                onChange={(e) => setCallerName(e.target.value)}
              />
            </div>
          </div>

          <div className="form-group">
            <label>Initial Call Mode</label>
            <select
              value={callMode}
              onChange={(e) => setCallMode(e.target.value as CallMode)}
            >
              <option value="LISTEN">LISTEN Mode (User speaks, AI highlights live danger phrases)</option>
              <option value="AUTO_TALK">AUTO_TALK Mode (AI takes over & speaks to caller using anchor questions)</option>
            </select>
          </div>

          <button type="submit" className="btn-primary">
            <Mic size={16} /> Start Call Session & Connect Microphone
          </button>
        </form>
      ) : (
        <div className="active-call-panel">
          <div className="call-status-bar">
            <div className="status-live">
              <Radio className="pulse text-red" size={18} />
              <span>LIVE CALL SESSION: <code>{activeCallSessionId}</code></span>
            </div>
            <span className="mode-badge">{currentMode} MODE</span>
            <button className="btn-danger" onClick={handleEndCall}>
              <MicOff size={16} /> End Call
            </button>
          </div>

          <div className="audio-stream-status">
            <strong>Microphone Audio Stream:</strong> {audioStatus}
          </div>

          {preCheck && preCheck.blacklisted && (
            <div className="precheck-warning high">
              <ShieldAlert size={20} />
              <div>
                <strong>⚠️ BLACKLISTED CALLER DETECTED!</strong>
                <p>{preCheck.warning}</p>
              </div>
            </div>
          )}

          {currentMode === 'LISTEN' && (
            <div className="takeover-box">
              <p>Suspicious coercion speech detected mid-call?</p>
              <button className="btn-warning" onClick={handleTakeover}>
                <Zap size={16} /> Trigger AI Takeover (Switch to AUTO_TALK)
              </button>
            </div>
          )}

          <div className="call-dashboard-grid">
            <div className="transcript-box">
              <h4>Real-Time Groq Whisper STT Transcript</h4>
              <div className="transcript-lines">
                {transcripts.length === 0 ? (
                  <p className="placeholder-text">Speak into your microphone... Audio chunks are being transcribed in real-time.</p>
                ) : (
                  transcripts.map((t, idx) => (
                    <div key={idx} className={`transcript-line ${t.speaker}`}>
                      <strong>{t.speaker}:</strong> {t.text}
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="highlights-box">
              <h4><AlertTriangle size={16} /> Live Danger Phrase Highlights</h4>
              <div className="highlight-list">
                {highlights.length === 0 ? (
                  <p className="placeholder-text">No danger phrases detected yet.</p>
                ) : (
                  highlights.map((h, idx) => (
                    <div key={idx} className={`highlight-chip ${h.risk_level.toLowerCase()}`}>
                      <strong>"{h.phrase}"</strong> — {h.reason} ({h.risk_level})
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
