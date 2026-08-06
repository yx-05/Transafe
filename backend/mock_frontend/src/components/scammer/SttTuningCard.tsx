import React, { useState, useRef, useEffect } from 'react';
import type { BackendConfig, WsCallEventMessage } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { CallAudioStreamer } from '../../services/audioRecorder';
import { CallEventsWebSocketClient } from '../../services/websocket';
import { Mic, MicOff, Radio, Activity, Sliders, Play, Loader2 } from 'lucide-react';

interface SttTuningCardProps {
  config: BackendConfig;
  victimUserId: string;
}

export const SttTuningCard: React.FC<SttTuningCardProps> = ({
  config,
  victimUserId,
}) => {
  const [callSessionId, setCallSessionId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [micStatus, setMicStatus] = useState<string>('Idle');
  const [sttState, setSttState] = useState<'idle' | 'transcribing'>('idle');
  const [sttEngine, setSttEngine] = useState<'nova-3' | 'groq'>('nova-3');

  // Mic level meter volume state (0 - 100)
  const [micVolume, setMicVolume] = useState<number>(0);

  // Transcripts & Highlights
  const [transcripts, setTranscripts] = useState<Array<{ speaker: string; text: string; ts: string; interim?: boolean }>>([]);
  const [highlights, setHighlights] = useState<Array<{ phrase: string; reason: string }>>([]);
  const [suspicion, setSuspicion] = useState<{ score: number; tier: 'LOW' | 'MEDIUM' | 'HIGH'; escalated: boolean; lastScore: number }>({
    score: 0,
    tier: 'LOW',
    escalated: false,
    lastScore: 0,
  });
  const [logs, setLogs] = useState<string[]>([
    'Standalone STT Engine Tuning Lab Initialized.',
    'Dual STT Engine Support: Groq Whisper & Deepgram Nova-3 active.',
  ]);

  const audioStreamerRef = useRef<CallAudioStreamer>(new CallAudioStreamer());
  const eventsWsClientRef = useRef<CallEventsWebSocketClient>(new CallEventsWebSocketClient());

  // Web Audio Analyser for mic volume level meter
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      stopTuningSession();
    };
  }, []);

  const addLog = (msg: string) => {
    setLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
  };

  const meterStreamRef = useRef<MediaStream | null>(null);

  const startMicVolumeMeter = (stream: MediaStream) => {
    try {
      meterStreamRef.current = stream;
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      audioContextRef.current = new AudioCtx();
      const source = audioContextRef.current.createMediaStreamSource(stream);
      analyserRef.current = audioContextRef.current.createAnalyser();
      analyserRef.current.fftSize = 256;
      source.connect(analyserRef.current);

      const bufferLength = analyserRef.current.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      const updateVolume = () => {
        if (!analyserRef.current) return;
        analyserRef.current.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < bufferLength; i++) {
          sum += dataArray[i];
        }
        const average = sum / bufferLength;
        const volume = Math.min(100, Math.round((average / 128) * 100));
        setMicVolume(volume);
        animFrameRef.current = requestAnimationFrame(updateVolume);
      };

      updateVolume();
    } catch (e) {
      console.warn('Audio level meter error:', e);
    }
  };

  const stopMicVolumeMeter = () => {
    if (meterStreamRef.current) {
      meterStreamRef.current.getTracks().forEach((track) => track.stop());
      meterStreamRef.current = null;
    }
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    analyserRef.current = null;
    setMicVolume(0);
  };

  const handleSelectEngine = async (engine: 'nova-3' | 'groq') => {
    setSttEngine(engine);
    addLog(`Switched STT Engine to: ${engine.toUpperCase()}`);
    if (callSessionId) {
      try {
        const client = new TranSafeApiClient(config);
        await client.updateSttEngine(callSessionId, engine);
      } catch (e) {}
    }
  };

  const startTuningSession = async () => {
    setLogs([`Initializing Standalone STT Session (${sttEngine.toUpperCase()})...`]);
    const client = new TranSafeApiClient(config);
    const sessionId = `sess-stt-tune-${Date.now()}`;

    try {
      addLog(`Creating trigger session on ${config.baseUrl}...`);
      const res = await client.triggerCall({
        user_id: victimUserId,
        session_id: sessionId,
        call: {
          caller_number: '+60161234567',
          caller_name: 'STT Tuning Simulator',
          call_mode: 'LISTEN',
          call_channel: 'WEBRTC',
          received_at: new Date().toISOString(),
          stt_engine: sttEngine,
        } as any,
      });

      const callId = res.call_session_id;
      setCallSessionId(callId);
      addLog(`✅ Call registered: ${callId}`);

      // Set initial STT engine selection
      await client.updateSttEngine(callId, sttEngine).catch(() => {});

      // Answer call programmatically
      await client.answerCall(callId);
      addLog('✅ Call answered. Connecting WebSockets & microphone...');

      // Connect Events WebSocket
      eventsWsClientRef.current.connect(
        config.baseUrl,
        callId,
        config.apiKey,
        (msg: WsCallEventMessage) => {
          if (msg.type === 'stt_status') {
            setSttState(msg.status === 'transcribing' ? 'transcribing' : 'idle');
          }
          if (msg.type === 'transcript_interim' && msg.text) {
            // Live partial result: update the last line in-place
            setTranscripts((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.interim) {
                next[next.length - 1] = { ...last, text: msg.text || '' };
              } else {
                next.push({
                  speaker: msg.speaker || 'TESTER',
                  text: msg.text || '',
                  ts: new Date().toLocaleTimeString(),
                  interim: true,
                });
              }
              return next;
            });
          }
          if (msg.type === 'transcript' && msg.text) {
            // Final result: replace pending interim line, else append
            setTranscripts((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.interim) {
                next[next.length - 1] = {
                  speaker: msg.speaker || 'TESTER',
                  text: msg.text || '',
                  ts: new Date().toLocaleTimeString(),
                };
              } else {
                next.push({
                  speaker: msg.speaker || 'TESTER',
                  text: msg.text || '',
                  ts: new Date().toLocaleTimeString(),
                });
              }
              return next;
            });
            addLog(`✅ [STT TRANSCRIPT] [${msg.speaker}]: "${msg.text}"`);
          }
          if (msg.type === 'highlight' && msg.highlighted_spans) {
            const span = msg.highlighted_spans[0];
            if (span) {
              setHighlights((prev) => [...prev, { phrase: span.phrase, reason: span.reason }]);
              addLog(`⚠️ [DANGER PHRASE] "${span.phrase}"`);
            }
          }
          if (msg.type === 'suspicion_update') {
            setSuspicion({
              score: msg.suspicion_score ?? 0,
              tier: msg.risk_tier ?? 'LOW',
              escalated: !!msg.trigger_escalation,
              lastScore: msg.utterance_risk_score ?? 0,
            });
            addLog(`🚨 [PHONE AGENT SUSPICION ${msg.risk_tier}] cumulative=${msg.suspicion_score} utterance=${msg.utterance_risk_score}${msg.trigger_escalation ? ' — ⚠️ ESCALATED (HIGH)' : ''}`);
          }
        },
        (err) => addLog(`❌ [EVENTS WS ERROR] ${err}`),
        () => addLog('[EVENTS WS] Closed.')
      );

      // Start Audio Streamer
      await audioStreamerRef.current.startStreaming(
        config.baseUrl,
        callId,
        config.apiKey,
        'SCAMMER',
        (status) => {
          setMicStatus(status);
          addLog(`[AUDIO STREAM] ${status}`);
        },
        (err) => addLog(`❌ [AUDIO STREAM ERROR] ${err}`)
      );

      // Access stream for volume meter
      if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        startMicVolumeMeter(stream);
      }

      setIsStreaming(true);
      addLog('🚀 STT Tuning Lab Live! Speak into your microphone.');
    } catch (err: any) {
      addLog(`❌ INIT ERROR: ${err.message}`);
    }
  };

  const stopTuningSession = () => {
    stopMicVolumeMeter();
    audioStreamerRef.current.stopStreaming();
    eventsWsClientRef.current.close();
    if (callSessionId) {
      const client = new TranSafeApiClient(config);
      client.declineCall(callSessionId).catch(() => {});
    }
    setIsStreaming(false);
    setCallSessionId(null);
    setSttState('idle');
    setMicStatus('Idle');
    setSuspicion({ score: 0, tier: 'LOW', escalated: false, lastScore: 0 });
    addLog('📴 STT Tuning Session ended.');
  };

  return (
    <div className="card test-card scammer-card">
      <div className="card-header">
        <div className="card-title">
          <Sliders className="card-icon text-red" size={20} />
          <h3>🎙️ Standalone Groq STT Engine Tuning Lab</h3>
        </div>
        <span className="card-tag red">ASYNC GROQ + SILENCE VAD</span>
      </div>

      {/* STT ENGINE SELECTOR TOGGLE */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', background: 'rgba(15, 23, 42, 0.6)', padding: '0.4rem', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)' }}>
        <button
          onClick={() => handleSelectEngine('nova-3')}
          style={{
            flex: 1,
            padding: '0.45rem 0.8rem',
            borderRadius: '6px',
            border: 'none',
            fontSize: '0.85rem',
            fontWeight: '600',
            cursor: 'pointer',
            background: sttEngine === 'nova-3' ? 'linear-gradient(135deg, #10b981, #059669)' : 'transparent',
            color: sttEngine === 'nova-3' ? '#fff' : '#94a3b8',
            transition: 'all 0.2s ease',
          }}
        >
          ⚡ Deepgram Nova-3 (Recommended)
        </button>
        <button
          onClick={() => handleSelectEngine('groq')}
          style={{
            flex: 1,
            padding: '0.45rem 0.8rem',
            borderRadius: '6px',
            border: 'none',
            fontSize: '0.85rem',
            fontWeight: '600',
            cursor: 'pointer',
            background: sttEngine === 'groq' ? 'linear-gradient(135deg, #3b82f6, #2563eb)' : 'transparent',
            color: sttEngine === 'groq' ? '#fff' : '#94a3b8',
            transition: 'all 0.2s ease',
          }}
        >
          🎙️ Groq Whisper (Batch)
        </button>
      </div>

      {/* STT CONFIG & PARAMS PANEL */}
      <div className="stt-tuning-params" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem', marginBottom: '1rem' }}>
        <div className="param-badge" style={{ background: 'rgba(15, 23, 42, 0.7)', border: '1px solid rgba(255,255,255,0.1)', padding: '0.6rem', borderRadius: '8px', fontSize: '0.8rem' }}>
          <strong style={{ color: '#38bdf8', display: 'block' }}>Active STT Engine:</strong>
          <span>{sttEngine === 'nova-3' ? 'Deepgram Nova-3' : 'Groq Whisper'}</span>
        </div>
        <div className="param-badge" style={{ background: 'rgba(15, 23, 42, 0.7)', border: '1px solid rgba(255,255,255,0.1)', padding: '0.6rem', borderRadius: '8px', fontSize: '0.8rem' }}>
          <strong style={{ color: '#4ade80', display: 'block' }}>Smart Format:</strong>
          <span>Enabled (Real-Time)</span>
        </div>
        <div className="param-badge" style={{ background: 'rgba(15, 23, 42, 0.7)', border: '1px solid rgba(255,255,255,0.1)', padding: '0.6rem', borderRadius: '8px', fontSize: '0.8rem' }}>
          <strong style={{ color: '#f43f5e', display: 'block' }}>Language:</strong>
          <span>English ("en")</span>
        </div>
      </div>

      {/* START / STOP CONTROLS */}
      {!isStreaming ? (
        <button className="btn-primary" onClick={startTuningSession} style={{ background: 'linear-gradient(135deg, #ef4444, #dc2626)', width: '100%' }}>
          <Mic size={18} /> Start Standalone Groq STT Test Session
        </button>
      ) : (
        <div className="active-call-panel red-border">
          <div className="call-status-bar">
            <div className="status-live">
              <Radio className="pulse text-red" size={18} />
              <span>LIVE TUNING SESSION: <code>{callSessionId}</code></span>
            </div>
            <button className="btn-danger" onClick={stopTuningSession}>
              <MicOff size={16} /> Stop STT Test
            </button>
          </div>

          {/* MIC VOLUME LEVEL METER */}
          <div className="mic-volume-meter" style={{ marginTop: '0.75rem', marginBottom: '0.75rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', marginBottom: '0.25rem' }}>
              <span><Activity size={14} className="text-red" /> Live Microphone Input Level:</span>
              <strong>{micVolume}%</strong>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.1)', height: '10px', borderRadius: '5px', overflow: 'hidden' }}>
              <div
                style={{
                  width: `${micVolume}%`,
                  height: '100%',
                  background: micVolume > 70 ? '#ef4444' : micVolume > 30 ? '#eab308' : '#22c55e',
                  transition: 'width 0.1s ease',
                }}
              />
            </div>
          </div>

          {/* ASYNC STT IN-FLIGHT INDICATOR */}
          {sttState === 'transcribing' && (
            <div className="stt-transcribing-indicator" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.4)', borderRadius: '8px', padding: '0.5rem 0.75rem', color: '#fca5a5', fontSize: '0.85rem' }}>
              <Loader2 className="spin" size={16} />
              <span>{sttEngine === 'nova-3' ? 'Deepgram Nova-3 streaming... live interim results' : 'AsyncGroq Whisper in-flight... Transcribing utterance non-blockingly'}</span>
            </div>
          )}

          {/* PHONE AGENT CUMULATIVE SUSPICION METER */}
          <div className="suspicion-meter" style={{ marginTop: '0.75rem', padding: '0.75rem', background: 'rgba(15, 23, 42, 0.7)', border: `1px solid ${suspicion.tier === 'HIGH' ? 'rgba(239,68,68,0.6)' : suspicion.tier === 'MEDIUM' ? 'rgba(234,179,8,0.6)' : 'rgba(255,255,255,0.1)'}`, borderRadius: '8px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.85rem', marginBottom: '0.35rem' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <Activity size={14} className="text-red" />
                <strong>Phone Agent Suspicion (cumulative)</strong>
              </span>
              <span>
                <strong style={{ color: suspicion.tier === 'HIGH' ? '#ef4444' : suspicion.tier === 'MEDIUM' ? '#eab308' : '#22c55e' }}>{suspicion.score}/100</strong>
                {' '}<span style={{ background: suspicion.tier === 'HIGH' ? '#ef4444' : suspicion.tier === 'MEDIUM' ? '#eab308' : '#22c55e', color: '#0f172a', borderRadius: '4px', padding: '0.05rem 0.4rem', fontWeight: 700, fontSize: '0.7rem' }}>{suspicion.tier}</span>
                {suspicion.lastScore > 0 && <small style={{ opacity: 0.7, marginLeft: '0.4rem' }}>last utterance: {suspicion.lastScore}</small>}
              </span>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.1)', height: '12px', borderRadius: '6px', overflow: 'hidden' }}>
              <div style={{ width: `${suspicion.score}%`, height: '100%', background: suspicion.tier === 'HIGH' ? 'linear-gradient(90deg,#f87171,#ef4444)' : suspicion.tier === 'MEDIUM' ? 'linear-gradient(90deg,#facc15,#eab308)' : 'linear-gradient(90deg,#4ade80,#22c55e)', transition: 'width 0.3s ease' }} />
            </div>
            {suspicion.escalated && (
              <div style={{ marginTop: '0.5rem', background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.4)', borderRadius: '6px', padding: '0.4rem 0.6rem', color: '#fca5a5', fontSize: '0.8rem', fontWeight: 600 }}>
                🚨 ESCALATION TRIGGERED — HIGH-risk scam indicators detected. Suggested action: freeze transactions / block number.
              </div>
            )}
          </div>

          {/* LIVE TRANSCRIPTS DISPLAY */}
          <div className="call-dashboard-grid" style={{ marginTop: '1rem' }}>
            <div className="transcript-box">
              <h4>{sttEngine === 'nova-3' ? 'Live Deepgram Nova-3 Streaming Transcripts (Interim + Final)' : 'Live Silence-Flushed Transcripts (Whisper "en")'}</h4>
              <div className="transcript-lines" style={{ maxHeight: '180px', overflowY: 'auto' }}>
                {transcripts.length === 0 ? (
                  <p className="placeholder-text">{sttEngine === 'nova-3' ? 'Speak into microphone... Words appear live as Deepgram streams them.' : 'Speak into microphone... Utterances automatically flush after ~600ms silence pause.'}</p>
                ) : (
                  transcripts.map((t, idx) => (
                    <div key={idx} className={`transcript-line ${t.speaker}`} style={t.interim ? { opacity: 0.6, fontStyle: 'italic' } : undefined}>
                      <small style={{ opacity: 0.6, marginRight: '0.5rem' }}>[{t.ts}]</small>
                      <strong>[{t.speaker}]:</strong> {t.text}{t.interim ? '…' : ''}
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="highlights-box">
              <h4>Detected Coercion Threat Spans</h4>
              <div className="highlight-list" style={{ maxHeight: '180px', overflowY: 'auto' }}>
                {highlights.length === 0 ? (
                  <p className="placeholder-text">Threat keywords appear here live.</p>
                ) : (
                  highlights.map((h, idx) => (
                    <div key={idx} className="highlight-chip high">
                      <strong>"{h.phrase}"</strong> — {h.reason}
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* DIAGNOSTIC LOG BOX */}
      <div className="status-progress-panel" style={{ marginTop: '1rem' }}>
        <div className="progress-header">
          <Play className="icon text-red" size={16} />
          <h4>STT Engine Tuning Diagnostic Logs</h4>
        </div>
        <div className="status-log-box" style={{ maxHeight: '140px', overflowY: 'auto' }}>
          {logs.map((log, idx) => (
            <div key={idx} className="status-log-item">
              <span>{log}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
