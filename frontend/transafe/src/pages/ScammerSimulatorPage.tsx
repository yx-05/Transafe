import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSimulation } from '../context/SimulationContext';
import type { SpeechHighlight } from '../context/SimulationContext';
import { UserHeader } from '../components/UserHeader';

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
    // Browser TTS Synthesis
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
                Monochrome Black & Red Attack Deck — Inject scam voice payloads directly into TranSafe WebRTC AI Copilot.
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
                    <p className="text-xs text-gray-400">Configure spoofed CID and destination target session.</p>
                  </div>
                </div>

                <form onSubmit={(e) => { e.preventDefault(); handleDial(); }} className="flex flex-col gap-5">
                  <div className="form-group mb-0">
                    <label className="form-label text-xs uppercase tracking-wider text-red-500 font-bold mb-2">
                      Target User Session ID
                    </label>
                    <input
                      type="text"
                      value={sessionId}
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

                  {/* Call Status Pill */}
                  <div className="p-4 bg-black rounded-2xl border-2 border-red-900 text-xs flex justify-between items-center">
                    <span className="font-semibold text-gray-400">WebRTC Call State:</span>
                    <span
                      className={`font-bold px-3 py-1 rounded-full text-[11px] uppercase tracking-wider ${
                        isCallConnected
                          ? 'bg-red-600 text-white border border-red-500'
                          : isCallRinging
                          ? 'bg-black text-red-500 border-2 border-red-600 animate-pulse'
                          : 'bg-black text-gray-500 border border-gray-800'
                      }`}
                    >
                      {isCallConnected ? '● CONNECTED' : isCallRinging ? '● RINGING TARGET...' : '● DISCONNECTED'}
                    </span>
                  </div>

                  {/* Call Action Buttons */}
                  <div className="flex flex-col gap-3">
                    <button
                      type="button"
                      onClick={handleDial}
                      disabled={isCallConnected || isCallRinging}
                      className={`btn-primary w-full py-4 justify-center bg-red-600 hover:bg-red-700 text-white font-extrabold border-2 border-red-500 ${
                        isCallConnected || isCallRinging ? 'opacity-50 cursor-not-allowed' : ''
                      }`}
                    >
                      <span className="material-symbols-outlined text-xl">call</span>
                      Dial Target Phone
                    </button>

                    <button
                      type="button"
                      onClick={endCall}
                      disabled={!isCallConnected && !isCallRinging}
                      className={`btn-danger w-full py-4 justify-center bg-black hover:bg-red-950 text-red-500 border-2 border-red-600 font-bold ${
                        !isCallConnected && !isCallRinging ? 'opacity-50 cursor-not-allowed' : ''
                      }`}
                    >
                      <span className="material-symbols-outlined text-xl">call_end</span>
                      Disconnect Call
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
                    <p className="text-xs text-gray-400">{isMicMuted ? 'Microphone capture muted' : 'Capturing live WebRTC audio'}</p>
                  </div>
                </div>

                <button
                  onClick={() => setIsMicMuted(!isMicMuted)}
                  className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex-shrink-0 border ${
                    isMicMuted
                      ? 'bg-red-600 hover:bg-red-700 text-white border-red-500'
                      : 'bg-black text-red-500 border-red-600 hover:bg-red-950'
                  }`}
                >
                  {isMicMuted ? 'Unmute' : 'Mute'}
                </button>
              </div>
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
            </div>
          </div>
        </main>
      </div>
    </div>
  );
};
