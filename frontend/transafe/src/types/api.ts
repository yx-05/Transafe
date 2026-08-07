// TypeScript interfaces for TranSafe Backend API & WebSocket Payloads

export type TriggerType = 'TELEMETRY' | 'TRANSACTION' | 'CALL' | 'PHISHING' | 'REPORT';
export type RiskTier = 'LOW' | 'MEDIUM' | 'HIGH';
export type CallMode = 'LISTEN' | 'AUTO_TALK';
export type CallChannel = 'WEBRTC' | 'IN_APP_VOIP';
export type UserLabel = 'unlabeled' | 'fraud' | 'benign';

export interface BackendConfig {
  baseUrl: string;
  apiKey: string;
  adminKey: string;
}

export interface ResponseEnvelope<T> {
  success: boolean;
  data: T | null;
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  } | null;
  timestamp: string;
}

// ---------------- USER TRIGGER REQUESTS ----------------

export interface TelemetryTriggerRequest {
  user_id: string;
  session_id: string;
  device_id: string;
  session_metrics?: Record<string, unknown>;
  behavioral_biometrics?: Record<string, unknown>;
  browser_network_fingerprint?: Record<string, unknown>;
}

export interface TransactionPayload {
  transaction_id: string;
  sender_account: string;
  recipient_account: string;
  recipient_name?: string;
  amount: number;
  currency: string;
  description: string;
  initiated_at: string;
}

export interface TransactionTriggerRequest {
  user_id: string;
  session_id: string;
  transaction: TransactionPayload;
  associated_case_id?: string;
  session_metrics?: Record<string, any>;
  behavioral_biometrics?: Record<string, any>;
  browser_network_fingerprint?: Record<string, any>;
}

export interface CallPayload {
  caller_number: string;
  caller_name?: string;
  call_mode: CallMode;
  call_channel: CallChannel;
  received_at?: string;
  stt_engine?: string;
  auto_autotalk_on_unknown?: boolean;
}

export interface CallTriggerRequest {
  user_id: string;
  session_id: string;
  call: CallPayload;
}

export interface PhishingMaterial {
  content_type: 'TEXT' | 'URL' | 'IMAGE';
  content: string; // Plain text, URL, or Base64 image
  source?: string; // SMS | WHATSAPP | EMAIL | WEBSITE | OTHER
}

export type PhishingTriggerRequest = {
  user_id: string;
  session_id: string;
  material: PhishingMaterial;
  associated_case_id?: string;
};

export interface BiometricResultRequest {
  user_id: string;
  session_id: string;
  transaction_id: string;
  biometric_result: 'PASSED' | 'FAILED' | 'DECLINED';
  method?: string;
  attempted_at?: string;
}

// ---------------- RESPONSE DATA SCHEMAS ----------------

export interface TelemetryTriggerData {
  session_id: string;
  message: string;
}

export interface TransactionTriggerData {
  session_id: string;
  transaction_id: string;
  message: string;
  estimated_seconds: number;
}

export interface CallPreCheck {
  blacklisted: boolean;
  blacklist_cases: number;
  initial_risk: RiskTier;
  warning?: string;
}

export interface CallTriggerData {
  session_id: string;
  call_session_id: string;
  call_mode: CallMode;
  call_channel: CallChannel;
  pre_check: CallPreCheck;
  message: string;
  ws_audio_url: string;
  ws_events_url: string;
}

export interface PhishingTriggerData {
  session_id: string;
  message: string;
  estimated_seconds: number;
}

export interface BiometricResultData {
  session_id: string;
  transaction_id: string;
  transaction_status: string;
  message: string;
  message_ms: string;
}

export interface CallTakeoverData {
  session_id: string;
  call_mode: CallMode;
  message: string;
  ws_events_url: string;
}

export interface RecentCaseItem {
  case_id: string;
  trigger_type: TriggerType;
  caller_number?: string;
  risk_tier: RiskTier;
  risk_score: number;
  status: string;
  user_label: UserLabel;
  archetype?: string;
  snippet?: string;
  created_at: string;
}

export interface RecentCasesData {
  has_recent_activity: boolean;
  recent_cases: RecentCaseItem[];
}

export interface CaseLabelData {
  case_id: string;
  user_label: UserLabel;
  message: string;
}

// ---------------- EXPLAINABLE AI (XAI) & WS MESSAGES ----------------

export interface WorkerFinding {
  worker: string;
  score: number;
  confidence: number;
  evidence: string[];
  error?: string;
}

export interface XaiReport {
  session_id: string;
  trigger_type: TriggerType;
  risk_score: number;
  risk_tier: RiskTier;
  verdict_summary: string;
  verdict_summary_ms?: string;
  workers_activated: string[];
  worker_findings: WorkerFinding[];
  action_taken: string;
  unfreeze_at?: string;
  recommendation?: string;
  case_id?: string;
  associated_case_id?: string;
}

export interface WsSessionMessage {
  type: 'status' | 'progress' | 'result' | 'error';
  status?: string;
  worker?: string;
  message?: string;
  data?: XaiReport;
  error?: string;
}

export interface WsCallEventMessage {
  type: 'pre_check' | 'pre_check_result' | 'transcript' | 'transcript_interim' | 'highlight' | 'suspicion_update' | 'deep_analysis' | 'takeover' | 'mode_change' | 'talking' | 'call_ended' | 'ended' | 'stt_status';
  call_session_id?: string;
  speaker?: 'CALLER' | 'VICTIM' | 'TRANSAFE_AI' | 'SCAMMER' | 'CUSTOMER';
  text?: string;
  is_final?: boolean;
  status?: string;
  suspicion_score?: number;
  risk_tier?: 'LOW' | 'MEDIUM' | 'HIGH';
  utterance_risk_score?: number;
  trigger_escalation?: boolean;
  escalation_reason?: string;
  evidence?: string[];
  reason?: string;
  score?: number;
  confidence?: number;
  extracted_entities?: {
    phone_numbers?: string[];
    urls?: string[];
    bank_accounts?: string[];
  };
  research?: {
    queried?: boolean;
    decision?: string;
    reasoning?: string;
    queries?: string[];
    web_hits?: Array<{
      title?: string;
      url?: string;
    }>;
  };
  blacklisted?: boolean;
  blacklist_case_count?: number;
  spoofed_prefix?: boolean;
  initial_risk?: 'LOW' | 'MEDIUM' | 'HIGH';
  warning_text?: string;
  warning_text_ms?: string;
  highlighted_spans?: Array<{
    phrase: string;
    risk_level: string;
    reason: string;
    tag?: string;
    start?: number;
    end?: number;
    text?: string;
    utterance_risk_score?: number;
  }>;
  call_mode?: CallMode;
  warning?: string;
  pre_check?: CallPreCheck;
  tts_id?: string;
  action?: 'continue' | 'hangup';
  signal_detected?: boolean;
  next_aq?: string;
}

// ---------------- ADMIN ENDPOINTS ----------------

export interface AdminCaseItem {
  case_id: string;
  user_id: string;
  trigger_type: TriggerType;
  risk_score: number;
  risk_tier: RiskTier;
  status: string;
  action_taken: string;
  created_at: string;
  verdict_summary: string | null;
}

export interface AdminCaseListResponse {
  items: AdminCaseItem[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
}

export interface AdminAccountItem {
  id?: string;
  account_number: string;
  user_id?: string | null;
  account_type?: string | null;
  balance_myr?: number | null;
  status: 'active' | 'frozen' | 'closed';
  frozen_at?: string | null;
  frozen_by?: string | null;
  frozen_reason?: string | null;
  unfreeze_at?: string | null;
  created_at?: string;
}

export interface AccountActionData {
  account_number: string;
  status: 'frozen' | 'active';
  frozen_at?: string;
  unfrozen_at?: string;
  frozen_by?: string;
  unfrozen_by?: string;
  reason: string;
}

export interface CaseActionData {
  case_id: string;
  status: string;
  action_taken: string;
  unfreeze_at?: string | null;
  reason?: string | null;
}

export interface AdminCaseDetail {
  case_id?: string;
  id?: string;
  user_id: string;
  trigger_type: TriggerType;
  risk_score: number;
  risk_tier: RiskTier;
  status: string;
  action_taken: string;
  created_at?: string;
  updated_at?: string;
  transaction_id?: string | null;
  caller_number?: string | null;
  phishing_source?: string | null;
  user_label?: 'unlabeled' | 'fraud' | 'benign' | null;
  labeled_at?: string | null;
  xai_report?: Record<string, unknown> | null;
}

export interface AnalyticsSummary {
  period: { from: string; to: string };
  total_cases: number;
  by_risk_tier: { LOW: number; MEDIUM: number; HIGH: number };
  by_trigger_type: Record<string, number>;
  by_fraud_type: Record<string, number>;
  accounts_frozen: number;
  total_amount_protected_myr: number;
  avg_risk_score: number;
  worker_activation_counts: Record<string, number>;
}

export interface AnalyticsTrendPoint {
  date: string;
  total: number;
  HIGH: number;
  MEDIUM: number;
  LOW: number;
}

export interface AdminAlertItem {
  alert_id: string;
  case_id: string;
  alert_type: string;
  status: 'pending' | 'reviewed' | 'escalated';
  risk_score: number;
  verdict_summary: string;
  created_at: string;
}
