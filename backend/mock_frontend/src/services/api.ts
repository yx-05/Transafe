import type {
  AccountActionData,
  AdminAlertItem,
  AdminCaseListResponse,
  AnalyticsSummary,
  AnalyticsTrendPoint,
  BackendConfig,
  BiometricResultData,
  BiometricResultRequest,
  CallTakeoverData,
  CallTriggerData,
  CallTriggerRequest,
  PhishingTriggerData,
  PhishingTriggerRequest,
  RecentCasesData,
  ReportTriggerData,
  ReportTriggerRequest,
  ResponseEnvelope,
  TelemetryTriggerData,
  TelemetryTriggerRequest,
  TransactionTriggerData,
  TransactionTriggerRequest,
} from '../types/api';

async function fetchEnvelope<T>(
  url: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(url, options);
  const json: ResponseEnvelope<T> = await res.json();
  
  if (!res.ok || !json.success) {
    const errorMsg = json.error?.message || `HTTP ${res.status} ${res.statusText}`;
    throw new Error(errorMsg);
  }
  
  if (json.data === null) {
    throw new Error('Backend returned null data envelope');
  }
  
  return json.data;
}

export class TranSafeApiClient {
  private config: BackendConfig;

  constructor(config: BackendConfig) {
    this.config = config;
  }

  private get headers(): Record<string, string> {
    return {
      'Content-Type': 'application/json',
      'X-API-Key': this.config.apiKey,
    };
  }

  private get adminHeaders(): Record<string, string> {
    return {
      'Content-Type': 'application/json',
      'X-API-Key': this.config.apiKey,
      'X-Admin-Key': this.config.adminKey,
    };
  }

  // --- USER TRIGGERS ---

  async triggerTelemetry(payload: TelemetryTriggerRequest): Promise<TelemetryTriggerData> {
    return fetchEnvelope<TelemetryTriggerData>(`${this.config.baseUrl}/api/v1/trigger/telemetry`, {
      method: 'POST',
      headers: this.headers,
      body: JSON.stringify(payload),
    });
  }

  async triggerTransaction(payload: TransactionTriggerRequest): Promise<TransactionTriggerData> {
    return fetchEnvelope<TransactionTriggerData>(`${this.config.baseUrl}/api/v1/trigger/transaction`, {
      method: 'POST',
      headers: this.headers,
      body: JSON.stringify(payload),
    });
  }

  async triggerCall(payload: CallTriggerRequest): Promise<CallTriggerData> {
    return fetchEnvelope<CallTriggerData>(`${this.config.baseUrl}/api/v1/trigger/call`, {
      method: 'POST',
      headers: this.headers,
      body: JSON.stringify(payload),
    });
  }

  async triggerPhishing(payload: PhishingTriggerRequest): Promise<PhishingTriggerData> {
    return fetchEnvelope<PhishingTriggerData>(`${this.config.baseUrl}/api/v1/trigger/phishing`, {
      method: 'POST',
      headers: this.headers,
      body: JSON.stringify(payload),
    });
  }

  async triggerReport(payload: ReportTriggerRequest): Promise<ReportTriggerData> {
    return fetchEnvelope<ReportTriggerData>(`${this.config.baseUrl}/api/v1/trigger/report`, {
      method: 'POST',
      headers: this.headers,
      body: JSON.stringify(payload),
    });
  }

  async submitBiometricResult(payload: BiometricResultRequest): Promise<BiometricResultData> {
    return fetchEnvelope<BiometricResultData>(`${this.config.baseUrl}/api/v1/biometric/result`, {
      method: 'POST',
      headers: this.headers,
      body: JSON.stringify(payload),
    });
  }

  async takeoverCall(sessionId: string): Promise<CallTakeoverData> {
    return fetchEnvelope<CallTakeoverData>(`${this.config.baseUrl}/api/v1/call/${sessionId}/takeover`, {
      method: 'POST',
      headers: this.headers,
    });
  }

  async getRecentCases(userId: string): Promise<RecentCasesData> {
    return fetchEnvelope<RecentCasesData>(`${this.config.baseUrl}/api/v1/cases/recent?user_id=${encodeURIComponent(userId)}`, {
      method: 'GET',
      headers: this.headers,
    });
  }

  // --- ADMIN API ---

  async listAdminCases(page = 1, pageSize = 20, riskTier = 'all', status = 'all'): Promise<AdminCaseListResponse> {
    const params = new URLSearchParams({
      page: page.toString(),
      page_size: pageSize.toString(),
      risk_tier: riskTier,
      status: status,
    });
    return fetchEnvelope<AdminCaseListResponse>(`${this.config.baseUrl}/admin/v1/cases?${params}`, {
      method: 'GET',
      headers: this.adminHeaders,
    });
  }

  async getCaseDetail(caseId: string): Promise<Record<string, unknown>> {
    return fetchEnvelope<Record<string, unknown>>(`${this.config.baseUrl}/admin/v1/cases/${encodeURIComponent(caseId)}`, {
      method: 'GET',
      headers: this.adminHeaders,
    });
  }

  async freezeAccount(account: string, reason: string): Promise<AccountActionData> {
    return fetchEnvelope<AccountActionData>(`${this.config.baseUrl}/admin/v1/accounts/${encodeURIComponent(account)}/freeze`, {
      method: 'POST',
      headers: this.adminHeaders,
      body: JSON.stringify({ reason }),
    });
  }

  async unfreezeAccount(account: string, reason: string): Promise<AccountActionData> {
    return fetchEnvelope<AccountActionData>(`${this.config.baseUrl}/admin/v1/accounts/${encodeURIComponent(account)}/unfreeze`, {
      method: 'POST',
      headers: this.adminHeaders,
      body: JSON.stringify({ reason }),
    });
  }

  async getAnalyticsSummary(): Promise<AnalyticsSummary> {
    return fetchEnvelope<AnalyticsSummary>(`${this.config.baseUrl}/admin/v1/analytics/summary`, {
      method: 'GET',
      headers: this.adminHeaders,
    });
  }

  async getAnalyticsTrend(): Promise<{ series: AnalyticsTrendPoint[] }> {
    return fetchEnvelope<{ series: AnalyticsTrendPoint[] }>(`${this.config.baseUrl}/admin/v1/analytics/trend`, {
      method: 'GET',
      headers: this.adminHeaders,
    });
  }

  async listAdminAlerts(): Promise<{ items: AdminAlertItem[]; total: number }> {
    return fetchEnvelope<{ items: AdminAlertItem[]; total: number }>(`${this.config.baseUrl}/admin/v1/alerts`, {
      method: 'GET',
      headers: this.adminHeaders,
    });
  }

  async updateAdminAlert(alertId: string, status: string): Promise<{ alert_id: string; status: string }> {
    return fetchEnvelope<{ alert_id: string; status: string }>(`${this.config.baseUrl}/admin/v1/alerts/${encodeURIComponent(alertId)}`, {
      method: 'PATCH',
      headers: this.adminHeaders,
      body: JSON.stringify({ status }),
    });
  }
}
