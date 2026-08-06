import { TranSafeApiClient } from './api';
import type { BackendConfig } from '../types/api';

export interface BrowserNetworkFingerprint {
  browser_fingerprint_hash: string;
  user_agent: string;
  screen_resolution: string;
  network_type: string;
  browser_timezone: string;
}

export interface SessionMetrics {
  time_on_page_seconds: number;
  tab_switch_count: number;
  page_focused: boolean;
}

export interface BehavioralBiometrics {
  is_account_number_pasted: boolean;
  avg_keystroke_flight_time_ms: number | null;
  backspace_count: number;
  mouse_cursor_erratic_score: number;
  device_tremor_detected: boolean;
}

export class PassiveTelemetryTracker {
  private config: BackendConfig;
  private userId: string;
  private sessionId: string;
  private deviceId: string;
  private lastKeyDownTime: number | null = null;
  private flightTimes: number[] = [];
  private backspaceCount: number = 0;
  private tabSwitchCount: number = 0;
  private copyPasteCount: number = 0;
  private isAccountPasted: boolean = false;
  private pageStartTime: number = Date.now();
  private active: boolean = false;
  private cleanupFns: Array<() => void> = [];

  constructor(config: BackendConfig, userId: string, sessionId: string, deviceId = 'device_web_001') {
    this.config = config;
    this.userId = userId;
    this.sessionId = sessionId;
    this.deviceId = deviceId;
  }

  public updateSession(userId: string, sessionId: string) {
    this.userId = userId;
    this.sessionId = sessionId;
    this.pageStartTime = Date.now();
    this.flightTimes = [];
    this.backspaceCount = 0;
    this.tabSwitchCount = 0;
    this.copyPasteCount = 0;
    this.isAccountPasted = false;
  }

  public start() {
    if (this.active) return;
    this.active = true;

    const client = new TranSafeApiClient(this.config);

    // 1. Tab Switch listener (visibilitychange)
    const handleVisibilityChange = () => {
      if (document.hidden && this.active) {
        this.tabSwitchCount++;
        client.ingestTelemetryEvent({
          user_id: this.userId,
          session_id: this.sessionId,
          device_id: this.deviceId,
          event_type: 'TAB_SWITCH',
          event_value: 'true',
        }).catch((err) => console.debug('Telemetry ingest tab_switch error:', err));
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    this.cleanupFns.push(() => document.removeEventListener('visibilitychange', handleVisibilityChange));
  }

  public trackKeyDown(keyName?: string) {
    this.lastKeyDownTime = performance.now();
    if (keyName === 'Backspace' || keyName === 'Delete') {
      this.backspaceCount++;
    }
  }

  public trackKeyUp() {
    if (this.lastKeyDownTime !== null) {
      const flightTime = Math.round(performance.now() - this.lastKeyDownTime);
      this.lastKeyDownTime = null;

      if (flightTime > 0 && flightTime < 5000) {
        this.flightTimes.push(flightTime);
        const client = new TranSafeApiClient(this.config);
        client.ingestTelemetryEvent({
          user_id: this.userId,
          session_id: this.sessionId,
          device_id: this.deviceId,
          event_type: 'KEYSTROKE',
          event_value: String(flightTime),
        }).catch((err) => console.debug('Telemetry ingest flight_time error:', err));
      }
    }
  }

  public trackPaste(fieldName?: string) {
    this.copyPasteCount++;
    if (fieldName === 'recipientAccount' || fieldName === 'recipient') {
      this.isAccountPasted = true;
    }
    const client = new TranSafeApiClient(this.config);
    client.ingestTelemetryEvent({
      user_id: this.userId,
      session_id: this.sessionId,
      device_id: this.deviceId,
      event_type: 'COPY_PASTE',
      event_value: fieldName || 'true',
    }).catch((err) => console.debug('Telemetry ingest paste error:', err));
  }

  public getSessionMetrics(): SessionMetrics {
    const elapsedSeconds = Math.round((Date.now() - this.pageStartTime) / 1000);
    return {
      time_on_page_seconds: Math.max(elapsedSeconds, 1),
      tab_switch_count: this.tabSwitchCount,
      page_focused: !document.hidden,
    };
  }

  public getBehavioralBiometrics(): BehavioralBiometrics {
    const avgFlight = this.flightTimes.length
      ? Math.round(this.flightTimes.reduce((a, b) => a + b, 0) / this.flightTimes.length)
      : null;

    return {
      is_account_number_pasted: this.isAccountPasted,
      avg_keystroke_flight_time_ms: avgFlight,
      backspace_count: this.backspaceCount,
      mouse_cursor_erratic_score: 15,
      device_tremor_detected: false,
    };
  }

  public getBrowserNetworkFingerprint(): BrowserNetworkFingerprint {
    const navAny = navigator as any;
    const netType = navAny.connection?.effectiveType || (navAny.onLine ? 'wifi' : 'offline');
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Kuala_Lumpur';
    const res = `${window.screen?.width || 1440}x${window.screen?.height || 900}`;
    const ua = navigator.userAgent || 'Mozilla/5.0 (Macintosh)';
    const fpHash = String(Math.abs(this.hashCode(ua + res + tz))).substring(0, 12);

    return {
      browser_fingerprint_hash: fpHash || 'a8f9c102b44e',
      user_agent: ua,
      screen_resolution: res,
      network_type: netType,
      browser_timezone: tz,
    };
  }

  private hashCode(str: string): number {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = (hash << 5) - hash + str.charCodeAt(i);
      hash |= 0;
    }
    return hash;
  }

  public stop() {
    this.active = false;
    this.cleanupFns.forEach((fn) => fn());
    this.cleanupFns = [];
  }
}
