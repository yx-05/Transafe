import React, { useState, useRef, useEffect } from 'react';
import type { BackendConfig, CallMode, WsCallEventMessage } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { CallAudioStreamer, playAgentSpeech } from '../../services/audioRecorder';
import { CallEventsWebSocketClient } from '../../services/websocket';
import { PhoneCall, Mic, MicOff, Radio, CheckCircle2, PhoneIncoming, XCircle, CheckCircle, Terminal, Zap } from 'lucide-react';

interface StepByStepUserCallProps {
  config: BackendConfig;
  userId: string;
}

interface DeepAnalysisResult {
  reason: string;
  score: number;
  risk_tier: string;
  confidence: number;
  evidence: string[];
  extracted_entities: { phone_numbers: string[]; urls: string[]; bank_accounts: string[] };
  research?: {
    queried: boolean;
    decision?: string;
    reasoning?: string;
    queries: string[];
    web_hits: Array<{ title?: string; url?: string }>;
  };
  ts: string;
}

export const StepByStepUserCall: React.FC<StepByStepUserCallProps> = ({
  config,
  userId,
}) => {
  // Step States
  const [currentStep, setCurrentStep] = useState<1 | 2 | 3 | 4>(1);
  const [activeCallSessionId, setActiveCallSessionId] = useState<string | null>(null);
  const [micStatus, setMicStatus] = useState<string>('Not Connected');
  const [incomingCall, setIncomingCall] = useState<{
    call_session_id: string;
    caller_number: string;
    caller_name: string;
  } | null>(null);

  // Transcripts & Suspicion — detection results are shown HERE only (matches real frontend CallActivePage)
  const [transcripts, setTranscripts] = useState<Array<{ speaker: string; text: string; ts: string; highlights?: Array<{ phrase: string; tag: string }> }>>([]);
  const [suspicionScore, setSuspicionScore] = useState<number>(0);
  const [deepAnalysis, setDeepAnalysis] = useState<DeepAnalysisResult | null>(null);
  const [callMode, setCallMode] = useState<CallMode>('LISTEN');

  // Diagnostic Step Logs
  const [stepLogs, setStepLogs] = useState<string[]>([
    `Step-by-Step Customer Test Lab Ready. Monitoring active calls for User ${userId}...`,
  ]);

  const audioStreamerRef = useRef<CallAudioStreamer>(new CallAudioStreamer());
  const eventsWsClientRef = useRef<CallEventsWebSocketClient>(new CallEventsWebSocketClient());

  useEffect(() => {
    return () => {
      audioStreamerRef.current.stopStreaming();
      eventsWsClientRef.current.close();
    };
  }, []);

  const addLog = (msg: string) => {
    setStepLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
  };

  const getSuspicionColor = (score: number) => {
    if (score > 70) return '#ef4444';
    if (score > 35) return '#f59e0b';
    return '#10b981';
  };

  // Inline phrase highlighting (matches real frontend renderHighlightedText)
  const renderHighlightedText = (text: string, highlights?: Array<{ phrase: string; tag: string }>) => {
    if (!highlights || highlights.length === 0) return text;

    let parts: Array<{ text: string; isHighlight: boolean; tag?: string }> = [{ text, isHighlight: false }];

    highlights.forEach(({ phrase, tag }) => {
      const nextParts: typeof parts = [];
      parts.forEach((part) => {
        if (part.isHighlight) {
          nextParts.push(part);
        } else {
          const index = part.text.toLowerCase().indexOf(phrase.toLowerCase());
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

  // STEP 1: Listen for Ringing Call from Scammer
  useEffect(() => {
    if (currentStep >= 3) return;
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

          addLog(`🔔 [STEP 1 DETECTED] Ringing call from ${name} (${number}). Call Session ID: ${callId}`);
        }
      } catch (e) {}
    }, 1500);

    return () => clearInterval(interval);
  }, [config.baseUrl, userId, currentStep, incomingCall]);

  // STEP 1: Answer Call
  const handleStep1AnswerCall = async () => {
    if (!incomingCall) return;
    const client = new TranSafeApiClient(config);
    const callSessionId = incomingCall.call_session_id;

    addLog(`[STEP 1] Answering call session ${callSessionId}...`);
    setTranscripts([]);
    setSuspicionScore(0);
    setDeepAnalysis(null);
    // A new call always starts in LISTEN — the Takeover button must show again
    // even if the previous call ended in AUTO_TALK. (The backend re-broadcasts
    // mode_change=AUTO_TALK right after the events WS connects if it auto-engaged.)
    setCallMode('LISTEN');

    try {
      await client.answerCall(callSessionId);
      setActiveCallSessionId(callSessionId);
      setIncomingCall(null);
      setCurrentStep(2);

      addLog(`✅ STEP 1 SUCCESS: Call answered! Session ID: ${callSessionId}. Ready for Step 2.`);

      // Connect Call Events WebSocket
      eventsWsClientRef.current.connect(
        config.baseUrl,
        callSessionId,
        config.apiKey,
        (msg: WsCallEventMessage) => {
          if (msg.type === 'transcript' && msg.text) {
            setTranscripts((prev) => [
              ...prev,
              { speaker: msg.speaker || 'SCAMMER', text: msg.text || '', ts: new Date().toLocaleTimeString() },
            ]);
            addLog(`[STT TRANSCRIPT] [${msg.speaker}]: "${msg.text}"`);
          }
          if (msg.type === 'highlight' && msg.highlighted_spans) {
            const spans = msg.highlighted_spans
              .filter((s) => s.phrase)
              .map((s) => ({ phrase: s.phrase, tag: s.tag || s.risk_level || 'THREAT' }));
            if (spans.length > 0) {
              // Attach spans inline to the transcript line for this utterance (real frontend style)
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
              spans.forEach((s) => addLog(`⚠️ [DANGER PHRASE] "${s.phrase}"`));
            }
          }
          if (msg.type === 'suspicion_update') {
            setSuspicionScore(msg.suspicion_score ?? 0);
            addLog(`🚨 [PHONE AGENT SUSPICION ${msg.risk_tier}] cumulative=${msg.suspicion_score} utterance=${msg.utterance_risk_score}${msg.trigger_escalation ? ' — ⚠️ ESCALATED (HIGH)' : ''}`);
          }
          if (msg.type === 'deep_analysis') {
            setDeepAnalysis({
              reason: msg.reason || 'call_end',
              score: msg.score ?? 0,
              risk_tier: msg.risk_tier || (msg.score && msg.score >= 70 ? 'HIGH' : msg.score && msg.score >= 40 ? 'MEDIUM' : 'LOW'),
              confidence: msg.confidence ?? 0,
              evidence: msg.evidence || [],
              extracted_entities: {
                phone_numbers: msg.extracted_entities?.phone_numbers || [],
                urls: msg.extracted_entities?.urls || [],
                bank_accounts: msg.extracted_entities?.bank_accounts || [],
              },
              research: msg.research
                ? {
                    queried: !!msg.research.queried,
                    decision: msg.research.decision,
                    reasoning: msg.research.reasoning,
                    queries: msg.research.queries || [],
                    web_hits: msg.research.web_hits || [],
                  }
                : undefined,
              ts: new Date().toLocaleTimeString(),
            });
            addLog(`🧠 [DEEP PHISHING ANALYSIS (${msg.reason})] score=${msg.score} tier=${msg.risk_tier}${msg.research?.queried ? ` · 🔎 web research: ${(msg.research.queries || []).length} query(ies), ${(msg.research.web_hits || []).length} hit(s)` : ''}`);
          }
          if (msg.type === 'mode_change' && msg.call_mode) {
            setCallMode(msg.call_mode);
            addLog(`🤖 [COPILOT] Call mode updated to: ${msg.call_mode}`);
          }
          if (msg.type === 'talking' && msg.text) {
            setTranscripts((prev) => [
              ...prev,
              { speaker: 'TRANSAFE_AI', text: msg.text || '', ts: new Date().toLocaleTimeString() },
            ]);
            addLog(`🤖 [TRANSAFE AGENT]: "${msg.text}"${msg.action === 'hangup' ? ' 🚨 — scam confirmed, ending call' : ''}`);
            if (msg.tts_id && msg.call_session_id) {
              // Use the session id from the event itself — `activeCallSessionId`
              // captured in this WS callback closure is STALE (pre-answer / null),
              // which would fetch /api/v1/call/null/tts/... → 404 → silent.
              playAgentSpeech(config.baseUrl, msg.call_session_id, msg.tts_id, config.apiKey).catch(() => {});
            }
          }
          if (msg.type === 'call_ended') {
            audioStreamerRef.current.stopStreaming();
            eventsWsClientRef.current.close();
            setCurrentStep(1);
            setActiveCallSessionId(null);
            setMicStatus('Not Connected');
            setSuspicionScore(0);
            setTranscripts([]);
            setCallMode('LISTEN');
            // Keep deepAnalysis so the final call-end verdict stays visible
            // for review after the UI resets to Step 1.
            addLog('📴 Call ended. 🧠 Final deep analysis retained below.');
          }
        },
        (err) => addLog(`[EVENTS WS ERROR] ${err}`),
        () => addLog('[EVENTS WS] Connection closed.')
      );
    } catch (err: any) {
      addLog(`❌ STEP 1 ERROR: ${err.message}`);
    }
  };

  // STEP 1: Decline Call
  const handleStep1DeclineCall = async () => {
    if (!incomingCall) return;
    const client = new TranSafeApiClient(config);
    try {
      await client.declineCall(incomingCall.call_session_id);
      addLog(`Call ${incomingCall.call_session_id} declined.`);
    } catch (e) {}
    setIncomingCall(null);
  };

  // STEP 2: Connect Customer Microphone
  const handleStep2ConnectMic = async () => {
    if (!activeCallSessionId) return;
    addLog('[STEP 2] Requesting Customer Microphone permission & connecting WebSockets...');

    try {
      await audioStreamerRef.current.startStreaming(
        config.baseUrl,
        activeCallSessionId,
        config.apiKey,
        'CUSTOMER',
        (status) => {
          setMicStatus(status);
          addLog(`[AUDIO STREAM] ${status}`);
        },
        (err) => addLog(`❌ [MIC ERROR] ${err}`)
      );

      setCurrentStep(3);
      addLog('✅ STEP 2 SUCCESS: Customer microphone active! 2-way audio relay active. Step 3 live.');
    } catch (err: any) {
      addLog(`❌ STEP 2 ERROR: ${err.message}`);
    }
  };

  // STEP 3: AI Takeover → AUTO_TALK (TranSafe speaks to the caller on your behalf)
  const handleTakeover = async () => {
    if (!activeCallSessionId) return;
    const client = new TranSafeApiClient(config);
    try {
      addLog('[TAKEOVER] Switching call to AUTO_TALK — TranSafe agent takes over the conversation...');
      await client.takeoverCall(activeCallSessionId);
      setCallMode('AUTO_TALK');
      addLog('🤖 [AGENT TAKEOVER] TranSafe agent is now speaking to the caller on your behalf (AUTO_TALK).');
    } catch (err: any) {
      addLog(`❌ [TAKEOVER ERROR] ${err.message}`);
    }
  };

  // STEP 4: Hang Up Call
  const handleStep4HangUp = () => {
    addLog('[STEP 4] Hanging up call session...');
    const currentId = activeCallSessionId;

    // 1. Stop audio instantly (0ms latency), but KEEP the events WS open so the
    //    backend's call-end deep analysis (deep_analysis: call_end) can still
    //    arrive — the call_ended handler closes it once everything is received.
    audioStreamerRef.curr
    // Reset the mode so the next call shows the "Use agent to call" Takeover
    // button again instead of the stale AUTO_TALK badge.
    setCallMode('LISTEN');ent.stopStreaming();
    setCurrentStep(1);
    setActiveCallSessionId(null);
    setMicStatus('Not Connected');
    setSuspicionScore(0);
    // Keep deepAnalysis + transcripts for post-call review of the final verdict;
    // they are cleared automatically when the next call is answered.

    // 2. Fire backend call termination non-blockingly in background
    if (currentId) {
      const client = new TranSafeApiClient(config);
      client.declineCall(currentId).catch(() => {});
    }
    addLog('✅ STEP 4 SUCCESS: Call ended. Awaiting final deep analysis...');
  };

  const handleResetCalls = async () => {
    setIncomingCall(null);
    setDeepAnalysis(null);
    try {
      const client = new TranSafeApiClient(config);
      await client.post('/api/v1/call/reset', { user_id: userId });
    } catch (e) {}
    addLog('Cleared all lingering call sessions.');
  };

  return (
    <div className="card test-card">
      <div className="card-header">
        <div className="card-title">
          <PhoneCall className="card-icon" size={20} />
          <h3>Step-by-Step Customer Call Test Lab</h3>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <button className="btn-secondary" style={{ padding: '0.3rem 0.6rem', fontSize: '0.75rem' }} onClick={handleResetCalls}>
            Clear Calls
          </button>
          <span className="card-tag">CUSTOMER ROLE (STEP-BY-STEP)</span>
        </div>
      </div>

      {/* STEP PROGRESS INDICATOR */}
      <div className="step-progress-bar">
        <div className={`step-item ${currentStep >= 1 ? 'active' : ''}`}>
          <span className="step-num">1</span>
          <span className="step-label">Ringing & Answer</span>
        </div>
        <div className={`step-item ${currentStep >= 2 ? 'active' : ''}`}>
          <span className="step-num">2</span>
          <span className="step-label">Connect Mic</span>
        </div>
        <div className={`step-item ${currentStep >= 3 ? 'active' : ''}`}>
          <span className="step-num">3</span>
          <span className="step-label">Live 2-Way Audio</span>
        </div>
        <div className={`step-item ${currentStep >= 4 ? 'active' : ''}`}>
          <span className="step-num">4</span>
          <span className="step-label">Hang Up</span>
        </div>
      </div>

      {/* INCOMING RINGING CALL MODAL */}
      {incomingCall && currentStep === 1 && (
        <div className="incoming-call-modal">
          <div className="incoming-call-content">
            <PhoneIncoming size={32} className="pulse text-red" />
            <div className="call-info">
              <h4>📞 INCOMING CALL FROM SCAMMER</h4>
              <p><strong>{incomingCall.caller_name}</strong> ({incomingCall.caller_number})</p>
              <small>Call Session ID: <code>{incomingCall.call_session_id}</code></small>
            </div>
            <div className="incoming-call-actions">
              <button className="btn-success" onClick={handleStep1AnswerCall}>
                <CheckCircle size={16} /> 1. Answer Call
              </button>
              <button className="btn-danger" onClick={handleStep1DeclineCall}>
                <XCircle size={16} /> Decline
              </button>
            </div>
          </div>
        </div>
      )}

      {currentStep === 1 && !incomingCall && (
        <div className="placeholder-box">
          <p>Waiting for Scammer to initiate a call from the Scammer Workbench page...</p>
        </div>
      )}

      {/* STEP 2 CONTROLS */}
      {currentStep === 2 && (
        <div className="step-action-box">
          <h4><CheckCircle2 size={18} className="text-green" /> Step 1 Complete: Call Answered!</h4>
          <p>Active Session ID: <code>{activeCallSessionId}</code></p>
          <button className="btn-primary" onClick={handleStep2ConnectMic}>
            <Mic size={16} /> 2. Connect Customer Microphone & 2-Way Relay
          </button>
        </div>
      )}

      {/* STEP 3 & 4 LIVE CALL CONTROLS */}
      {currentStep >= 3 && (
        <div className="active-call-panel">
          <div className="call-status-bar">
            <div className="status-live">
              <Radio className="pulse text-red" size={18} />
              <span>LIVE CALL: <code>{activeCallSessionId}</code></span>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              {callMode === 'LISTEN' ? (
                <button className="btn-warning" onClick={handleTakeover}>
                  <Zap size={16} /> 🤖 Takeover (AI speaks)
                </button>
              ) : (
                <span className="badge" style={{ padding: '0.35rem 0.75rem', borderRadius: '9999px', backgroundColor: 'rgba(217, 119, 6, 0.2)', border: '1px solid #f59e0b', color: '#fbbf24', fontSize: '0.8rem', fontWeight: 700 }}>
                  🤖 AUTO_TALK — TranSafe is speaking for you
                </span>
              )}
              <button className="btn-danger" onClick={handleStep4HangUp}>
                <MicOff size={16} /> 4. Hang Up Call
              </button>
            </div>
          </div>

          <div className="audio-stream-status">
            <strong>Customer Microphone Status:</strong> {micStatus}
          </div>

          {/* Suspicion Score Gauge (matches real frontend CallActivePage) */}
          <div style={{ marginBottom: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px', color: '#9ca3af' }}>
              <span>Call Suspicion Level</span>
              <span style={{ color: getSuspicionColor(suspicionScore), fontSize: '14px', fontWeight: 800 }}>
                {suspicionScore} / 100
              </span>
            </div>
            <div style={{ width: '100%', height: '12px', backgroundColor: 'rgba(255,255,255,0.1)', borderRadius: '9999px', overflow: 'hidden' }}>
              <div
                style={{
                  height: '100%',
                  width: `${suspicionScore}%`,
                  backgroundColor: getSuspicionColor(suspicionScore),
                  transition: 'width 0.5s',
                }}
              />
            </div>
          </div>

          {/* High Suspicion Alert Banner */}
          {suspicionScore >= 70 && (
            <div style={{ padding: '12px', borderRadius: '12px', backgroundColor: 'rgba(127, 29, 29, 0.8)', border: '2px solid #dc2626', color: '#fecaca', marginBottom: '16px', display: 'flex', alignItems: 'flex-start', gap: '12px', animation: 'pulse-red 2s infinite' }}>
              <span style={{ color: '#ef4444', fontSize: '24px' }}>⚠️</span>
              <div>
                <h4 style={{ fontWeight: 700, fontSize: '14px', margin: 0 }}>HIGH SCAM PROBABILITY DETECTED</h4>
                <p style={{ fontSize: '12px', marginTop: '2px', opacity: 0.9 }}>
                  Caller is using authority impersonation and coercion techniques. Do NOT perform any bank transfer!
                </p>
              </div>
            </div>
          )}

          {/* Live Speech Transcript & Threat Highlights (inline highlighted bubbles, matches real frontend) */}
          <div className="transcript-box">
            <h4>Live Speech Transcript & Threat Highlights</h4>
            <div className="transcript-lines" style={{ maxHeight: '240px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {transcripts.length === 0 ? (
                <p className="placeholder-text">Listening to incoming audio stream... Transcripts & threat highlights appear live.</p>
              ) : (
                transcripts.map((t, idx) => (
                  <div
                    key={idx}
                    className={`speech-bubble ${t.speaker === 'CUSTOMER' ? 'user' : t.speaker === 'TRANSAFE_AI' ? 'agent' : 'caller'}`}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', opacity: 0.6, marginBottom: '4px', fontFamily: 'monospace' }}>
                      <span style={{ fontWeight: 700, textTransform: 'uppercase' }}>
                        {t.speaker === 'CUSTOMER' ? 'User (Customer)' : t.speaker === 'SCAMMER' ? 'Caller (Scammer)' : t.speaker === 'TRANSAFE_AI' ? '🤖 TranSafe Agent' : t.speaker}
                      </span>
                      <span>{t.ts}</span>
                    </div>
                    <p style={{ margin: 0 }}>{renderHighlightedText(t.text, t.highlights)}</p>
                  </div>
                ))
              )}
            </div>
          </div>

        </div>
      )}

      {/* Deep Phishing Analysis (async Phishing Worker verdict — separate from live gauge).
          Rendered OUTSIDE the step>=3 block so it stays visible after the call ends
          (post-call review of the final call-end verdict). */}
      {deepAnalysis && (
        <div style={{ marginTop: '16px', padding: '12px', borderRadius: '12px', backgroundColor: 'rgba(15, 23, 42, 0.7)', border: `1px solid ${deepAnalysis.score >= 70 ? '#dc2626' : deepAnalysis.score >= 40 ? '#d97706' : '#10b981'}` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <h4 style={{ margin: 0, fontSize: '13px', fontWeight: 700 }}>🧠 Deep Phishing Analysis</h4>
            <span style={{ fontSize: '10px', opacity: 0.6, fontFamily: 'monospace' }}>{deepAnalysis.ts}</span>
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap', marginBottom: '8px' }}>
            <span style={{ padding: '3px 10px', borderRadius: '9999px', fontSize: '12px', fontWeight: 800, color: '#fff', backgroundColor: deepAnalysis.score >= 70 ? '#dc2626' : deepAnalysis.score >= 40 ? '#d97706' : '#10b981' }}>
              {deepAnalysis.score} / 100 · {deepAnalysis.risk_tier}
            </span>
            <span style={{ fontSize: '11px', color: '#9ca3af' }}>
              {deepAnalysis.reason === 'escalation' ? '⚠️ Triggered on mid-call high-risk escalation' : '🏁 Final deep analysis (call ended)'}
            </span>
            <span style={{ fontSize: '11px', color: '#9ca3af' }}>confidence {(deepAnalysis.confidence * 100).toFixed(0)}%</span>
          </div>
          {deepAnalysis.evidence.length > 0 && (
            <ul style={{ margin: '0 0 8px 0', paddingLeft: '18px', fontSize: '12px', color: '#d1d5db' }}>
              {deepAnalysis.evidence.map((ev, i) => (
                <li key={i}>{ev}</li>
              ))}
            </ul>
          )}
          {(deepAnalysis.extracted_entities.phone_numbers.length > 0 || deepAnalysis.extracted_entities.urls.length > 0 || deepAnalysis.extracted_entities.bank_accounts.length > 0) && (
            <div style={{ fontSize: '11px', color: '#9ca3af' }}>
              <strong style={{ color: '#e5e7eb' }}>Extracted entities:</strong>{' '}
              {deepAnalysis.extracted_entities.phone_numbers.length > 0 && <span>📞 {deepAnalysis.extracted_entities.phone_numbers.join(', ')} </span>}
              {deepAnalysis.extracted_entities.urls.length > 0 && <span>🔗 {deepAnalysis.extracted_entities.urls.join(', ')} </span>}
              {deepAnalysis.extracted_entities.bank_accounts.length > 0 && <span>🏦 {deepAnalysis.extracted_entities.bank_accounts.join(', ')} </span>}
            </div>
          )}
          {deepAnalysis.research && deepAnalysis.research.queried && (
            <div style={{ marginTop: '8px', padding: '8px 10px', borderRadius: '8px', backgroundColor: 'rgba(59, 130, 246, 0.08)', border: '1px solid rgba(59, 130, 246, 0.25)' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#60a5fa', marginBottom: '4px' }}>
                🔎 Online research {deepAnalysis.research.web_hits.length > 0 ? `· ${deepAnalysis.research.web_hits.length} hit(s) found` : '· no external hits'}
              </div>
              {deepAnalysis.research.queries.length > 0 && (
                <div style={{ fontSize: '11px', color: '#9ca3af', marginBottom: '4px' }}>
                  <strong style={{ color: '#e5e7eb' }}>Queries:</strong> {deepAnalysis.research.queries.join(' · ')}
                </div>
              )}
              {deepAnalysis.research.web_hits.length > 0 && (
                <ul style={{ margin: '4px 0 0 0', paddingLeft: '16px', fontSize: '11px', color: '#d1d5db' }}>
                  {deepAnalysis.research.web_hits.map((hit, i) => (
                    <li key={i}>
                      {hit.title || 'External report'}{' '}
                      {hit.url && (
                        <a href={hit.url} target="_blank" rel="noreferrer" style={{ color: '#60a5fa', wordBreak: 'break-all' }}>
                          ({hit.url})
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {/* STEP DIAGNOSTIC LOG BOX */}
      <div className="status-progress-panel" style={{ marginTop: '1rem' }}>
        <div className="progress-header">
          <Terminal className="icon text-blue" size={16} />
          <h4>Step-by-Step Diagnostic Logs</h4>
        </div>
        <div className="status-log-box" style={{ maxHeight: '160px', overflowY: 'auto' }}>
          {stepLogs.map((log, idx) => (
            <div key={idx} className="status-log-item">
              <span>{log}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
