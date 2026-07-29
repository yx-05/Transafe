import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSimulation } from '../context/SimulationContext';
import type { SpeechHighlight } from '../context/SimulationContext';

interface ScriptLine {
  text: string;
  highlights: SpeechHighlight[];
  scoreIncrease: number;
}

interface Scenario {
  id: string;
  name: string;
  lines: ScriptLine[];
}

const scenarios: Scenario[] = [
  {
    id: 'macau',
    name: 'Macau Police Accusation Scam',
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
  const {
    sessionId,
    spoofedCallerNumber,
    setSpoofedCallerNumber,
    isCallConnected,
    isCallRinging,
    triggerIncomingCall,
    endCall,
    injectScammerSpeech
  } = useSimulation();

  const navigate = useNavigate();

  const [activeTab, setActiveTab] = useState<string>('macau');
  const [isMicMuted, setIsMicMuted] = useState<boolean>(false);
  const [customText, setCustomText] = useState<string>('');

  const currentScenario = scenarios.find((s) => s.id === activeTab) || scenarios[0];

  const handleDial = () => {
    triggerIncomingCall(spoofedCallerNumber);
    // Navigate user app to call screen so they see incoming call ringing!
    navigate('/call-active');
  };

  const handleInjectLine = (line: ScriptLine) => {
    injectScammerSpeech(line.text, line.highlights, line.scoreIncrease);
    // TTS Browser Synthesis simulation
    if ('speechSynthesis' in window) {
      const utterance = new SpeechSynthesisUtterance(line.text);
      utterance.rate = 0.95;
      window.speechSynthesis.speak(utterance);
    }
  };

  const handleCustomInject = () => {
    if (!customText.trim()) return;
    injectScammerSpeech(
      customText,
      [{ phrase: customText, tag: 'Custom Injection' }],
      20
    );
    setCustomText('');
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6 md:p-10 font-mono">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex justify-between items-center border-b border-slate-800 pb-4 mb-8">
          <div>
            <h1 className="text-2xl font-extrabold text-red-500 flex items-center gap-3">
              <span className="material-symbols-outlined text-3xl">phone_in_talk</span>
              Scammer Call Simulator Deck
            </h1>
            <p className="text-xs text-slate-400 mt-1">
              Remote Audio Source & Attack Vector Injection Software (Phone A Terminal)
            </p>
          </div>
          <span className="text-xs bg-red-950 text-red-400 px-3 py-1 rounded border border-red-800 font-bold">
            SIMULATOR MODE ACTIVE
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-12 gap-8">
          {/* Left Column: Connection Controls */}
          <div className="md:col-span-5 flex flex-col gap-6">
            <div className="neo-card bg-slate-900 border border-slate-800 p-6 text-slate-200">
              <h2 className="text-sm font-bold text-slate-300 uppercase tracking-wider mb-4 border-b border-slate-800 pb-2">
                Target Connection Deck
              </h2>

              <div className="form-group">
                <label className="form-label text-slate-400 text-xs">Target User Session / ID</label>
                <input
                  type="text"
                  value={sessionId}
                  readOnly
                  className="form-input font-mono bg-slate-950 text-slate-300 border-slate-800 text-xs"
                />
              </div>

              <div className="form-group">
                <label className="form-label text-slate-400 text-xs">Spoofed Caller Number</label>
                <input
                  type="text"
                  value={spoofedCallerNumber}
                  onChange={(e) => setSpoofedCallerNumber(e.target.value)}
                  placeholder="e.g., +6016-123-4567"
                  className="form-input font-mono bg-slate-950 text-slate-200 border-slate-800 text-sm"
                />
              </div>

              {/* Status */}
              <div className="p-3 bg-slate-950 rounded-xl border border-slate-800 text-xs mb-6 flex justify-between items-center">
                <span className="text-slate-400">Call Status:</span>
                <span
                  className={`font-bold px-2 py-0.5 rounded text-[10px] ${
                    isCallConnected
                      ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                      : isCallRinging
                      ? 'bg-amber-950 text-amber-400 border border-amber-800 animate-pulse'
                      : 'bg-slate-800 text-slate-400'
                  }`}
                >
                  {isCallConnected ? 'CONNECTED' : isCallRinging ? 'RINGING TARGET...' : 'DISCONNECTED'}
                </span>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-col gap-3">
                <button
                  onClick={handleDial}
                  disabled={isCallConnected || isCallRinging}
                  className={`btn-primary py-3.5 text-xs justify-center bg-emerald-600 hover:bg-emerald-700 ${
                    isCallConnected || isCallRinging ? 'opacity-50 cursor-not-allowed' : ''
                  }`}
                >
                  <span className="material-symbols-outlined">call</span>
                  📞 Dial Target Phone B
                </button>

                <button
                  onClick={endCall}
                  disabled={!isCallConnected && !isCallRinging}
                  className={`btn-danger py-3.5 text-xs justify-center ${
                    !isCallConnected && !isCallRinging ? 'opacity-50 cursor-not-allowed' : ''
                  }`}
                >
                  <span className="material-symbols-outlined">call_end</span>
                  🔴 Disconnect Call
                </button>
              </div>
            </div>

            {/* Mic Toggle Card */}
            <div className="neo-card bg-slate-900 border border-slate-800 p-4 flex justify-between items-center">
              <span className="text-xs font-bold text-slate-300">Live Microphone Stream</span>
              <button
                onClick={() => setIsMicMuted(!isMicMuted)}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold flex items-center gap-2 transition-colors ${
                  isMicMuted
                    ? 'bg-red-950 text-red-400 border border-red-800'
                    : 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                }`}
              >
                <span className="material-symbols-outlined text-sm">
                  {isMicMuted ? 'mic_off' : 'mic'}
                </span>
                {isMicMuted ? 'Microphone Muted' : 'Microphone Active'}
              </button>
            </div>
          </div>

          {/* Right Column: Scenario & Dialogue Injector */}
          <div className="md:col-span-7 flex flex-col gap-6">
            <div className="neo-card bg-slate-900 border border-slate-800 p-6">
              <h2 className="text-sm font-bold text-slate-300 uppercase tracking-wider mb-4 border-b border-slate-800 pb-2">
                Scam Script & Speech Injector
              </h2>

              {/* Tabs */}
              <div className="flex gap-2 mb-6 overflow-x-auto pb-1">
                {scenarios.map((sc) => (
                  <button
                    key={sc.id}
                    onClick={() => setActiveTab(sc.id)}
                    className={`px-3 py-2 rounded-xl text-xs font-bold transition-all text-left whitespace-nowrap ${
                      activeTab === sc.id
                        ? 'bg-red-600 text-white shadow-lg'
                        : 'bg-slate-950 text-slate-400 border border-slate-800 hover:text-white'
                    }`}
                  >
                    {sc.name}
                  </button>
                ))}
              </div>

              {/* Sentence Trigger List */}
              <div className="flex flex-col gap-3 mb-6">
                {currentScenario.lines.map((line, idx) => (
                  <div
                    key={idx}
                    className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 flex justify-between items-center gap-4 hover:border-red-600/50 transition-colors"
                  >
                    <div className="text-xs text-slate-200">
                      <span className="text-red-400 font-bold mr-2">Row {idx + 1}:</span>
                      "{line.text}"
                    </div>

                    <button
                      onClick={() => handleInjectLine(line)}
                      className="btn-primary py-2 px-3 text-xs bg-red-600 hover:bg-red-700 flex-shrink-0"
                      title="Speak line via WebRTC & TTS to target phone"
                    >
                      <span className="material-symbols-outlined text-sm">volume_up</span>
                      Speak
                    </button>
                  </div>
                ))}
              </div>

              {/* Custom Text Injection Box */}
              <div className="pt-4 border-t border-slate-800">
                <label className="form-label text-slate-400 text-xs mb-2">Custom Speech Line Injection</label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={customText}
                    onChange={(e) => setCustomText(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleCustomInject()}
                    placeholder="Type custom sentence to inject..."
                    className="form-input bg-slate-950 border-slate-800 text-slate-200 text-xs flex-1"
                  />
                  <button onClick={handleCustomInject} className="btn-secondary text-xs py-2 px-4">
                    Inject
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
