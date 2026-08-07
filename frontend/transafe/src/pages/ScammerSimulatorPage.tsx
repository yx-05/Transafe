import React, { useEffect, useRef, useState } from 'react';
import { useSimulation } from '../context/SimulationContext';
import { useApi } from '../context/ApiContext';
import { UserHeader } from '../components/UserHeader';
import { CallAudioStreamer, playAgentSpeech } from '../services/audioRecorder';
import { CallEventsWebSocketClient } from '../services/websocket';
import type { WsCallEventMessage } from '../types/api';

interface ScriptLine {
  text: string;
  highlights: SpeechHighlight[];
  scoreIncrease: number;
}

interface Scenario {
  id: string;
  name: string;
  icon: string;
  description: string;
  lines: ScriptLine[];
}

interface SpeechHighlight {
  phrase: string;
  tag: string;
}

const scenarios: Scenario[] = [
  {
    id: 'macau',
    name: 'Macau Police Accusation Scam',
    icon: 'local_police',
    description: 'Impersonates PDRM Inspector Tan from Bukit Aman HQ, threatening arrest for money laundering.',
    lines: [
      {
        text: 'Hello, this is Inspector Tan calling from Bukit Aman PDRM HQ Police Contingent.',
        highlights: [{ phrase: 'Inspector Tan calling from Bukit Aman PDRM', tag: 'Authority Impersonation' }],
        scoreIncrease: 20
      },
      {
        text: 'We detected your IC number linked to a major money laundering syndicate in Penang.',
        highlights: [{ phrase: 'money laundering', tag: 'Accusation' }],
        scoreIncrease: 25
      },
      {
        text: 'You must immediately move RM 5,000 to our safe audit account: Maybank 7653-1234-5678.',
        highlights: [
          { phrase: 'move RM 5,000 to our safe audit account', tag: 'Fund Transfer' },
          { phrase: '7653-1234-5678', tag: 'Blacklisted Account' }
        ],
        scoreIncrease: 35
      },
      {
        text: 'Do not hang up this call or speak to anyone, otherwise officers will arrest you within 30 minutes!',
        highlights: [
          { phrase: 'Do not hang up this call', tag: 'Coercion' },
          { phrase: 'arrest you within 30 minutes', tag: 'Legal Threat' }
        ],
        scoreIncrease: 20
      }
    ]
  },
  {
    id: 'epf',
    name: 'EPF Fund Account Scam',
    icon: 'savings',
    description: 'Impersonates KWSP EPF Compliance, warning victim of unauthorized fund withdrawal attempts.',
    lines: [
      {
        text: 'Good day, I am calling from KWSP EPF Cyber Security Compliance Division.',
        highlights: [{ phrase: 'KWSP EPF Cyber Security', tag: 'Agency Impersonation' }],
        scoreIncrease: 15
      },
      {
        text: 'Your EPF account balance has been frozen due to suspected illegal withdrawal attempts.',
        highlights: [{ phrase: 'account balance has been frozen', tag: 'Account Fear' }],
        scoreIncrease: 20
      },
      {
        text: 'To unlock your savings, transfer RM 2,500 security deposit to account Public Bank 3344-9988-1122.',
        highlights: [{ phrase: 'transfer RM 2,500 security deposit', tag: 'Fund Transfer' }],
        scoreIncrease: 30
      }
    ]
  },
  {
    id: 'lhdn',
    name: 'LHDN Tax Audit Warning',
    icon: 'gavel',
    description: 'Impersonates LHDN Inland Revenue Board, threatening court warrants for unpaid tax arrears.',
    lines: [
      {
        text: 'This is an urgent alert from LHDN Inland Revenue Board Audit Unit.',
        highlights: [{ phrase: 'LHDN Inland Revenue Board', tag: 'Government Impersonation' }],
        scoreIncrease: 15
      },
      {
        text: 'You have outstanding tax arrears of RM 12,400. Fail to pay and court warrant will be issued today.',
        highlights: [{ phrase: 'court warrant will be issued today', tag: 'Urgent Threat' }],
        scoreIncrease: 25
      },
      {
        text: 'Settle the tax clearance immediately via direct transfer to RHB 2141-8877-6655.',
        highlights: [{ phrase: 'direct transfer to RHB', tag: 'Fund Transfer' }],
        scoreIncrease: 30
      }
    ]
  }
];

export const ScammerSimulatorPage: React.FC = () => {
  const { spoofedCallerNumber, setSpoofedCallerNumber } = useSimulation();

  const { config, client, userId } = useApi();

  const [activeTab, setActiveTab] = useState<string>('macau');
  const [isMicMuted, setIsMicMuted] = useState<boolean>(false);
  const [customText, setCustomText] = useState<string>('');

  // ---- Real Backend Call State (Step-by-Step + STT Tuning) ----
  const [callerName, setCallerName] = useState('Inspector Tan (PDRM Fake)');
  const [unknownCaller, setUnknownCaller] = useState(false);
  const [autoAutotalk, setAutoAutotalk] = useState(false);
  const [callSessionId, setCallSessionId] = useState<string | null>(null);
  const [micStatus, setMicStatus] = useState<string>('Not Connected');
  const [callStatus, setCallStatus] = useState<string>('Idle');
  const [sttEngine, setSttEngine] = useState<'nova-3' | 'groq'>('nova-3');
  const [sttState, setSttState] = useState<'idle' | 'transcribing'>('idle');
  const [micVolume, setMicVolume] = useState<number>(0);
  const [transcripts, setTranscripts] = useState<Array<{ speaker: string; text: string; ts: string; interim?: boolean }>>([]);
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

  const currentScenario = scenarios.find((s) => s.id === activeTab) || scenarios[0];

  useEffect(() => {
    return () => {
      audioStreamerRef.current.stopStreaming();
      eventsWsClientRef.current.close();
      stopMicVolumeMeter();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const addLog = (msg: string) => {
    setStepLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
  };

  // --- STT TUNING HELPERS ---
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
        await client.updateSttEngine(callSessionId, engine);
        addLog(`✅ STT engine updated live on call ${callSessionId}.`);
      } catch (e) {}
    }
  };

  // STEP 1: Initiate Call Trigger via real backend
  const handleStep1InitiateCall = async (e: React.FormEvent) => {
    e.preventDefault();
    setStepLogs(['[STEP 1] Initiating Call Trigger request...']);
    setCallSessionId(null);
    setTranscripts([]);
    setSttState('idle');

    const scamSessionId = `sess-scam-${Date.now()}`;

    try {
      addLog(`Sending POST /api/v1/trigger/call to ${config.baseUrl}...`);
      const res = await client.triggerCall({
        user_id: userId,
        session_id: scamSessionId,
        call: {
          caller_number: spoofedCallerNumber,
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
      if (res.call_mode === 'AUTO_TALK') {
        addLog('🤖 [AUTO-ENGAGE] Unknown caller + auto-engage enabled — TranSafe AI answered in AUTO_TALK mode.');
      }
      // Set initial STT engine selection (matches the toggle above)
      await client.updateSttEngine(res.call_session_id, sttEngine).catch(() => {});
      addLog(`✅ STEP 1 SUCCESS: Call registered! Call Session ID = ${res.call_session_id}`);
      addLog(`Ringing incoming call pushed to Victim User (${userId}). Ready for Step 2.`);

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

      addLog('✅ STEP 2 SUCCESS: Microphone active! Audio streaming & peer relay ready. Step 3 live.');
    } catch (err: any) {
      addLog(`❌ STEP 2 ERROR: ${err.message}`);
    }
  };

  // Mute / unmute the scammer microphone (works any number of times)
  const handleToggleMute = () => {
    const next = !isMicMuted;
    setIsMicMuted(next);
    audioStreamerRef.current.setMuted(next);
    addLog(next ? '🔇 Scammer microphone muted — audio relay paused.' : '🎙️ Scammer microphone unmuted — audio relay resumed.');
  };

  // STEP 4: Hang Up Call
  const handleStep4HangUp = () => {
    addLog('[STEP 4] Hanging up call session...');
    const currentId = callSessionId;

    // 1. Reset UI & stop audio recording instantly (0ms latency)
    audioStreamerRef.current.stopStreaming();
    stopMicVolumeMeter();
    eventsWsClientRef.current.close();
    setCallSessionId(null);
    setCallStatus('ENDED');
    setMicStatus('Not Connected');
    setSttState('idle');
    setTranscripts([]);

    // 2. Fire backend call termination non-blockingly in background
    if (currentId) {
      client.declineCall(currentId).catch(() => {});
    }
    addLog('✅ STEP 4 SUCCESS: Call ended. Terminal reset to Step 1.');
  };

  const handleInjectLine = (line: ScriptLine) => {
    // Browser TTS Synthesis (audio plays on this device)
    if ('speechSynthesis' in window) {
      const utterance = new SpeechSynthesisUtterance(line.text);
      utterance.rate = 0.95;
      window.speechSynthesis.speak(utterance);
    }
    addLog(`📢 [INJECT] "${line.text}" (${line.highlights.map((h) => h.tag).join(', ')})`);
  };

  const handleCustomInject = () => {
    if (!customText.trim()) return;
    if ('speechSynthesis' in window) {
      const utterance = new SpeechSynthesisUtterance(customText);
      utterance.rate = 0.95;
      window.speechSynthesis.speak(utterance);
    }
    addLog(`📢 [CUSTOM INJECT] "${customText}"`);
    setCustomText('');
  };

  const currentStep = !callSessionId ? 1 : micStatus.startsWith('Connected') || micStatus.includes('streaming') ? 3 : 2;

  return (
    <div className="min-h-screen bg-black text-white pb-28 font-mono relative">
      <div className="main-content-wrapper relative z-10">
        {/* Header App Bar */}
        <UserHeader title="Scammer Dial Console" showBack={true} />

        {/* Main Content Area */}
        <main className="px-6 flex flex-col gap-8 relative z-10">
          {/* Subheader Banner */}
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 pb-4 border-b-2 border-red-600">
            <div>
              <h2 className="text-2xl md:text-4xl font-extrabold tracking-tight text-red-600 flex items-center gap-3">
                <span className="material-symbols-outlined text-3xl text-red-600">warning</span>
                Remote Call Attack Terminal
              </h2>
              <p className="text-gray-400 mt-1 text-sm md:text-base">
                Monochrome Black & Red Attack Deck — Fire real scam calls into TranSafe WebRTC AI Copilot with live STT tuning.
              </p>
            </div>
          </div>

          {/* Grid Layout: Target Connection Deck (Left 5 Cols) + Script Injector Deck (Right 7 Cols) */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
            {/* Left Column: Target Connection Deck & Audio Mic */}
            <div className="lg:col-span-5 flex flex-col gap-6">
              <div className="bg-[#0a0a0a] rounded-[32px] p-6 md:p-8 border-2 border-red-600 flex flex-col gap-6">
                <div className="flex items-center gap-3 border-b-2 border-red-600/40 pb-4">
                  <div className="w-10 h-10 rounded-2xl bg-black text-red-600 border-2 border-red-600 flex items-center justify-center flex-shrink-0">
                    <span className="material-symbols-outlined text-2xl">settings_phone</span>
                  </div>
                  <div>
                    <h3 className="text-xl font-bold text-red-600">Target Connection Deck</h3>
                    <p className="text-xs text-gray-400">Configure spoofed CID and fire the incoming call.</p>
                  </div>
                </div>

                {/* STT ENGINE SELECTOR TOGGLE */}
                <div
                  style={{
                    display: 'flex',
                    gap: '0.5rem',
                    background: 'rgba(15, 23, 42, 0.6)',
                    padding: '0.4rem',
                    borderRadius: '8px',
                    border: '1px solid rgba(255,255,255,0.1)',
                  }}
                >
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
                    ⚡ Deepgram Nova-3
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
                    🎙️ Groq Whisper
                  </button>
                </div>

                <form onSubmit={handleStep1InitiateCall} className="flex flex-col gap-5">
                  <div className="form-group mb-0">
                    <label className="form-label text-xs uppercase tracking-wider text-red-500 font-bold mb-2">
                      Target Victim User ID
                    </label>
                    <input
                      type="text"
                      value={userId}
                      readOnly
                      className="form-input font-mono bg-black text-red-400 border-2 border-red-900 text-xs font-semibold cursor-not-allowed"
                    />
                  </div>

                  <div className="form-group mb-0">
                    <label className="form-label text-xs uppercase tracking-wider text-red-500 font-bold mb-2">
                      Spoofed Caller Number (CID)
                    </label>
                    <div className="relative flex items-center">
                      <span className="absolute left-4 text-red-600 text-base pointer-events-none">📞</span>
                      <input
                        type="text"
                        value={spoofedCallerNumber}
                        onChange={(e) => setSpoofedCallerNumber(e.target.value)}
                        placeholder="e.g., +6016-123-4567"
                        className="form-input pl-11 font-mono font-bold bg-black text-white border-2 border-red-600 focus:border-red-500 focus:ring-1 focus:ring-red-500 text-sm"
                        required
                      />
                    </div>
                  </div>

                  <div className="form-group mb-0">
                    <label className="form-label text-xs uppercase tracking-wider text-red-500 font-bold mb-2">
                      Scammer Identity Name
                    </label>
                    <input
                      type="text"
                      value={callerName}
                      onChange={(e) => setCallerName(e.target.value)}
                      required={!unknownCaller}
                      disabled={unknownCaller}
                      className="form-input font-mono font-bold bg-black text-white border-2 border-red-600 focus:border-red-500 focus:ring-1 focus:ring-red-500 text-sm disabled:opacity-40"
                    />
                  </div>

                  <div className="flex flex-col gap-2">
                    <label className="flex items-center gap-2 text-xs cursor-pointer">
                      <input
                        type="checkbox"
                        checked={unknownCaller}
                        onChange={(e) => setUnknownCaller(e.target.checked)}
                        className="accent-red-600 w-4 h-4"
                      />
                      📵 Caller is Unknown (no identity claimed)
                    </label>
                    <label className="flex items-center gap-2 text-xs cursor-pointer">
                      <input
                        type="checkbox"
                        checked={autoAutotalk}
                        onChange={(e) => setAutoAutotalk(e.target.checked)}
                        className="accent-red-600 w-4 h-4"
                      />
                      🤖 Auto-engage AI (AUTO_TALK) on unknown call
                    </label>
                  </div>

                  {/* Call Status Pill */}
                  <div className="p-4 bg-black rounded-2xl border-2 border-red-900 text-xs flex justify-between items-center">
                    <span className="font-semibold text-gray-400">WebRTC Call State:</span>
                    <span
                      className={`font-bold px-3 py-1 rounded-full text-[11px] uppercase tracking-wider ${
                        callStatus === 'RINGING'
                          ? 'bg-black text-red-500 border-2 border-red-600 animate-pulse'
                          : callStatus === 'ENDED'
                          ? 'bg-black text-gray-500 border border-gray-800'
                          : 'bg-black text-gray-500 border border-gray-800'
                      }`}
                    >
                      {callStatus === 'RINGING' ? '● RINGING TARGET...' : callStatus === 'ENDED' ? '● ENDED' : '● DISCONNECTED'}
                    </span>
                  </div>

                  {/* Call Action Buttons */}
                  <div className="flex flex-col gap-3">
                    <button
                      type="submit"
                      disabled={!!callSessionId}
                      className={`btn-primary w-full py-4 justify-center bg-red-600 hover:bg-red-700 text-white font-extrabold border-2 border-red-500 ${
                        callSessionId ? 'opacity-50 cursor-not-allowed' : ''
                      }`}
                    >
                      <span className="material-symbols-outlined text-xl">call</span>
                      1. Fire Incoming Call to Customer
                    </button>

                    <button
                      type="button"
                      onClick={handleStep2ConnectMic}
                      disabled={!callSessionId || currentStep >= 3}
                      className={`btn-secondary w-full py-4 justify-center bg-black hover:bg-red-950 text-red-500 border-2 border-red-600 font-bold ${
                        !callSessionId || currentStep >= 3 ? 'opacity-50 cursor-not-allowed' : ''
                      }`}
                    >
                      <span className="material-symbols-outlined text-xl">mic</span>
                      2. Connect Scammer Microphone & Audio Relay
                    </button>

                    <button
                      type="button"
                      onClick={handleStep4HangUp}
                      disabled={!callSessionId}
                      className={`btn-danger w-full py-4 justify-center bg-black hover:bg-red-950 text-red-500 border-2 border-red-600 font-bold ${
                        !callSessionId ? 'opacity-50 cursor-not-allowed' : ''
                      }`}
                    >
                      <span className="material-symbols-outlined text-xl">call_end</span>
                      4. Hang Up Call
                    </button>
                  </div>
                </form>
              </div>

              {/* Microphone Toggle Card */}
              <div className="bg-[#0a0a0a] rounded-[24px] p-5 border-2 border-red-600 flex justify-between items-center gap-4">
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${isMicMuted ? 'bg-black text-red-600 border border-red-600' : 'bg-red-600 text-white'}`}>
                    <span className="material-symbols-outlined text-xl">{isMicMuted ? 'mic_off' : 'mic'}</span>
                  </div>
                  <div>
                    <h4 className="text-sm font-bold text-white">Audio Input Stream</h4>
                    <p className="text-xs text-gray-400">{isMicMuted ? 'Microphone capture muted' : micStatus}</p>
                  </div>
                </div>

                <button
                  onClick={handleToggleMute}
                  className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex-shrink-0 border ${
                    isMicMuted
                      ? 'bg-red-600 hover:bg-red-700 text-white border-red-500'
                      : 'bg-black text-red-500 border-red-600 hover:bg-red-950'
                  }`}
                >
                  {isMicMuted ? 'Unmute' : 'Mute'}
                </button>
              </div>

              {/* MIC VOLUME LEVEL METER */}
              {callSessionId && currentStep >= 3 && (
                <div className="bg-[#0a0a0a] rounded-[24px] p-5 border-2 border-red-600 flex flex-col gap-3">
                  <div className="flex justify-between items-center text-xs">
                    <span className="flex items-center gap-1.5 text-red-500 font-semibold">
                      <span className="material-symbols-outlined text-sm">graphic_eq</span>
                      Live Microphone Input Level:
                    </span>
                    <strong className="text-white">{micVolume}%</strong>
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
                  <div className="audio-stream-status text-red-500 text-xs flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-sm">volume_up</span>
                    <strong>Scammer Microphone Status:</strong> {micStatus}
                  </div>
                </div>
              )}
            </div>

            {/* Right Column: Scam Script & Speech Line Injector */}
            <div className="lg:col-span-7 flex flex-col gap-6">
              <div className="bg-[#0a0a0a] rounded-[32px] p-6 md:p-8 border-2 border-red-600 flex flex-col gap-6">
                <div className="flex items-center justify-between border-b-2 border-red-600/40 pb-4">
                  <div>
                    <h3 className="text-xl font-bold text-red-600">Scam Script & Speech Injector</h3>
                    <p className="text-xs text-gray-400">Inject pre-scripted audio phrases into active WebRTC session.</p>
                  </div>
                  <span className="material-symbols-outlined text-red-600 text-3xl flex-shrink-0">record_voice_over</span>
                </div>

                {/* Scenario Selector Tabs */}
                <div className="flex gap-2 overflow-x-auto pb-2">
                  {scenarios.map((sc) => (
                    <button
                      key={sc.id}
                      onClick={() => setActiveTab(sc.id)}
                      className={`px-4 py-2.5 rounded-2xl text-xs font-bold transition-all flex items-center gap-2 whitespace-nowrap flex-shrink-0 border-2 ${
                        activeTab === sc.id
                          ? 'bg-red-600 text-white border-red-500'
                          : 'bg-black text-red-500 border-red-600 hover:bg-red-950'
                      }`}
                    >
                      <span className="material-symbols-outlined text-base">{sc.icon}</span>
                      <span>{sc.name}</span>
                    </button>
                  ))}
                </div>

                {/* Scenario Description Banner */}
                <div className="p-4 rounded-2xl bg-black border-2 border-red-600/60 text-white text-xs flex items-start gap-3">
                  <span className="material-symbols-outlined text-red-600 text-xl flex-shrink-0">info</span>
                  <div className="leading-relaxed">
                    <strong className="font-bold text-red-500">{currentScenario.name}:</strong> {currentScenario.description}
                  </div>
                </div>

                {/* Sentence Trigger List */}
                <div className="flex flex-col gap-3">
                  {currentScenario.lines.map((line, idx) => (
                    <div
                      key={idx}
                      className="p-4 rounded-2xl bg-black border-2 border-red-900 flex items-center justify-between gap-4 hover:border-red-600 transition-colors"
                    >
                      <div className="text-xs text-white flex-1 min-w-0 font-mono leading-relaxed">
                        <span className="text-red-500 font-bold mr-2">[{idx + 1}]</span>
                        "{line.text}"
                      </div>

                      <button
                        onClick={() => handleInjectLine(line)}
                        className="btn-primary py-2.5 px-4 text-xs bg-red-600 hover:bg-red-700 text-white flex-shrink-0 font-bold flex items-center gap-1.5 border border-red-500 active:scale-95"
                        title="Inject line into WebRTC call stream"
                      >
                        <span className="material-symbols-outlined text-base">volume_up</span>
                        <span>Inject</span>
                      </button>
                    </div>
                  ))}
                </div>

                {/* Custom Text Injection */}
                <div className="pt-4 border-t-2 border-red-600/40 flex flex-col gap-2">
                  <label className="form-label text-xs uppercase tracking-wider text-red-500 font-bold mb-0">
                    Custom Speech Line Injection
                  </label>
                  <div className="flex gap-3">
                    <input
                      type="text"
                      value={customText}
                      onChange={(e) => setCustomText(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleCustomInject()}
                      placeholder="Type custom sentence to inject live..."
                      className="form-input text-xs font-mono bg-black text-white border-2 border-red-600 focus:border-red-500 flex-1"
                    />
                    <button
                      onClick={handleCustomInject}
                      className="btn-secondary py-3 px-5 text-xs font-bold bg-black text-red-500 border-2 border-red-600 hover:bg-red-950 flex-shrink-0 whitespace-nowrap"
                    >
                      Inject Custom
                    </button>
                  </div>
                </div>
              </div>

              {/* LIVE STT TRANSCRIPTS */}
              {callSessionId && (
                <div className="bg-[#0a0a0a] rounded-[32px] p-6 md:p-8 border-2 border-red-600 flex flex-col gap-4">
                  <div className="flex items-center justify-between border-b-2 border-red-600/40 pb-4">
                    <h3 className="text-lg font-bold text-red-600">Live STT Transcripts</h3>
                    <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400">
                      {sttEngine === 'nova-3' ? 'Deepgram Nova-3 Streaming' : 'Groq Whisper Batch'} • {sttState === 'transcribing' ? 'TRANSCRIBING...' : 'IDLE'}
                    </span>
                  </div>

                  {sttState === 'transcribing' && (
                    <div className="flex items-center gap-2 p-3 rounded-xl bg-red-600/15 border border-red-600/40 text-red-400 text-xs">
                      <span className="material-symbols-outlined text-sm animate-spin">autorenew</span>
                      {sttEngine === 'nova-3' ? 'Deepgram Nova-3 streaming... live interim results' : 'Async Groq Whisper in-flight... Transcribing utterance non-blockingly'}
                    </div>
                  )}

                  <div style={{ maxHeight: '200px', overflowY: 'auto' }} className="flex flex-col gap-1.5">
                    {transcripts.length === 0 ? (
                      <p className="text-xs text-gray-500">
                        {sttEngine === 'nova-3'
                          ? 'Speak into microphone... Words appear live as Deepgram streams them.'
                          : 'Speak into microphone... Utterances automatically flush after ~600ms silence pause.'}
                      </p>
                    ) : (
                      transcripts.map((t, idx) => (
                        <div
                          key={idx}
                          className="text-xs font-mono leading-relaxed"
                          style={{ opacity: t.interim ? 0.6 : 1, fontStyle: t.interim ? 'italic' : 'normal', color: t.speaker === 'TRANSAFE_AI' ? '#fbbf24' : t.speaker === 'CUSTOMER' ? '#60a5fa' : '#fca5a5' }}
                        >
                          <small style={{ opacity: 0.6, marginRight: '0.5rem' }}>[{t.ts}]</small>
                          <strong>[{t.speaker}]:</strong> {t.text}{t.interim ? '…' : ''}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}

              {/* STEP DIAGNOSTIC LOG BOX */}
              <div className="bg-[#0a0a0a] rounded-[32px] p-6 md:p-8 border-2 border-red-600 flex flex-col gap-4">
                <div className="flex items-center gap-2 border-b-2 border-red-600/40 pb-4">
                  <span className="material-symbols-outlined text-red-600 text-lg">play_arrow</span>
                  <h3 className="text-lg font-bold text-red-600">Step-by-Step Diagnostic Logs</h3>
                </div>
                <div className="flex flex-col gap-1" style={{ maxHeight: '160px', overflowY: 'auto' }}>
                  {stepLogs.map((log, idx) => (
                    <div key={idx} className="text-[11px] font-mono text-gray-400 leading-relaxed">
                      <span style={{ color: log.includes('❌') ? '#f87171' : log.includes('✅') ? '#4ade80' : '#9ca3af' }}>{log}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
};
