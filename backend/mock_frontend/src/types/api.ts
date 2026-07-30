// TypeScript interfaces for TranSafe Backend API & WebSocket Payloads

export type TriggerType = 'TELEMETRY' | 'TRANSACTION' | 'CALL' | 'PHISHING' | 'REPORT';
export type RiskTier = 'LOW' | 'MEDIUM' | 'HIGH';
export type CallMode = 'LISTEN' | 'AUTO_TALK';
export type CallChannel = 'WEBRTC' | 'IN_APP_VOIP';

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
}

export interface CallPayload {
  caller_number: string;
  caller_name?: string;
  call_mode: CallMode;
  call_channel: CallChannel;
}

export interface CallTriggerRequest {
  user_id: string;
  session_id: string;
  call: CallPayload;
}

export interface PhishingMaterial {
  source_type: 'TEXT' | 'URL' | 'IMAGE';
  content: string; // Plain text, URL, or Base64 image
}

export interface PhishingTriggerRequest {
  user_id: string;
  session_id: string;
  phishing_material: PhishingMaterial;
  associated_case_id?: string;
}

export interface FraudReportPayload {
  phone_numbers: string[];
  bank_accounts: string[];
  description: string;
}

export interface ReportTriggerRequest {
  user_id: string;
  report: FraudReportPayload;
}

export interface BiometricResultRequest {
  user_id: string;
  session_id: string;
  transaction_id: string;
  biometric_result: 'PASSED' | 'FAILED' | 'DECLINED';
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

export interface ReportTriggerData {
  case_id: string;
  message: string;
  entities_recorded: {
    phone_numbers: string[];
    bank_accounts: string[];
  };
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
  created_at: string;
}

export interface RecentCasesData {
  has_recent_activity: boolean;
  recent_cases: RecentCaseItem[];
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
  type: 'pre_check' | 'transcript' | 'highlight' | 'takeover' | 'mode_change' | 'ended';
  speaker?: 'CALLER' | 'VICTIM' | 'TRANSAFE_AI';
  text?: string;
  highlighted_spans?: Array<{
    phrase: string;
    risk_level: string;
    reason: string;
  }>;
  call_mode?: CallMode;
  warning?: string;
  pre_check?: CallPreCheck;
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
  verdict_summary: string;
}

export interface AdminCaseListResponse {
  items: AdminCaseItem[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
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
