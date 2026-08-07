import React, { useState, useRef, useEffect } from 'react';
import type { BackendConfig, WsCallEventMessage } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { CallAudioStreamer, playAgentSpeech } from '../../services/audioRecorder';
import { CallEventsWebSocketClient } from '../../services/websocket';
import { Skull, PhoneOutgoing, Mic, MicOff, Radio, Volume2, CheckCircle2, Play, Activity, Loader2 } from 'lucide-react';

interface StepByStepScammerCallProps {
  config: BackendConfig;
  victimUserId: string;
}

export const StepByStepScammerCall: React.FC<StepByStepScammerCallProps> = ({
  config,
  victimUserId,
}) => {
  const [callerNumber, setCallerNumber] = useState('+60161234567');
  const [callerName, setCallerName] = useState('Inspector Tan (PDRM Fake)');
  // AUTO_TALK auto-engage options
  const [unknownCaller, setUnknownCaller] = useState(false);
  const [autoAutotalk, setAutoAutotalk] = useState(false);

  // Step States
  const [currentStep, setCurrentStep] = useState<1 | 2 | 3 | 4>(1);
  const [callSessionId, setCallSessionId] = useState<string | null>(null);
  const [micStatus, setMicStatus] = useState<string>('Not Connected');
  const [callStatus, setCallStatus] = useState<string>('Idle');

  // STT Tuning States (merged from Standalone STT Tuning Lab)
  const [sttEngine, setSttEngine] = useState<'nova-3' | 'groq'>('nova-3');
  const [sttState, setSttState] = useState<'idle' | 'transcribing'>('idle');
  const [micVolume, setMicVolume] = useState<number>(0);
  const [transcripts, setTranscripts] = useState<Array<{ speaker: string; text: string; ts: string; interim?: boolean }>>([]);

  // Counters & Logs
  const [stepLogs, setStepLogs] = useState<string[]>([
    'Combined Step-by-Step Call + STT Tuning Terminal Ready.',
    'Dual STT Engine Support: Deepgram Nova-3 (streaming) & Groq Whisper (batch).',
  ]);

  const audioStreamerRef = useRef<CallAudioStreamer>(new CallAudioStreamer());
  const eventsWsClientRef = useRef<CallEventsWebSocketClient>(new CallEventsWebSocketClient());

  // Web Audio Analyser for mic volume level meter
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const meterStreamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    return () => {
      audioStreamerRef.current.stopStreaming();
      eventsWsClientRef.current.close();
    };
  }, []);

  const addLog = (msg: string) => {
    setStepLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
  };

  // --- STT TUNING HELPERS (merged from Standalone STT Tuning Lab) ---
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
    addLog(`Switched STT Engine to: ${engine === 'nova-3' ? 'Deepgram Nova-3' : 'Groq Whisper'}`);
    if (callSessionId) {
      try {
        const client = new TranSafeApiClient(config);
        await client.updateSttEngine(callSessionId, engine);
        addLog(`✅ STT engine updated live on call ${callSessionId}.`);
      } catch (e) {}
    }
  };

  // STEP 1: Initiate Call Trigger
  const handleStep1InitiateCall = async (e: React.FormEvent) => {
    e.preventDefault();
    setStepLogs(['[STEP 1] Initiating Call Trigger request...']);
    setCallSessionId(null);
    setCurrentStep(1);

    const client = new TranSafeApiClient(config);
    const sessionId = `sess-scam-${Date.now()}`;

    try {
      addLog(`Sending POST /api/v1/trigger/call to ${config.baseUrl}...`);
      const res = await client.triggerCall({
        user_id: victimUserId,
        session_id: sessionId,
        call: {
          caller_number: callerNumber,
          caller_name: unknownCaller ? 'Unknown' : callerName,
          call_mode: 'LISTEN',
          call_channel: 'WEBRTC',
          received_at: new Date().toISOString(),
          stt_engine: sttEngine,
          auto_autotalk_on_unknown: autoAutotalk,
        },
      });

      setCallSessionId(res.call_session_id);
      setCallStatus('RINGING');
      setCurrentStep(2);
      setTranscripts([]);
      setSttState('idle');
      if (res.call_mode === 'AUTO_TALK') {
        addLog('🤖 [AUTO-ENGAGE] Unknown caller + auto-engage enabled — TranSafe AI answered in AUTO_TALK mode.');
      }
      // Set initial STT engine selection (matches the toggle above)
      await client.updateSttEngine(res.call_session_id, sttEngine).catch(() => {});
      addLog(`✅ STEP 1 SUCCESS: Call registered! Call Session ID = ${res.call_session_id}`);
      addLog(`Ringing incoming call pushed to Victim User (${victimUserId}). Ready for Step 2.`);

      // Connect Events WebSocket
      eventsWsClientRef.current.connect(
        config.baseUrl,
        res.call_session_id,
        config.apiKey,
        (msg: WsCallEventMessage) => {
          if (msg.type === 'stt_status') {
            setSttState(msg.status === 'transcribing' ? 'transcribing' : 'idle');
          }
          if (msg.type === 'transcript_interim' && msg.text) {
            setTranscripts((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.interim) {
                next[next.length - 1] = { ...last, text: msg.text || '' };
              } else {
                next.push({
                  speaker: msg.speaker || 'SCAMMER',
                  text: msg.text || '',
                  ts: new Date().toLocaleTimeString(),
                  interim: true,
                });
              }
              return next;
            });
          }
          if (msg.type === 'transcript' && msg.text) {
            setTranscripts((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.interim) {
                next[next.length - 1] = {
                  speaker: msg.speaker || 'SCAMMER',
                  text: msg.text || '',
                  ts: new Date().toLocaleTimeString(),
                };
              } else {
                next.push({
                  speaker: msg.speaker || 'SCAMMER',
                  text: msg.text || '',
                  ts: new Date().toLocaleTimeString(),
                });
              }
              return next;
            });
            addLog(`✅ [STT TRANSCRIPT] [${msg.speaker}]: "${msg.text}"`);
          }
          if (msg.type === 'mode_change' && msg.call_mode) {
            addLog(`🤖 [CALL MODE] TranSafe switched the call to ${msg.call_mode}.`);
          }
          if (msg.type === 'talking' && msg.text) {
            setTranscripts((prev) => [
              ...prev,
              { speaker: 'TRANSAFE_AI', text: msg.text || '', ts: new Date().toLocaleTimeString() },
            ]);
            addLog(`🤖 [TRANSAFE AGENT]: "${msg.text}"${msg.action === 'hangup' ? ' 🚨 — scam confirmed, ending call' : ''}`);
            if (msg.tts_id && msg.call_session_id) {
              // Use the session id from the event itself — the `callSessionId`
              // state captured in this WS callback closure is STALE (still null
              // from the pre-render), so the old guard silently skipped TTS.
              // force=true for the hangup farewell so it is always heard.
              playAgentSpeech(config.baseUrl, msg.call_session_id, msg.tts_id, config.apiKey, msg.action === 'hangup').catch(() => {});
            }
          }
          if (msg.type === 'call_ended') {
            audioStreamerRef.current.stopStreaming();
            stopMicVolumeMeter();
            setCurrentStep(1);
            setCallSessionId(null);
            setCallStatus('ENDED');
            setSttState('idle');
            setTranscripts([]);
            addLog('📴 Call ended by Customer.');
          }
        },
        (err) => addLog(`[EVENTS WS ERROR] ${err}`),
        () => addLog('[EVENTS WS] Connection closed.')
      );
    } catch (err: any) {
      addLog(`❌ STEP 1 ERROR: ${err.message}`);
    }
  };

  // STEP 2: Connect Scammer Microphone
  const handleStep2ConnectMic = async () => {
    if (!callSessionId) return;
    addLog('[STEP 2] Requesting Scammer Microphone permission & connecting WebSockets...');

    try {
      await audioStreamerRef.current.startStreaming(
        config.baseUrl,
        callSessionId,
        config.apiKey,
        'SCAMMER',
        (status) => {
          setMicStatus(status);
          addLog(`[AUDIO STREAM] ${status}`);
        },
        (err) => addLog(`❌ [MIC ERROR] ${err}`)
      );

      // Start mic volume level meter (from Tuning Lab)
      if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        startMicVolumeMeter(stream);
      }

      setCurrentStep(3);
      addLog('✅ STEP 2 SUCCESS: Microphone active! Audio streaming & peer relay ready. Step 3 live.');
    } catch (err: any) {
      addLog(`❌ STEP 2 ERROR: ${err.message}`);
    }
  };

  // STEP 4: Hang Up Call
  const handleStep4HangUp = () => {
    addLog('[STEP 4] Hanging up call session...');
    const currentId = callSessionId;
    
    // 1. Reset UI & stop audio recording instantly (0ms latency)
    audioStreamerRef.current.stopStreaming();
    stopMicVolumeMeter();
    eventsWsClientRef.current.close();
    setCurrentStep(1);
    setCallSessionId(null);
    setCallStatus('ENDED');
    setMicStatus('Not Connected');
    setSttState('idle');
    setTranscripts([]);

    // 2. Fire backend call termination non-blockingly in background
    if (currentId) {
      const client = new TranSafeApiClient(config);
      client.declineCall(currentId).catch(() => {});
    }
    addLog('✅ STEP 4 SUCCESS: Call ended. Terminal reset to Step 1.');
  };

  return (
    <div className="card test-card scammer-card">
      <div className="card-header">
        <div className="card-title">
          <Skull className="card-icon text-red" size={20} />
          <h3>🎙️ Step-by-Step Scammer Call + STT Tuning Lab</h3>
        </div>
        <span className="card-tag red">SCAMMER ROLE (STEP-BY-STEP + STT TUNING)</span>
      </div>

      {/* STT ENGINE SELECTOR TOGGLE (merged from Standalone Tuning Lab) */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem', background: 'rgba(15, 23, 42, 0.6)', padding: '0.4rem', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)' }}>
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

      {/* STEP PROGRESS INDICATOR */}
      <div className="step-progress-bar">
        <div className={`step-item ${currentStep >= 1 ? 'active' : ''}`}>
          <span className="step-num">1</span>
          <span className="step-label">Trigger Call</span>
        </div>
        <div className={`step-item ${currentStep >= 2 ? 'active' : ''}`}>
          <span className="step-num">2</span>
          <span className="step-label">Connect Mic</span>
        </div>
        <div className={`step-item ${currentStep >= 3 ? 'active' : ''}`}>
          <span className="step-num">3</span>
          <span className="step-label">Live Audio Relay</span>
        </div>
        <div className={`step-item ${currentStep >= 4 ? 'active' : ''}`}>
          <span className="step-num">4</span>
          <span className="step-label">Hang Up</span>
        </div>
      </div>

      {/* STEP 1 CONTROLS */}
      {currentStep === 1 && (
        <form onSubmit={handleStep1InitiateCall} className="card-form">
          <div className="form-row">
            <div className="form-group">
              <label>Scammer Caller ID (Phone Number)</label>
              <input
                type="text"
                value={callerNumber}
                onChange={(e) => setCallerNumber(e.target.value)}
                required
              />
            </div>
            <div className="form-group">
              <label>Scammer Identity Name</label>
              <input
                type="text"
                value={callerName}
                onChange={(e) => setCallerName(e.target.value)}
                required={!unknownCaller}
                disabled={unknownCaller}
              />
            </div>
          </div>

          <div className="form-row" style={{ alignItems: 'center', gap: '1rem', marginBottom: '0.75rem' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.85rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={unknownCaller}
                onChange={(e) => setUnknownCaller(e.target.checked)}
              />
              📵 Caller is Unknown (no identity claimed)
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.85rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={autoAutotalk}
                onChange={(e) => setAutoAutotalk(e.target.checked)}
              />
              🤖 Auto-engage AI (AUTO_TALK) on unknown call
            </label>
          </div>

          <button type="submit" className="btn-danger-submit">
            <PhoneOutgoing size={16} /> 1. Fire Incoming Call to Customer
          </button>
        </form>
      )}

      {/* STEP 2 CONTROLS */}
      {currentStep === 2 && (
        <div className="step-action-box red-border">
          <h4><CheckCircle2 size={18} className="text-green" /> Step 1 Complete: Call Session Created!</h4>
          <p>Call Session ID: <code>{callSessionId}</code> (Status: {callStatus})</p>
          <button className="btn-primary" onClick={handleStep2ConnectMic}>
            <Mic size={16} /> 2. Connect Scammer Microphone & Audio Relay
          </button>
        </div>
      )}

      {/* STEP 3 & 4 LIVE CALL CONTROLS */}
      {currentStep >= 3 && (
        <div className="active-call-panel red-border">
          <div className="call-status-bar">
            <div className="status-live">
              <Radio className="pulse text-red" size={18} />
              <span>LIVE CALL: <code>{callSessionId}</code></span>
            </div>
            <button className="btn-danger" onClick={handleStep4HangUp}>
              <MicOff size={16} /> 4. Hang Up Call
            </button>
          </div>

          <div className="audio-stream-status text-red">
            <Mic size={16} /> <strong>Scammer Microphone Status:</strong> {micStatus}
          </div>

          <div className="scammer-live-banner">
            <Volume2 size={20} className="pulse" />
            <div>
              <strong>🎙️ Step 3 Live: 2-Way Audio Active!</strong>
              <p>Speak into your microphone. Your audio is relayed to the Customer, while Customer audio plays in your speakers.</p>
            </div>
          </div>

          {/* MIC VOLUME LEVEL METER (from Tuning Lab) */}
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
            <div className="stt-transcribing-indicator" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.4)', borderRadius: '8px', padding: '0.5rem 0.75rem', color: '#fca5a5', fontSize: '0.85rem', marginBottom: '0.75rem' }}>
              <Loader2 className="spin" size={16} />
              <span>{sttEngine === 'nova-3' ? 'Deepgram Nova-3 streaming... live interim results' : 'AsyncGroq Whisper in-flight... Transcribing utterance non-blockingly'}</span>
            </div>
          )}

          {/* LIVE STT TRANSCRIPTS (tuning results on the combined card) */}
          <div className="transcript-box" style={{ marginTop: '0.75rem' }}>
            <h4>{sttEngine === 'nova-3' ? 'Live Deepgram Nova-3 Streaming Transcripts (Interim + Final)' : 'Live Silence-Flushed Transcripts (Groq Whisper "en")'}</h4>
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
        </div>
      )}

      {/* STEP DIAGNOSTIC LOG BOX */}
      <div className="status-progress-panel" style={{ marginTop: '1rem' }}>
        <div className="progress-header">
          <Play className="icon text-red" size={16} />
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
