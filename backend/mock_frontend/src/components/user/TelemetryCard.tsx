import React, { useState } from 'react';
import type { BackendConfig, XaiReport } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { SessionWebSocketClient } from '../../services/websocket';
import { Activity, FileText } from 'lucide-react';

interface TelemetryCardProps {
  config: BackendConfig;
  userId: string;
  onOpenXaiReport: (report: XaiReport) => void;
}

export const TelemetryCard: React.FC<TelemetryCardProps> = ({
  config,
  userId,
  onOpenXaiReport,
}) => {
  const [deviceId, setDeviceId] = useState('dev-macbook-pro-2026');
  const [avgFlightTime, setAvgFlightTime] = useState('650'); // Slow flight time simulating dictation/coercion
  const [screenShare, setScreenShare] = useState(true);
  const [copyPaste, setCopyPaste] = useState(true);

  const [loading, setLoading] = useState(false);
  const [statusLog, setStatusLog] = useState<string[]>([]);
  const [result, setResult] = useState<XaiReport | null>(null);

  const handleScanTelemetry = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setStatusLog(['Sending telemetry biometric payload...']);
    setResult(null);

    const client = new TranSafeApiClient(config);
    const sessionId = `sess-tel-${Date.now()}`;

    try {
      const wsClient = new SessionWebSocketClient();
      wsClient.connect(
        config.baseUrl,
        sessionId,
        (msg) => {
          if (msg.message || msg.status) {
            setStatusLog((prev) => [...prev, msg.message || msg.status || '']);
          }
          if (msg.type === 'result' && msg.data) {
            setResult(msg.data);
            setLoading(false);
            wsClient.close();
          }
        },
        (_err) => {
          setStatusLog((prev) => [...prev, 'WebSocket error']);
          setLoading(false);
        },
        () => {}
      );

      await client.triggerTelemetry({
        user_id: userId,
        session_id: sessionId,
        device_id: deviceId,
        session_metrics: {
          active_seconds: 140,
          tab_switches: 8,
          copy_paste_events: copyPaste ? 3 : 0,
        },
        behavioral_biometrics: {
          avg_flight_time_ms: parseInt(avgFlightTime),
          backspace_count: 14,
          screen_share_detected: screenShare,
        },
        browser_network_fingerprint: {
          vpn_detected: false,
          ip_location: 'Kuala Lumpur, MY',
        },
      });
    } catch (err: any) {
      setStatusLog((prev) => [...prev, `Error: ${err.message}`]);
      setLoading(false);
    }
  };

  return (
    <div className="card test-card">
      <div className="card-header">
        <div className="card-title">
          <Activity className="card-icon" size={20} />
          <h3>Behavioral Telemetry Analysis</h3>
        </div>
        <span className="card-tag">FR-T01</span>
      </div>

      <form onSubmit={handleScanTelemetry} className="card-form">
        <div className="form-row">
          <div className="form-group">
            <label>Device ID</label>
            <input
              type="text"
              value={deviceId}
              onChange={(e) => setDeviceId(e.target.value)}
              required
            />
          </div>
          <div className="form-group">
            <label>Avg Keystroke Flight Time (ms)</label>
            <input
              type="number"
              value={avgFlightTime}
              onChange={(e) => setAvgFlightTime(e.target.value)}
              required
            />
            <small>Normal: ~300ms | Slow (Coercion): {'>'} 500ms</small>
          </div>
        </div>

        <div className="form-row checkboxes">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={screenShare}
              onChange={(e) => setScreenShare(e.target.checked)}
            />
            Active Screen Share / Remote Control Flag
          </label>

          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={copyPaste}
              onChange={(e) => setCopyPaste(e.target.checked)}
            />
            Copy-Pasted Recipient Details (from WhatsApp)
          </label>
        </div>

        <button type="submit" className="btn-primary" disabled={loading}>
          {loading ? 'Evaluating Telemetry...' : 'Trigger Telemetry Risk Scan'}
        </button>
      </form>

      {statusLog.length > 0 && (
        <div className="status-log-box">
          <div className="log-entries">
            {statusLog.map((log, index) => (
              <div key={index} className="log-line">▸ {log}</div>
            ))}
          </div>
        </div>
      )}

      {result && (
        <div className={`result-box tier-${result.risk_tier.toLowerCase()}`}>
          <div className="result-header">
            <h4>Telemetry Score: {result.risk_score}/100 ({result.risk_tier})</h4>
            <button className="btn-small" onClick={() => onOpenXaiReport(result)}>
              <FileText size={14} /> View XAI Report
            </button>
          </div>
          <p>{result.verdict_summary}</p>
        </div>
      )}
    </div>
  );
};
