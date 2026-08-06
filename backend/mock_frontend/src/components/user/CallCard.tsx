import React, { useState, useRef, useEffect } from 'react';
import type { BackendConfig, CallMode, WsCallEventMessage, CallPreCheck, XaiReport } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { CallEventsWebSocketClient, SessionWebSocketClient } from '../../services/websocket';
import { CallAudioStreamer } from '../../services/audioRecorder';
import {
  PhoneCall,
  Mic,
  MicOff,
  ShieldAlert,
  Radio,
  AlertTriangle,
  Zap,
  Activity,
  FileText,
  CheckCircle2,
  Terminal,
  PhoneIncoming,
  XCircle,
  CheckCircle,
} from 'lucide-react';

interface CallCardProps {
  config: BackendConfig;
  userId: string;
  onOpenXaiReport?: (report: XaiReport) => void;
}

export const CallCard: React.FC<CallCardProps> = ({ config, userId, onOpenXaiReport }) => {
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

  // Incoming Call State
  const [incomingCall, setIncomingCall] = useState<{
    call_session_id: string;
    caller_number: string;
    caller_name: string;
  } | null>(null);

  // Backend Action Progress & Pipeline Tracker State
  const [statusLog, setStatusLog] = useState<string[]>([
    'System ready. Monitoring for incoming scammer calls...',
  ]);
  const [currentResult, setCurrentResult] = useState<XaiReport | null>(null);

  const audioStreamerRef = useRef<CallAudioStreamer>(new CallAudioStreamer());
  const eventsWsClientRef = useRef<CallEventsWebSocketClient>(new CallEventsWebSocketClient());
  const sessionWsClientRef = useRef<SessionWebSocketClient>(new SessionWebSocketClient());

  useEffect(() => {
    return () => {
      audioStreamerRef.current.stopStreaming();
      eventsWsClientRef.current.close();
      sessionWsClientRef.current.close();
    };
  }, []);

  // Poll for incoming ringing call from Scammer workbench
  useEffect(() => {
    if (streaming) return;
    const client = new TranSafeApiClient(config);
    const interval = setInterval(async () => {
      try {
        const call = await client.getActiveCall(userId);
        if (call && call.status === 'RINGING' && (!incomingCall || incomingCall.call_session_id !== call.call_session_id)) {
          const callId = call.call_session_id as string;
          const number = (call.caller_number as string) || '+60161234567';
          const name = (call.caller_name as string) || 'Inspector Tan (PDRM Fake)';
          
          setIncomingCall({
            call_session_id: callId,
            caller_number: number,
            caller_name: name,
          });

          setStatusLog((prev) => [
            ...prev,
            `[CALL ENGINE] 📞 Incoming call detected from ${name} (${number})`,
            `[CALL ENGINE] Registering ringing call session: ${callId}`,
            `[PRE-CHECK] Evaluating caller ID risk against Supabase Fraud Memory...`,
          ]);
        }
      } catch (e) {
        // Silently ignore polling errors
      }
    }, 1500);

    return () => clearInterval(interval);
  }, [config.baseUrl, config.apiKey, userId, streaming, incomingCall]);

  const handleAcceptCall = async () => {
    if (!incomingCall) return;
    const client = new TranSafeApiClient(config);
    const callSessionId = incomingCall.call_session_id;
    const sessionId = `sess-call-${Date.now()}`;

    setTranscripts([]);
    setHighlights([]);
    setPreCheck(null);

    setStatusLog((prev) => [
      ...prev,
      `[CALL ENGINE] Answering call session ${callSessionId}...`,
      `[REST API] POST /api/v1/call/${callSessionId}/answer -> HTTP 200`,
      `[WEBSOCKET] Connecting events stream /ws/call/${callSessionId}/events...`,
    ]);

    try {
      await client.answerCall(callSessionId);
      setActiveCallSessionId(callSessionId);
      setActiveSessionId(sessionId);
      setIncomingCall(null);

      // Connect Session WebSocket for Multi-Agent Graph pipeline progress
      sessionWsClientRef.current.connect(
        config.baseUrl,
        sessionId,
        config.apiKey,
        (msg) => {
          if (msg.type === 'status' && msg.message) {
            setStatusLog((prev) => [...prev, `[AGENT PIPELINE] ${msg.message}`]);
          }
          if (msg.type === 'result' && msg.result) {
            setCurrentResult(msg.result);
            setStatusLog((prev) => [
              ...prev,
              `[AGENT PIPELINE] ✅ Pipeline complete. Risk Score: ${msg.result?.risk_score}/100 (${msg.result?.risk_tier})`,
            ]);
          }
        },
        (err) => console.error('Session WS error:', err),
        () => console.log('Session WS closed')
      );

      // Connect Call Events WebSocket
      eventsWsClientRef.current.connect(
        config.baseUrl,
        callSessionId,
        config.apiKey,
        (msg: WsCallEventMessage) => {
          if (msg.type === 'transcript' && msg.text) {
            setTranscripts((prev) => [...prev, { speaker: msg.speaker || 'SCAMMER', text: msg.text || '' }]);
            setStatusLog((prev) => [
              ...prev,
              `[GROQ WHISPER STT] [${msg.speaker}]: "${msg.text}"`,
            ]);
          }
          if (msg.type === 'highlight' && msg.highlighted_spans) {
            setHighlights((prev) => [...prev, ...msg.highlighted_spans!]);
            setStatusLog((prev) => [
              ...prev,
              `[SAFETY COPILOT ⚠️] High-risk coercion phrase: "${msg.highlighted_spans![0]?.phrase}"`,
            ]);
          }
          if (msg.type === 'mode_change' && msg.call_mode) {
            setCurrentMode(msg.call_mode);
            setStatusLog((prev) => [...prev, `[COPILOT] Call Mode updated to: ${msg.call_mode}`]);
          }
          if (msg.type === 'pre_check_result') {
            setPreCheck({
              blacklisted: msg.blacklisted || false,
              blacklist_cases: msg.blacklist_case_count || 0,
              initial_risk: msg.initial_risk || 'LOW',
              warning: msg.warning_text || undefined,
            });
            setStatusLog((prev) => [
              ...prev,
              `[PRE-CHECK] Blacklist Status: ${msg.blacklisted ? 'BLACKLISTED (2 Cases)' : 'CLEAN'}`,
            ]);
          }
          if (msg.type === 'call_ended') {
            audioStreamerRef.current.stopStreaming();
            setStreaming(false);
            setAudioStatus('Call Ended by Peer');
            setStatusLog((prev) => [...prev, '[CALL ENGINE] 📴 Call session ended by peer.']);
          }
        },
        (err) => console.error('Events WS error:', err),
        () => console.log('Events WS closed')
      );

      // Start Customer Microphone Recording & Audio Relay Playback
      setStatusLog((prev) => [
        ...prev,
        `[WEBAUDIO RELAY] Initializing Customer Microphone (16kHz PCM)...`,
        `[WEBSOCKET] Connected to /ws/call/${callSessionId}/audio?role=CUSTOMER`,
      ]);

      await audioStreamerRef.current.startStreaming(
        config.baseUrl,
        callSessionId,
        config.apiKey,
        'CUSTOMER',
        (status) => {
          setAudioStatus(status);
          setStatusLog((prev) => [...prev, `[WEBAUDIO STREAM] ${status}`]);
        },
        (err) => setStatusLog((prev) => [...prev, `[MICROPHONE ERROR] ${err}`])
      );

      setStreaming(true);
    } catch (err: any) {
      alert(`Accept call failed: ${err.message}`);
    }
  };

  const handleDeclineCall = async () => {
    if (!incomingCall) return;
    const client = new TranSafeApiClient(config);
    try {
      await client.declineCall(incomingCall.call_session_id);
      setStatusLog((prev) => [...prev, `[CALL ENGINE] Call ${incomingCall.call_session_id} declined.`]);
    } catch (e) {}
    setIncomingCall(null);
  };

  const handleStartCallForm = async (e: React.FormEvent) => {
    e.preventDefault();
    setTranscripts([]);
    setHighlights([]);
    setPreCheck(null);
    setStatusLog(['[CALL ENGINE] Initiating Call Trigger request to backend...']);
    setCurrentResult(null);

    const client = new TranSafeApiClient(config);
    const sessionId = `sess-call-${Date.now()}`;

    try {
      const res = await client.triggerCall({
        user_id: userId,
        session_id: sessionId,
        call: {
          caller_number: callerNumber,
          caller_name: callerName,
          call_mode: callMode,
          call_channel: 'WEBRTC',
          received_at: new Date().toISOString(),
          stt_engine: 'nova-3',
        },
      });

      setActiveCallSessionId(res.call_session_id);
      setActiveSessionId(sessionId);
      setCurrentMode(res.call_mode);
      setPreCheck(res.pre_check);

      setStatusLog((prev) => [
        ...prev,
        `[REST API] POST /api/v1/trigger/call -> Session registered (${sessionId})`,
        `[PRE-CHECK] Blacklisted: ${res.pre_check.blacklisted ? 'YES ⚠️' : 'NO ✅'}`,
        `[WEBSOCKET] Connecting to audio & event streams...`,
      ]);

      eventsWsClientRef.current.connect(
        config.baseUrl,
        res.call_session_id,
        config.apiKey,
        (msg: WsCallEventMessage) => {
          if (msg.type === 'transcript' && msg.text) {
            setTranscripts((prev) => [...prev, { speaker: msg.speaker || 'SCAMMER', text: msg.text || '' }]);
            setStatusLog((prev) => [
              ...prev,
              `[GROQ WHISPER STT] [${msg.speaker}]: "${msg.text}"`,
            ]);
          }
          if (msg.type === 'highlight' && msg.highlighted_spans) {
            setHighlights((prev) => [...prev, ...msg.highlighted_spans!]);
            setStatusLog((prev) => [
              ...prev,
              `[SAFETY COPILOT ⚠️] High-risk phrase: "${msg.highlighted_spans![0]?.phrase}"`,
            ]);
          }
          if (msg.type === 'mode_change' && msg.call_mode) {
            setCurrentMode(msg.call_mode);
          }
        },
        (err) => console.error('Events WS error:', err),
        () => console.log('Events WS closed')
      );

      await audioStreamerRef.current.startStreaming(
        config.baseUrl,
        res.call_session_id,
        config.apiKey,
        'CUSTOMER',
        (status) => setAudioStatus(status),
        (err) => alert(`Microphone Streaming Error: ${err}`)
      );

      setStreaming(true);
    } catch (err: any) {
      alert(`Start call failed: ${err.message}`);
    }
  };

  const handleTakeover = async () => {
    if (!activeCallSessionId) return;
    const client = new TranSafeApiClient(config);
    try {
      setStatusLog((prev) => [...prev, '[AGENT TAKEOVER] Triggering AI Agent mid-call takeover (switching to AUTO_TALK)...']);
      const res = await client.takeoverCall(activeCallSessionId);
      setCurrentMode('AUTO_TALK');
      setStatusLog((prev) => [...prev, `[AGENT TAKEOVER] AI Agent active: ${res.message}`]);
    } catch (err: any) {
      alert(`Takeover failed: ${err.message}`);
    }
  };

  const handleEndCall = () => {
    audioStreamerRef.current.stopStreaming();
    eventsWsClientRef.current.close();
    sessionWsClientRef.current.close();
    setStreaming(false);
    setAudioStatus('Call Ended');
    setStatusLog((prev) => [...prev, '[CALL ENGINE] Call session ended manually.']);
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

      {/* INCOMING SCAMMER CALL RINGING POPUP */}
      {incomingCall && !streaming && (
        <div className="incoming-call-modal">
          <div className="incoming-call-content">
            <PhoneIncoming size={32} className="pulse text-red" />
            <div className="call-info">
              <h4>📞 INCOMING CALL FROM SCAMMER</h4>
              <p><strong>{incomingCall.caller_name}</strong> ({incomingCall.caller_number})</p>
              <small>TranSafe AI is monitoring this incoming call session.</small>
            </div>
            <div className="incoming-call-actions">
              <button className="btn-success" onClick={handleAcceptCall}>
                <CheckCircle size={16} /> Accept Call
              </button>
              <button className="btn-danger" onClick={handleDeclineCall}>
                <XCircle size={16} /> Decline
              </button>
            </div>
          </div>
        </div>
      )}

      {!streaming ? (
        <form onSubmit={handleStartCallForm} className="card-form">
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
            <Mic size={16} /> Start Direct Call Test Session
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
            <strong>Customer Microphone & Speaker Relay:</strong> {audioStatus}
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
              <h4>Dual-Speaker Groq Whisper STT Transcript</h4>
              <div className="transcript-lines">
                {transcripts.length === 0 ? (
                  <p className="placeholder-text">Speak into your microphone... Audio chunks from Scammer & Customer are transcribed live.</p>
                ) : (
                  transcripts.map((t, idx) => (
                    <div key={idx} className={`transcript-line ${t.speaker}`}>
                      <strong>[{t.speaker}]:</strong> {t.text}
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

      {/* ALWAYS VISIBLE: Backend Action Progress & Pipeline Tracker Panel */}
      {statusLog.length > 0 && (
        <div className="status-progress-panel" style={{ marginTop: '1rem' }}>
          <div className="progress-header">
            <Activity className="icon text-blue" size={16} />
            <h4>Backend Action Progress & Multi-Agent Pipeline Tracker</h4>
          </div>
          <div className="status-log-box" style={{ maxHeight: '180px', overflowY: 'auto' }}>
            {statusLog.map((log, idx) => (
              <div key={idx} className="status-log-item">
                <Terminal size={14} className="log-icon" />
                <span>{log}</span>
              </div>
            ))}
          </div>

          {currentResult && (
            <div className="pipeline-result-bar">
              <div className="result-badge-group">
                <CheckCircle2 size={18} className="text-green" />
                <span>Risk Score: <strong>{currentResult.risk_score}/100</strong> ({currentResult.risk_tier})</span>
                <span className="action-tag">Action: {currentResult.action_taken}</span>
              </div>
              {onOpenXaiReport && (
                <button
                  type="button"
                  className="btn-secondary btn-sm"
                  onClick={() => onOpenXaiReport(currentResult)}
                >
                  <FileText size={14} /> Inspect XAI Report
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
