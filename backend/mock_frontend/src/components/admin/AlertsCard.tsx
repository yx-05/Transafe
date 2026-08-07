import React, { useState, useEffect } from 'react';
import type { AdminAlertItem, BackendConfig } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { Bell, CheckCircle2, Clock, RefreshCw } from 'lucide-react';

interface AlertsCardProps {
  config: BackendConfig;
}

export const AlertsCard: React.FC<AlertsCardProps> = ({ config }) => {
  const [alerts, setAlerts] = useState<AdminAlertItem[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchAlerts = async () => {
    setLoading(true);
    const client = new TranSafeApiClient(config);
    try {
      const res = await client.listAdminAlerts();
      setAlerts(res.items || []);
    } catch (err: any) {
      console.error('Fetch alerts error', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
  }, [config.baseUrl, config.adminKey]);

  const handleResolveAlert = async (alertId: string) => {
    const client = new TranSafeApiClient(config);
    try {
      await client.updateAdminAlert(alertId, 'reviewed');
      setAlerts(alerts.filter((a) => a.alert_id !== alertId));
    } catch (err: any) {
      alert(`Update failed: ${err.message}`);
    }
  };

  return (
    <div className="card test-card admin-card">
      <div className="card-header">
        <div className="card-title">
          <Bell className="card-icon text-red" size={20} />
          <h3>Real-Time Admin Operations Alerts Queue</h3>
        </div>
        <button className="btn-icon-text" onClick={fetchAlerts} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh
        </button>
      </div>

      <div className="alerts-list">
        {alerts.length === 0 ? (
          <p className="placeholder-text">No unreviewed alerts in queue.</p>
        ) : (
          alerts.map((alert) => (
            <div key={alert.alert_id} className={`alert-card-item ${alert.status}`}>
              <div className="alert-header">
                <strong>ALERT: {alert.alert_type}</strong>
                <span className="alert-score">Risk Score: {alert.risk_score}/100</span>
              </div>
              <p>{alert.verdict_summary}</p>
              <div className="alert-meta">
                <span>Case ID: <code>{alert.case_id}</code></span>
                <span>Time: <Clock size={12} /> {new Date(alert.created_at).toLocaleTimeString()}</span>
              </div>
              <div className="alert-actions">
                {alert.status === 'pending' ? (
                  <button className="btn-small-success" onClick={() => handleResolveAlert(alert.alert_id)}>
                    <CheckCircle2 size={14} /> Mark Reviewed
                  </button>
                ) : (
                  <span className="reviewed-tag">✓ Reviewed</span>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
