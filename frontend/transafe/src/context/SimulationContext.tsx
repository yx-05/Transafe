import React, { createContext, useContext, useState, useCallback } from 'react';
import type { ReactNode } from 'react';

// ==========================================
// Types & Interfaces
// ==========================================

export interface Transaction {
  id: string;
  recipient: string;
  bank: string;
  accountNumber: string;
  amount: number;
  date: string;
  category: string;
  type: 'debit' | 'credit';
  status: 'COMPLETED' | 'HELD' | 'BLOCKED' | 'FROZEN';
  riskScore?: number;
}

export interface SpeechHighlight {
  phrase: string;
  tag: string; // e.g. "Fund Transfer", "Authority Impersonation", "Accusation"
}

export interface TranscriptLine {
  id: string;
  speaker: 'caller' | 'user' | 'ai';
  text: string;
  timestamp: string;
  highlights?: SpeechHighlight[];
}

export interface VerificationAnchor {
  id: string;
  code: string;
  title: string;
  status: 'PENDING' | 'PASSED' | 'EVADED' | 'FAILED' | 'FLAG_TRIGGERED';
}

export interface CaseWorkerFinding {
  workerName: string;
  score: number;
  status: 'SAFE' | 'WARNING' | 'CRITICAL';
  evidence: string[];
}

export interface FraudCase {
  id: string;
  userId: string;
  userName: string;
  triggerType: 'CALL' | 'TRANSACTION' | 'PHISHING';
  timestamp: string;
  riskScore: number;
  status: 'PENDING_REVIEW' | 'FROZEN' | 'BLOCKED' | 'DISMISSED' | 'APPROVED';
  actionTaken: 'FREEZE_30_MIN' | 'BLOCK_TRANSACTION' | 'ALERT_ADMIN' | 'ALLOW';
  summaryEn: string;
  summaryMs: string;
  workerFindings: CaseWorkerFinding[];
  transcript?: TranscriptLine[];
  screenshotUrl?: string;
  ocrText?: string;
  associatedCaseId?: string;
}

interface SimulationContextType {
  // Session & Balance
  sessionId: string;
  accountBalance: number;
  setAccountBalance: React.Dispatch<React.SetStateAction<number>>;
  transactions: Transaction[];
  addTransaction: (tx: Transaction) => void;
  
  // Active Call State
  isCallRinging: boolean;
  isCallConnected: boolean;
  callMode: 'none' | 'copilot' | 'autotalk';
  callerId: string;
  spoofedCallerNumber: string;
  setSpoofedCallerNumber: (num: string) => void;
  suspicionScore: number;
  transcript: TranscriptLine[];
  verificationAnchors: VerificationAnchor[];
  
  // Call Controls
  triggerIncomingCall: (callerNum?: string) => void;
  answerCall: (mode: 'copilot' | 'autotalk') => void;
  declineCall: () => void;
  endCall: () => void;
  switchCallMode: (mode: 'copilot' | 'autotalk') => void;
  injectScammerSpeech: (text: string, highlights?: SpeechHighlight[], scoreIncrease?: number) => void;
  
  // Transfer & Scan Workflow
  isScanningTransfer: boolean;
  scannerLogs: string[];
  lastScanVerdict: {
    riskScore: number;
    riskTier: 'LOW' | 'MEDIUM' | 'HIGH';
    actionTaken: 'FREEZE_30_MIN' | 'BLOCK_TRANSACTION' | 'ALERT_ADMIN' | 'ALLOW';
    summaryEn: string;
    summaryMs: string;
  } | null;
  submitTransferScan: (details: {
    bank: string;
    recipientName: string;
    accountNumber: string;
    amount: number;
    description: string;
    associatedCaseId?: string;
  }) => Promise<void>;
  clearScanVerdict: () => void;

  // Phishing Scan Workflow
  isScanningPhishing: boolean;
  phishingResult: {
    scamDetected: boolean;
    confidence: number;
    extractedText: string;
    verdict: string;
    caseId: string;
  } | null;
  submitPhishingScan: (file: File) => Promise<void>;

  // Admin Fraud Cases
  fraudCases: FraudCase[];
  selectedCaseId: string | null;
  setSelectedCaseId: (id: string | null) => void;
  updateCaseStatus: (id: string, status: FraudCase['status'], action?: FraudCase['actionTaken']) => void;
}

const defaultAnchors: VerificationAnchor[] = [
  { id: 'aq-1', code: '[AQ-1]', title: 'Organization & Employee ID Verification', status: 'PENDING' },
  { id: 'aq-2', code: '[AQ-2]', title: 'Direct Call-Back Verification Line', status: 'PENDING' },
  { id: 'aq-3', code: '[AQ-3]', title: 'Immediate Fund Transfer Intent Check', status: 'PENDING' },
  { id: 'aq-4', code: '[AQ-4]', title: 'Pressure & Consult Prevention Check', status: 'PENDING' },
];

const initialTransactions: Transaction[] = [
  {
    id: 'tx-101',
    recipient: 'Ali Bin Ahmad',
    bank: 'Maybank',
    accountNumber: '1641-2345-6789',
    amount: 150.00,
    date: 'Today, 10:30 AM',
    category: 'P2P Transfer',
    type: 'debit',
    status: 'COMPLETED'
  },
  {
    id: 'tx-102',
    recipient: 'Salary Deposit (Global Tech Inc.)',
    bank: 'CIMB Bank',
    accountNumber: '7012-9988-1122',
    amount: 4500.00,
    date: 'Yesterday, 9:00 AM',
    category: 'Income',
    type: 'credit',
    status: 'COMPLETED'
  },
  {
    id: 'tx-103',
    recipient: 'Village Grocer KL',
    bank: 'Public Bank',
    accountNumber: '3344-5566-7788',
    amount: 84.20,
    date: '2 days ago',
    category: 'Shopping',
    type: 'debit',
    status: 'COMPLETED'
  }
];

const initialCases: FraudCase[] = [
  {
    id: 'case-891',
    userId: 'usr-9012',
    userName: 'JOHN DOE',
    triggerType: 'CALL',
    timestamp: '10 mins ago',
    riskScore: 88,
    status: 'PENDING_REVIEW',
    actionTaken: 'FREEZE_30_MIN',
    summaryEn: 'High-risk Macau Police scam call detected. Caller used legal threats and urged victim not to hang up while asking for RM 10,000 transfer.',
    summaryMs: 'Panggilan penipuan Macau Police berisiko tinggi dikesan. Pemanggil menggunakan ugutan undang-undang dan meminta pemindahan wang RM 10,000.',
    workerFindings: [
      { workerName: 'Phone Worker', score: 92, status: 'CRITICAL', evidence: ['Authority impersonation detected ("PDRM Inspector")', 'Coercive urgency tactics used', 'Evaded ID verification check'] },
      { workerName: 'Research Worker', score: 85, status: 'CRITICAL', evidence: ['Caller number matches Macau scam prefix +6016-123-****', 'Matched 3 historic NSRC scam patterns'] },
      { workerName: 'Telemetry Worker', score: 65, status: 'WARNING', evidence: ['Elevated stress audio frequency', 'Long pause before answering'] }
    ],
    transcript: [
      { id: '1', speaker: 'caller', text: 'Hello, this is Inspector Tan from PDRM Police HQ.', timestamp: '10:14 AM', highlights: [{ phrase: 'Inspector Tan from PDRM', tag: 'Authority Impersonation' }] },
      { id: '2', speaker: 'caller', text: 'We detected money laundering under your account. You face immediate arrest.', timestamp: '10:14 AM', highlights: [{ phrase: 'money laundering', tag: 'Accusation' }, { phrase: 'immediate arrest', tag: 'Coercion' }] },
      { id: '3', speaker: 'ai', text: '🤖 AI: I am unauthorized to confirm details over this line. Please state your official badge ID.', timestamp: '10:15 AM' },
      { id: '4', speaker: 'caller', text: 'You must transfer RM 10,000 to our safe audit account Maybank 7653-1234-5678 immediately!', timestamp: '10:15 AM', highlights: [{ phrase: 'transfer RM 10,000 to our safe audit account', tag: 'Fund Transfer' }] }
    ]
  },
  {
    id: 'case-892',
    userId: 'usr-9012',
    userName: 'JOHN DOE',
    triggerType: 'PHISHING',
    timestamp: '1 hour ago',
    riskScore: 78,
    status: 'BLOCKED',
    actionTaken: 'BLOCK_TRANSACTION',
    summaryEn: 'WhatsApp phishing message claiming EPF account compromise with malicious APK download link.',
    summaryMs: 'Mesej pancingan data WhatsApp mendakwa akaun KWSP terkompromi dengan pautan muat turun APK berbahaya.',
    workerFindings: [
      { workerName: 'Phishing Worker', score: 82, status: 'CRITICAL', evidence: ['OCR extracted fake EPF link domain "epf-gov-my.apk-update.net"', 'Matched 14 reported WhatsApp malware lures'] },
      { workerName: 'Research Worker', score: 75, status: 'WARNING', evidence: ['IP domain host flagged in threat intelligence db'] }
    ],
    screenshotUrl: 'https://images.unsplash.com/photo-1563986768609-322da13575f3?w=600&auto=format&fit=crop&q=80',
    ocrText: 'URGENT EPF NOTICE: Your account has been suspended due to unverified login. Download KWSP Security App: http://epf-gov-my.apk-update.net to reactivate.'
  }
];

const SimulationContext = createContext<SimulationContextType | undefined>(undefined);

export const SimulationProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [sessionId] = useState<string>('session-' + Math.random().toString(36).substring(2, 8));
  const [accountBalance, setAccountBalance] = useState<number>(24530.80);
  const [transactions, setTransactions] = useState<Transaction[]>(initialTransactions);
  
  // Call State
  const [isCallRinging, setIsCallRinging] = useState<boolean>(false);
  const [isCallConnected, setIsCallConnected] = useState<boolean>(false);
  const [callMode, setCallMode] = useState<'none' | 'copilot' | 'autotalk'>('none');
  const [callerId, setCallerId] = useState<string>('Unknown Caller (+6016-123-4567)');
  const [spoofedCallerNumber, setSpoofedCallerNumber] = useState<string>('+6016-123-4567');
  const [suspicionScore, setSuspicionScore] = useState<number>(15);
  const [transcript, setTranscript] = useState<TranscriptLine[]>([]);
  const [verificationAnchors, setVerificationAnchors] = useState<VerificationAnchor[]>(defaultAnchors);

  // Transfer Scan State
  const [isScanningTransfer, setIsScanningTransfer] = useState<boolean>(false);
  const [scannerLogs, setScannerLogs] = useState<string[]>([]);
  const [lastScanVerdict, setLastScanVerdict] = useState<SimulationContextType['lastScanVerdict']>(null);

  // Phishing Scan State
  const [isScanningPhishing, setIsScanningPhishing] = useState<boolean>(false);
  const [phishingResult, setPhishingResult] = useState<SimulationContextType['phishingResult']>(null);

  // Admin Fraud Cases State
  const [fraudCases, setFraudCases] = useState<FraudCase[]>(initialCases);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>('case-891');

  // Add a transaction
  const addTransaction = useCallback((tx: Transaction) => {
    setTransactions((prev) => [tx, ...prev]);
    if (tx.type === 'debit') {
      setAccountBalance((prev) => Math.max(0, prev - tx.amount));
    } else {
      setAccountBalance((prev) => prev + tx.amount);
    }
  }, []);

  // Call Control Functions
  const triggerIncomingCall = useCallback((num?: string) => {
    const callerNum = num || spoofedCallerNumber || '+6016-123-4567';
    setCallerId(`Unknown Caller (${callerNum})`);
    setIsCallRinging(true);
    setIsCallConnected(false);
    setCallMode('none');
    setSuspicionScore(20);
    setTranscript([]);
    setVerificationAnchors(defaultAnchors);
  }, [spoofedCallerNumber]);

  const answerCall = useCallback((mode: 'copilot' | 'autotalk') => {
    setIsCallRinging(false);
    setIsCallConnected(true);
    setCallMode(mode);
    setSuspicionScore(35);
    // Add initial line
    const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    setTranscript([
      {
        id: 'line-0',
        speaker: 'caller',
        text: 'Hello, am I speaking to John Doe? This is Inspector Tan from Bukit Aman PDRM HQ.',
        timestamp: now,
        highlights: [{ phrase: 'Inspector Tan from Bukit Aman PDRM', tag: 'Authority Impersonation' }]
      }
    ]);
  }, []);

  const declineCall = useCallback(() => {
    setIsCallRinging(false);
    setIsCallConnected(false);
    setCallMode('none');
  }, []);

  const endCall = useCallback(() => {
    setIsCallRinging(false);
    setIsCallConnected(false);
    setCallMode('none');
  }, []);

  const switchCallMode = useCallback((mode: 'copilot' | 'autotalk') => {
    setCallMode(mode);
  }, []);

  // Inject Speech from Scammer Simulator
  const injectScammerSpeech = useCallback((text: string, highlights?: SpeechHighlight[], scoreIncrease: number = 20) => {
    const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const lineId = 'line-' + Math.random().toString(36).substring(2, 7);
    
    // Auto trigger ringing if call not connected
    if (!isCallConnected && !isCallRinging) {
      triggerIncomingCall();
    }

    setTranscript((prev) => [
      ...prev,
      {
        id: lineId,
        speaker: 'caller',
        text,
        timestamp: now,
        highlights
      }
    ]);

    setSuspicionScore((prev) => Math.min(100, prev + scoreIncrease));

    // Update Verification Anchors based on speech content
    const lowerText = text.toLowerCase();
    setVerificationAnchors((prev) =>
      prev.map((anchor) => {
        if (anchor.id === 'aq-1' && (lowerText.includes('id') || lowerText.includes('pdrm') || lowerText.includes('police'))) {
          return { ...anchor, status: lowerText.includes("don't need") || lowerText.includes('refuse') ? 'EVADED' : 'PASSED' };
        }
        if (anchor.id === 'aq-2' && (lowerText.includes('hang up') || lowerText.includes('call back'))) {
          return { ...anchor, status: 'FAILED' };
        }
        if (anchor.id === 'aq-3' && (lowerText.includes('transfer') || lowerText.includes('rm') || lowerText.includes('safe account'))) {
          return { ...anchor, status: 'FLAG_TRIGGERED' };
        }
        if (anchor.id === 'aq-4' && (lowerText.includes('arrest') || lowerText.includes('seize') || lowerText.includes('immediately'))) {
          return { ...anchor, status: 'FAILED' };
        }
        return anchor;
      })
    );

    // If auto-talk is active, synthesize AI response!
    if (callMode === 'autotalk') {
      setTimeout(() => {
        let aiReply = "🤖 AI: I am unauthorized to confirm details over this line. Can you provide your official badge number?";
        if (lowerText.includes('transfer') || lowerText.includes('rm')) {
          aiReply = "🤖 AI: Financial regulations strictly prohibit transferring funds to unverified accounts. This session is recorded for NSRC.";
        } else if (lowerText.includes('hang up') || lowerText.includes('arrest')) {
          aiReply = "🤖 AI: Under BNM guidelines, I am terminating this unverified call and escalating to our fraud operations desk.";
        }

        setTranscript((prev) => [
          ...prev,
          {
            id: 'line-ai-' + Math.random().toString(36).substring(2, 7),
            speaker: 'ai',
            text: aiReply,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          }
        ]);
      }, 1200);
    }
  }, [isCallConnected, isCallRinging, callMode, triggerIncomingCall]);

  // Submit Transfer Scan Simulation
  const submitTransferScan = useCallback(async (details: {
    bank: string;
    recipientName: string;
    accountNumber: string;
    amount: number;
    description: string;
    associatedCaseId?: string;
  }) => {
    setIsScanningTransfer(true);
    setScannerLogs([]);
    setLastScanVerdict(null);

    const logSteps = [
      'Orchestrator: Routing transaction trigger to analysis workers...',
      `Financial Worker: Reviewing 90-day transaction deviations for RM ${details.amount.toFixed(2)}...`,
      'Telemetry Worker: Inspecting behavioral biometrics & typing cadence...',
      `Research Worker: Querying national scam databases for account ${details.accountNumber}...`,
      'Risk Scorer: Integrating worker confidence parameters...',
      'Explainable AI: Formatting human-readable verdict...'
    ];

    for (let i = 0; i < logSteps.length; i++) {
      await new Promise((res) => setTimeout(res, 700));
      const timestamp = new Date().toLocaleTimeString();
      setScannerLogs((prev) => [...prev, `[${timestamp}] ${logSteps[i]}`]);
    }

    // Determine risk based on amount or linked case
    const isHighRisk = details.amount >= 5000 || !!details.associatedCaseId || details.accountNumber.includes('7653');
    const calculatedScore = isHighRisk ? 89 : details.amount > 1000 ? 55 : 18;
    const tier: 'LOW' | 'MEDIUM' | 'HIGH' = calculatedScore > 70 ? 'HIGH' : calculatedScore > 30 ? 'MEDIUM' : 'LOW';
    const action: 'FREEZE_30_MIN' | 'BLOCK_TRANSACTION' | 'ALERT_ADMIN' | 'ALLOW' =
      tier === 'HIGH' ? 'FREEZE_30_MIN' : tier === 'MEDIUM' ? 'ALERT_ADMIN' : 'ALLOW';

    const summaryEn = tier === 'HIGH'
      ? `High-risk transaction intercepted! Recipient account ${details.accountNumber} correlates with active Macau Police scam call reported 10 mins ago. Transaction amount RM ${details.amount.toFixed(2)} deviates 420% from 90-day average.`
      : tier === 'MEDIUM'
      ? `Medium risk detected. Transaction amount RM ${details.amount.toFixed(2)} exceeds normal daily transfer threshold. Flagged for verification.`
      : `Transaction verified safe. Account ${details.accountNumber} has clean history and normal baseline metrics.`;

    const summaryMs = tier === 'HIGH'
      ? `Pindahan berisiko tinggi dipintas! Akaun penerima ${details.accountNumber} sepadan dengan panggilan penipuan Macau Police aktif. Jumlah RM ${details.amount.toFixed(2)} menyimpang 420% daripada purata 90 hari.`
      : tier === 'MEDIUM'
      ? `Risiko sederhana dikesan. Jumlah RM ${details.amount.toFixed(2)} melebihi had pemindahan harian biasa. Ditandakan untuk pengesahan.`
      : `Pindahan disahkan selamat. Akaun ${details.accountNumber} mempunyai rekod bersih.`;

    const verdict = {
      riskScore: calculatedScore,
      riskTier: tier,
      actionTaken: action,
      summaryEn,
      summaryMs
    };

    setLastScanVerdict(verdict);
    setIsScanningTransfer(false);

    // Record transaction
    const newTx: Transaction = {
      id: 'tx-' + Math.random().toString(36).substring(2, 7),
      recipient: details.recipientName || 'Beneficiary',
      bank: details.bank,
      accountNumber: details.accountNumber,
      amount: details.amount,
      date: 'Just Now',
      category: 'P2P Transfer',
      type: 'debit',
      status: action === 'FREEZE_30_MIN' ? 'FROZEN' : action === 'ALERT_ADMIN' ? 'HELD' : 'COMPLETED',
      riskScore: calculatedScore
    };
    addTransaction(newTx);

    // Push new case to Admin Panel if High/Medium
    if (tier !== 'LOW') {
      const newCase: FraudCase = {
        id: 'case-' + Math.random().toString(36).substring(2, 7),
        userId: 'usr-9012',
        userName: 'JOHN DOE',
        triggerType: 'TRANSACTION',
        timestamp: 'Just Now',
        riskScore: calculatedScore,
        status: action === 'FREEZE_30_MIN' ? 'FROZEN' : 'PENDING_REVIEW',
        actionTaken: action,
        summaryEn,
        summaryMs,
        workerFindings: [
          { workerName: 'Financial Worker', score: calculatedScore, status: 'CRITICAL', evidence: [`High transaction velocity`, `Amount RM ${details.amount} > 90-day baseline`] },
          { workerName: 'Research Worker', score: isHighRisk ? 90 : 30, status: isHighRisk ? 'CRITICAL' : 'SAFE', evidence: [`Blacklist lookup for ${details.accountNumber}`] }
        ],
        associatedCaseId: details.associatedCaseId
      };
      setFraudCases((prev) => [newCase, ...prev]);
      setSelectedCaseId(newCase.id);
    }
  }, [addTransaction]);

  const clearScanVerdict = useCallback(() => {
    setLastScanVerdict(null);
  }, []);

  // Phishing Scan Simulation
  const submitPhishingScan = useCallback(async (_file: File) => {
    setIsScanningPhishing(true);
    setPhishingResult(null);

    await new Promise((res) => setTimeout(res, 2200));

    const extractedText = `URGENT NOTICE: Your bank account will be suspended within 2 hours due to unauthorized login from IP 192.168.1.1. Click http://maybank2u-safe-verify.com/login.apk to verify your identity.`;
    const caseId = 'case-phish-' + Math.random().toString(36).substring(2, 7);

    const result = {
      scamDetected: true,
      confidence: 94,
      extractedText,
      verdict: 'HIGH RISK PHISHING LURE DETECTED: Contains fake domain masquerading as Maybank2u and malicious APK download payload.',
      caseId
    };

    setPhishingResult(result);
    setIsScanningPhishing(false);

    // Push to admin cases
    const newCase: FraudCase = {
      id: caseId,
      userId: 'usr-9012',
      userName: 'JOHN DOE',
      triggerType: 'PHISHING',
      timestamp: 'Just Now',
      riskScore: 94,
      status: 'BLOCKED',
      actionTaken: 'BLOCK_TRANSACTION',
      summaryEn: result.verdict,
      summaryMs: 'LURE PANCINGAN DATA BERISIKO TINGGI DIKESAN: Mengandungi domain palsu menyamar sebagai Maybank2u dan fail APK berbahaya.',
      workerFindings: [
        { workerName: 'Phishing Worker', score: 96, status: 'CRITICAL', evidence: ['Fake Maybank domain detected', 'Malicious APK payload lure'] },
        { workerName: 'Research Worker', score: 92, status: 'CRITICAL', evidence: ['Domain registered 2 days ago', 'Matched 8 SMS phishing reports'] }
      ],
      ocrText: extractedText
    };

    setFraudCases((prev) => [newCase, ...prev]);
    setSelectedCaseId(caseId);
  }, []);

  // Update Admin Case Action
  const updateCaseStatus = useCallback((id: string, status: FraudCase['status'], action?: FraudCase['actionTaken']) => {
    setFraudCases((prev) =>
      prev.map((c) => (c.id === id ? { ...c, status, actionTaken: action || c.actionTaken } : c))
    );
  }, []);

  return (
    <SimulationContext.Provider
      value={{
        sessionId,
        accountBalance,
        setAccountBalance,
        transactions,
        addTransaction,

        isCallRinging,
        isCallConnected,
        callMode,
        callerId,
        spoofedCallerNumber,
        setSpoofedCallerNumber,
        suspicionScore,
        transcript,
        verificationAnchors,

        triggerIncomingCall,
        answerCall,
        declineCall,
        endCall,
        switchCallMode,
        injectScammerSpeech,

        isScanningTransfer,
        scannerLogs,
        lastScanVerdict,
        submitTransferScan,
        clearScanVerdict,

        isScanningPhishing,
        phishingResult,
        submitPhishingScan,

        fraudCases,
        selectedCaseId,
        setSelectedCaseId,
        updateCaseStatus
      }}
    >
      {children}
    </SimulationContext.Provider>
  );
};

export const useSimulation = () => {
  const context = useContext(SimulationContext);
  if (!context) {
    throw new Error('useSimulation must be used within a SimulationProvider');
  }
  return context;
};
