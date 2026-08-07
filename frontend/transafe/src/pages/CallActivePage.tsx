import React, { useEffect, useRef, useState } from 'react';
import { useApi } from '../context/ApiContext';
import { UserHeader } from '../components/UserHeader';
import { CallEventsWebSocketClient } from '../services/websocket';
import { CallAudioStreamer, playAgentSpeech } from '../services/audioRecorder';
import type { CallPreCheck, WsCallEventMessage } from '../types/api';

interface TranscriptLine {
  id: number;
  speaker: 'caller' | 'ai' | 'user';
  text: string;
  ts: string;
  highlights?: Array<{ phrase: string; tag: string }>;
}

interface DeepAnalysis {
  reason: string;
  score: number;
  risk_tier: string;
  confidence: number;
  evidence: string[];
  extracted_entities: { phone_numbers: string[]; urls: string[]; bank_accounts: string[] };
  ts: string;
}

const DEFAULT_ANCHORS = [
  { id: 'aq-1', code: 'AQ-01', title: 'Identity Anchor Question', status: 'PENDING' },
  { id: 'aq-2', code: 'AQ-02', title: 'Authority Anchor Question', status: 'PENDING' },
  { id: 'aq-3', code: 'AQ-03', title: 'Money Anchor Question', status: 'PENDING' },
  { id: 'aq-4', code: 'AQ-04', title: 'Next Action Anchor Question', status: 'PENDING' },
];

const normalizeMode = (mode: string): 'copilot' | 'autotalk' =>
  mode === 'AUTO_TALK' ? 'autotalk' : 'copilot';

const normalizeSpeaker = (speaker?: string): 'caller' | 'ai' | 'user' => {
  if (speaker === 'TRANSAFE_AI') return 'ai';
  if (speaker === 'CUSTOMER') return 'user';
  return 'caller';
};

export const CallActivePage: React.FC = () => {
  const { config, client, userId } = useApi();


  const [callerName] = useState('Inspector Tan (PDRM Fake)');
  const [callMode, setCallMode] = useState<'copilot' | 'autotalk'>('copilot');
  const [currentMode, setCurrentMode] = useState<'copilot' | 'autotalk'>('copilot');

  const [activeCallSessionId, setActiveCallSessionId] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [micStatus, setMicStatus] = useState('Idle');
  const [preCheck, setPreCheck] = useState<CallPreCheck | null>(null);

  const [transcripts, setTranscripts] = useState<TranscriptLine[]>([]);
  const [suspicionScore, setSuspicionScore] = useState(0);
  const [verificationAnchors] = useState(DEFAULT_ANCHORS);
  const [deepAnalysis, setDeepAnalysis] = useState<DeepAnalysis | null>(null);
  const [awaitingFinalAnalysis, setAwaitingFinalAnalysis] = useState(false);

  const [incomingCall, setIncomingCall] = useState<{
    call_session_id: string;
    caller_number: string;
    caller_name: string;
  } | null>(null);

  const [statusLog, setStatusLog] = useState<string[]>([
    'System ready. Monitoring for incoming scammer calls...',
  ]);

  const audioStreamerRef = useRef<CallAudioStreamer>(new CallAudioStreamer());
  const eventsWsClientRef = useRef<CallEventsWebSocketClient>(new CallEventsWebSocketClient());
  const finalAnalysisTimerRef = useRef<number | null>(null);
  const lineIdRef = useRef(1);

  useEffect(() => {
    return () => {
      audioStreamerRef.current.stopStreaming();
      eventsWsClientRef.current.close();
      if (finalAnalysisTimerRef.current !== null) {
        window.clearTimeout(finalAnalysisTimerRef.current);
      }
    };
  }, []);

  // Poll for incoming ringing call from Scammer workbench / simulator
  useEffect(() => {
    if (streaming) return;
    const interval = setInterval(async () => {
      try {
        const call = await client.getActiveCall(userId);
        if (
          call &&
          call.status === 'RINGING' &&
          (!incomingCall || incomingCall.call_session_id !== call.call_session_id)
        ) {
          const callId = call.call_session_id as string;
          const number = (call.caller_number as string) || '+60161234567';
          const name = (call.caller_name as string) || 'Inspector Tan (PDRM Fake)';

          setIncomingCall({ call_session_id: callId, caller_number: number, caller_name: name });
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
  }, [config.baseUrl, client, userId, streaming, incomingCall]);

  const addTranscript = (speaker: 'caller' | 'ai' | 'user', text: string, highlights?: Array<{ phrase: string; tag: string }>) => {
    setTranscripts((prev) => [
      ...prev,
      { id: lineIdRef.current++, speaker, text, ts: new Date().toLocaleTimeString(), highlights },
    ]);
  };

  const handleAcceptCall = async () => {
    if (!incomingCall) return;
    const callSessionId = incomingCall.call_session_id;

    setTranscripts([]);
    setSuspicionScore(0);
    setDeepAnalysis(null);
    setAwaitingFinalAnalysis(false);
    if (finalAnalysisTimerRef.current !== null) {
      window.clearTimeout(finalAnalysisTimerRef.current);
      finalAnalysisTimerRef.current = null;
    }
    setCallMode('copilot');

    setStatusLog((prev) => [
      ...prev,
      `[CALL ENGINE] Answering call session ${callSessionId}...`,
      `[REST API] POST /api/v1/call/${callSessionId}/answer -> HTTP 200`,
      `[WEBSOCKET] Connecting events stream /ws/call/${callSessionId}/events...`,
    ]);

    try {
      await client.answerCall(callSessionId);
      setActiveCallSessionId(callSessionId);
      setIncomingCall(null);

      // Connect Call Events WebSocket
      eventsWsClientRef.current.connect(
        config.baseUrl,
        callSessionId,
        config.apiKey,
        (msg: WsCallEventMessage) => {
          if (msg.type === 'transcript' && msg.text) {
            const speaker = normalizeSpeaker(msg.speaker);
            addTranscript(speaker, msg.text);
            setStatusLog((prev) => [...prev, `[GROQ WHISPER STT] [${msg.speaker}]: "${msg.text}"`]);
          }
          if (msg.type === 'highlight' && msg.highlighted_spans) {
            const spans = msg.highlighted_spans
              .filter((s) => s.phrase)
              .map((s) => ({ phrase: s.phrase, tag: s.tag || s.risk_level || 'THREAT' }));
            if (spans.length > 0) {
              // Attach spans inline to the matching transcript line
              setTranscripts((prev) => {
                const next = [...prev];
                for (let i = next.length - 1; i >= 0; i--) {
                  if (next[i].text === (msg.text || '')) {
                    next[i] = { ...next[i], highlights: spans };
                    break;
                  }
                }
                return next;
              });
              setStatusLog((prev) => [
                ...prev,
                `[SAFETY COPILOT ⚠️] High-risk phrase: "${spans[0]?.phrase}" (${spans[0]?.tag})`,
              ]);
            }
          }
          if (msg.type === 'suspicion_update') {
            setSuspicionScore(msg.suspicion_score ?? 0);
            setStatusLog((prev) => [
              ...prev,
              `🚨 [PHONE AGENT SUSPICION ${msg.risk_tier}] cumulative=${msg.suspicion_score} utterance=${msg.utterance_risk_score}${msg.trigger_escalation ? ' — ⚠️ ESCALATED (HIGH)' : ''}`,
            ]);
          }
          if (msg.type === 'deep_analysis') {
            const analysis: DeepAnalysis = {
              reason: msg.reason || 'call_end',
              score: msg.score ?? 0,
              risk_tier:
                msg.risk_tier ||
                (msg.score && msg.score >= 70 ? 'HIGH' : msg.score && msg.score >= 40 ? 'MEDIUM' : 'LOW'),
              confidence: msg.confidence ?? 0,
              evidence: msg.evidence || [],
              extracted_entities: {
                phone_numbers: msg.extracted_entities?.phone_numbers || [],
                urls: msg.extracted_entities?.urls || [],
                bank_accounts: msg.extracted_entities?.bank_accounts || [],
              },
              ts: new Date().toLocaleTimeString(),
            };
            if (msg.reason === 'call_end') {
              setDeepAnalysis(analysis);
              setAwaitingFinalAnalysis(false);
              if (finalAnalysisTimerRef.current !== null) {
                window.clearTimeout(finalAnalysisTimerRef.current);
                finalAnalysisTimerRef.current = null;
              }
              eventsWsClientRef.current.close();
            } else {
              // Mid-call escalation snapshot — don't overwrite a final verdict
              setDeepAnalysis((prev) => (prev && prev.reason === 'call_end' ? prev : analysis));
            }
            setStatusLog((prev) => [
              ...prev,
              `🧠 [DEEP PHISHING ANALYSIS (${msg.reason})] score=${msg.score} tier=${msg.risk_tier}${msg.research?.queried ? ` · 🔎 web research: ${(msg.research.queries || []).length} query(ies), ${(msg.research.web_hits || []).length} hit(s)` : ''}`,
            ]);
          }
          if (msg.type === 'mode_change' && msg.call_mode) {
            setCurrentMode(normalizeMode(msg.call_mode));
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
              `[PRE-CHECK] Blacklist Status: ${msg.blacklisted ? `BLACKLISTED (${msg.blacklist_case_count || 0} Cases)` : 'CLEAN'}`,
            ]);
          }
          if (msg.type === 'talking' && msg.text) {
            addTranscript('ai', msg.text);
            setStatusLog((prev) => [
              ...prev,
              `🤖 [TRANSAFE AGENT]: "${msg.text}"${msg.action === 'hangup' ? ' 🚨 — scam confirmed, ending call' : ''}`,
            ]);
            if (msg.tts_id && msg.call_session_id) {
              // force=true for the hangup farewell so it interrupts ongoing speech
              playAgentSpeech(config.baseUrl, msg.call_session_id, msg.tts_id, config.apiKey, msg.action === 'hangup').catch(() => {});
            }
          }
          if (msg.type === 'call_ended') {
            audioStreamerRef.current.stopStreaming();
            setStreaming(false);
            setMicStatus('Call Ended by Peer');
            setSuspicionScore(0);
            setCallMode('copilot');
            setStatusLog((prev) => [...prev, '[CALL ENGINE] 📴 Call session ended by peer.']);
            // Do NOT close the WS — the backend broadcasts call_ended FIRST,
            // then runs final call-end deep analysis and broadcasts
            // deep_analysis (reason='call_end') AFTER. 60s safety net:
            setAwaitingFinalAnalysis(true);
            if (finalAnalysisTimerRef.current !== null) {
              window.clearTimeout(finalAnalysisTimerRef.current);
            }
            finalAnalysisTimerRef.current = window.setTimeout(() => {
              eventsWsClientRef.current.close();
              finalAnalysisTimerRef.current = null;
              setAwaitingFinalAnalysis(false);
            }, 60000);
          }
        },
        (err) => setStatusLog((prev) => [...prev, `[EVENTS WS ERROR] ${err}`]),
        () => {}
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
        (status) => setMicStatus(status),
        (err) => setStatusLog((prev) => [...prev, `[MICROPHONE ERROR] ${err}`])
      );

      setStreaming(true);
    } catch (err: any) {
      setStatusLog((prev) => [...prev, `Accept call failed: ${err.message}`]);
    }
  };

  const handleDeclineCall = async () => {
    if (!incomingCall) return;
    try {
      await client.declineCall(incomingCall.call_session_id);
      setStatusLog((prev) => [...prev, `[CALL ENGINE] Call ${incomingCall.call_session_id} declined.`]);
    } catch (e) {}
    setIncomingCall(null);
  };

  // Accept the call AND immediately switch to AUTO_TALK so the AI agent
  // starts speaking on its own. We pass the session id directly to avoid
  // the stale-state race where activeCallSessionId is not yet committed.
  const handleAcceptThenAutoTalk = async () => {
    if (!incomingCall) return;
    const callSessionId = incomingCall.call_session_id;
    await handleAcceptCall();
    await handleTakeover(callSessionId);
  };

  const handleTakeover = async (sessionIdOverride?: string) => {
    const targetSessionId = sessionIdOverride || activeCallSessionId;
    if (!targetSessionId) return;
    try {
      setStatusLog((prev) => [...prev, '[AGENT TAKEOVER] Triggering AI Agent mid-call takeover (switch to AUTO_TALK)...']);
      const res = await client.takeoverCall(targetSessionId);
      setCurrentMode('autotalk');
      setCallMode('autotalk');
      setStatusLog((prev) => [...prev, `[AGENT TAKEOVER] AI Agent active: ${res.message}`]);
    } catch (err: any) {
      setStatusLog((prev) => [...prev, `Takeover failed: ${err.message}`]);
    }
  };

  const handleEndCall = () => {
    audioStreamerRef.current.stopStreaming();
    eventsWsClientRef.current.close();
    setStreaming(false);
    setMicStatus('Call Ended');
    setStatusLog((prev) => [...prev, '[CALL ENGINE] Call session ended manually.']);
  };



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

  // Deep Phishing Analysis verdict panel. Rendered in BOTH the active-call
  // dashboard and the post-call "no active call" view so a final verdict that
  // arrives AFTER call_ended is still shown to the user.
  const renderDeepAnalysisPanel = () => {
    if (!deepAnalysis) return null;
    return (
      <div style={{ marginBottom: '24px', padding: '16px', borderRadius: '12px', backgroundColor: 'rgba(127, 29, 29, 0.5)', border: '1px solid #7f1d1d', color: '#fecaca' }}>
        <h4 style={{ fontSize: '12px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#f87171', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>psychology</span>
          Deep Phishing Analysis ({deepAnalysis.reason})
        </h4>
        <p style={{ fontSize: '13px', marginBottom: '8px' }}>
          Score: <strong style={{ color: deepAnalysis.score >= 70 ? '#f87171' : '#fbbf24' }}>{deepAnalysis.score}/100</strong> ({deepAnalysis.risk_tier}) • Confidence: {Math.round((deepAnalysis.confidence || 0) * 100)}%
        </p>
        {deepAnalysis.evidence.length > 0 && (
          <ul style={{ fontSize: '12px', color: '#fca5a5', paddingLeft: '16px', margin: 0, display: 'flex', flexDirection: 'column', gap: '2px' }}>
            {deepAnalysis.evidence.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        )}
      </div>
    );
  };

  const activeMode = streaming ? currentMode : callMode;

  return (
    <div className="dark-container" style={{ minHeight: '100vh', paddingBottom: '100px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <div className="header-padding-wrapper" style={{ width: '100%', paddingTop: '16px' }}>
        <UserHeader title="Safety Copilot" showBack={true} />
      </div>
      <div style={{ width: '100%', maxWidth: '768px', padding: '0 16px' }}>
        {/* ======================================================
            1. INCOMING CALL HUD MODAL
           ====================================================== */}
        {incomingCall && !streaming && (
          <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.8)', backdropFilter: 'blur(8px)', zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
            <div className="dark-card" style={{ textAlign: 'center', padding: '32px', width: '100%', maxWidth: '448px' }}>
              <div style={{ width: '96px', height: '96px', backgroundColor: 'rgba(37, 99, 235, 0.2)', color: '#3b82f6', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 24px', animation: 'pulse-red 2s infinite' }}>
                <span className="material-symbols-outlined" style={{ fontSize: '48px' }}>phone_callback</span>
              </div>

              <h2 style={{ fontSize: '24px', fontWeight: 800, color: '#ffffff', marginBottom: '4px' }}>{incomingCall.caller_name}</h2>
              <p style={{ fontSize: '12px', color: '#60a5fa', fontFamily: 'monospace', marginBottom: '16px' }}>
                {incomingCall.caller_number} • Secure WebRTC Call Session
              </p>

              <div style={{ padding: '12px', backgroundColor: 'rgba(127, 29, 29, 0.6)', border: '1px solid rgba(153, 27, 27, 0.6)', borderRadius: '12px', color: '#fca5a5', fontSize: '12px', marginBottom: '32px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="material-symbols-outlined" style={{ color: '#f87171' }}>warning</span>
                <span>TranSafe AI is monitoring this incoming call session. Caller ID may be spoofed.</span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ display: 'flex', gap: '12px' }}>
                  <button
                    onClick={handleAcceptCall}
                    className="btn-primary"
                    style={{ flex: 1, padding: '14px', fontSize: '14px', justifyContent: 'center', backgroundColor: '#059669', boxShadow: 'none' }}
                    onMouseEnter={e => { e.currentTarget.style.backgroundColor = '#047857'; }}
                    onMouseLeave={e => { e.currentTarget.style.backgroundColor = '#059669'; }}
                  >
                    <span className="material-symbols-outlined">headset_mic</span>
                    Listen & Monitor
                  </button>

                  <button
                    onClick={handleAcceptThenAutoTalk}
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
                  onClick={handleDeclineCall}
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
        {streaming ? (
          <div className="dark-card" style={{ padding: '24px' }}>
            {/* Call Header */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', borderBottom: '1px solid #374151', paddingBottom: '16px', marginBottom: '24px' }}>
              <div style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <span style={{ width: '12px', height: '12px', backgroundColor: '#ef4444', borderRadius: '50%', animation: 'ping 1.5s infinite' }}></span>
                    <h2 style={{ fontSize: '20px', fontWeight: 700, color: '#ffffff', margin: 0 }}>
                      {incomingCall?.caller_name || callerName}
                    </h2>
                  </div>
                  <p style={{ fontSize: '12px', color: '#9ca3af', marginTop: '4px', fontFamily: 'monospace' }}>
                    {activeCallSessionId} • Mode: <strong style={{ color: '#60a5fa', textTransform: 'uppercase' }}>{activeMode === 'autotalk' ? 'AUTO_TALK' : 'LISTEN'}</strong> • WebRTC Encrypted Stream
                  </p>
                  <p style={{ fontSize: '11px', color: '#6b7280', marginTop: '4px', fontFamily: 'monospace' }}>
                    Mic: {micStatus} {awaitingFinalAnalysis && '• ⏳ Final verdict pending...'}
                  </p>
                </div>

                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {activeMode === 'copilot' ? (
                    <button
                      onClick={() => handleTakeover()}
                      className="btn-secondary"
                      style={{ padding: '8px 12px', fontSize: '12px', backgroundColor: 'rgba(30, 58, 138, 0.4)', color: '#93c5fd', border: '1px solid #1d4ed8' }}
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>smart_toy</span>
                      Switch to Auto-Talk
                    </button>
                  ) : (
                    <span className="dark-badge-pass" style={{ padding: '8px 12px', fontSize: '12px', alignSelf: 'center' }}>
                      AI Agent Speaking
                    </span>
                  )}

                  <button onClick={handleEndCall} className="btn-danger" style={{ padding: '8px 16px', fontSize: '12px' }}>
                    <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>call_end</span>
                    End Call
                  </button>
                </div>
              </div>
            </div>

            {/* Blacklisted Caller Warning */}
            {preCheck?.blacklisted && (
              <div style={{ padding: '16px', borderRadius: '12px', backgroundColor: 'rgba(127, 29, 29, 0.8)', border: '2px solid #dc2626', color: '#fecaca', marginBottom: '24px', display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                <span className="material-symbols-outlined" style={{ color: '#ef4444', fontSize: '24px' }}>gpp_bad</span>
                <div>
                  <h4 style={{ fontWeight: 700, fontSize: '14px', margin: 0 }}>⚠️ BLACKLISTED CALLER DETECTED!</h4>
                  <p style={{ fontSize: '12px', marginTop: '2px', opacity: 0.9 }}>
                    {preCheck.warning || `This number is linked to ${preCheck.blacklist_cases || 0} fraud case(s) in the database.`}
                  </p>
                </div>
              </div>
            )}

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
            {activeMode === 'autotalk' && (
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
                        className="dark-badge-pending"
                        style={{ padding: '2px 8px', borderRadius: '4px', fontWeight: 700, textTransform: 'uppercase', fontSize: '10px', whiteSpace: 'nowrap' }}
                      >
                        {anchor.status}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Deep Analysis Final Verdict */}
            {renderDeepAnalysisPanel()}

            {/* Live Transcript Container */}
            <div>
              <h4 style={{ fontSize: '12px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#9ca3af', marginBottom: '12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>Live Speech Transcript & Threat Highlights</span>
                <span style={{ fontSize: '10px', color: '#6b7280', fontFamily: 'monospace' }}>Whisper STT Stream</span>
              </h4>

              <div style={{ backgroundColor: '#0b0f19', padding: '16px', borderRadius: '16px', border: '1px solid #374151', maxHeight: '320px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {transcripts.length === 0 ? (
                  <p style={{ fontSize: '12px', color: '#6b7280', textAlign: 'center', padding: '32px 0' }}>
                    Listening to incoming audio stream... (Trigger speech from Scammer Simulator)
                  </p>
                ) : (
                  transcripts.map((line) => (
                    <div
                      key={line.id}
                      className={`speech-bubble ${line.speaker === 'caller' ? 'caller' : line.speaker === 'ai' ? 'ai' : 'user'}`}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '10px', opacity: 0.6, marginBottom: '4px', fontFamily: 'monospace' }}>
                        <span style={{ fontWeight: 700, textTransform: 'uppercase' }}>
                          {line.speaker === 'caller'
                            ? 'Caller (Scammer)'
                            : line.speaker === 'ai'
                            ? 'AI Agent'
                            : 'User'}
                        </span>
                        <span>{line.ts}</span>
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
          <div className="dark-card" style={{ textAlign: 'center', padding: '24px' }}>
            {/* Show the final deep-phishing verdict even after the call ends,
                since call_ended is broadcast BEFORE the call-end analysis. */}
            {awaitingFinalAnalysis && !deepAnalysis && (
              <div style={{ padding: '16px', borderRadius: '12px', backgroundColor: 'rgba(30, 58, 138, 0.4)', border: '1px solid #1d4ed8', color: '#93c5fd', marginBottom: '24px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
                <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>hourglass_top</span>
                Call ended — running final deep phishing analysis...
              </div>
            )}
            {renderDeepAnalysisPanel()}
            <div style={{ width: '80px', height: '80px', backgroundColor: '#1f2937', color: '#9ca3af', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 24px' }}>
              <span className="material-symbols-outlined" style={{ fontSize: '36px' }}>phone_disabled</span>
            </div>
            <h2 style={{ fontSize: '24px', fontWeight: 700, color: '#ffffff', marginBottom: '8px' }}>No Active Call Session</h2>
            <p style={{ fontSize: '12px', color: '#9ca3af', maxWidth: '448px', margin: '0 auto 32px' }}>
              TranSafe Real-Time Safety Copilot will automatically intercept incoming phone calls, transcribe conversations, and highlight scam keyphrases.
            </p>
            <div style={{ display: 'flex', gap: '16px', justifyContent: 'center', flexWrap: 'wrap' }}>
              <button
                onClick={() => window.open('/scammer', '_blank')}
                className="btn-primary"
                style={{ padding: '14px 24px', justifyContent: 'center', backgroundColor: '#dc2626', color: '#fff', border: 'none', display: 'inline-flex' }}
                onMouseEnter={e => { e.currentTarget.style.backgroundColor = '#b91c1c'; }}
                onMouseLeave={e => { e.currentTarget.style.backgroundColor = '#dc2626'; }}
              >
                <span className="material-symbols-outlined">terminal</span>
                Open Scammer Simulator
              </button>
            </div>
          </div>
        )}

        {/* Backend Action Progress & Pipeline Tracker Panel */}
        {statusLog.length > 0 && (
          <div className="dark-card" style={{ padding: '16px', marginTop: '16px' }}>
            <h4 style={{ fontSize: '12px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#60a5fa', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>terminal</span>
              Backend Action Progress & Multi-Agent Pipeline Tracker
            </h4>
            <div style={{ maxHeight: '180px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '4px' }}>
              {statusLog.map((log, idx) => (
                <div key={idx} style={{ fontSize: '11px', fontFamily: 'monospace', color: log.startsWith('❌') ? '#f87171' : '#9ca3af' }}>
                  ▸ {log}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
