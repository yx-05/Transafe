import React, { useState, useEffect } from 'react';
import type { AnalyticsSummary, BackendConfig } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { BarChart3, Cpu } from 'lucide-react';

interface AnalyticsCardProps {
  config: BackendConfig;
}

export const AnalyticsCard: React.FC<AnalyticsCardProps> = ({ config }) => {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fetchAnalytics = async () => {
      setLoading(true);
      const client = new TranSafeApiClient(config);
      try {
        const sumRes = await client.getAnalyticsSummary();
        setSummary(sumRes);
      } catch (err: any) {
        console.error('Analytics fetch failed', err);
      } finally {
        setLoading(false);
      }
    };

    fetchAnalytics();
  }, [config.baseUrl, config.adminKey]);

  return (
    <div className="card test-card admin-card">
      <div className="card-header">
        <div className="card-title">
          <BarChart3 className="card-icon" size={20} />
          <h3>Fraud Operations Analytics</h3>
        </div>
        <span className="card-tag">FR-A05</span>
      </div>

      {loading ? (
        <p>Loading analytics summary data...</p>
      ) : summary ? (
        <div className="analytics-dashboard">
          <div className="metrics-grid">
            <div className="metric-box">
              <span className="metric-label">Total Fraud Cases</span>
              <span className="metric-value">{summary.total_cases}</span>
            </div>

            <div className="metric-box highlight-green">
              <span className="metric-label">Amount Protected</span>
              <span className="metric-value">RM {summary.total_amount_protected_myr.toLocaleString()}</span>
            </div>

            <div className="metric-box highlight-red">
              <span className="metric-label">Accounts Frozen</span>
              <span className="metric-value">{summary.accounts_frozen}</span>
            </div>

            <div className="metric-box">
              <span className="metric-label">Avg Risk Score</span>
              <span className="metric-value">{summary.avg_risk_score}/100</span>
            </div>
          </div>

          <div className="analytics-breakdowns">
            <div className="breakdown-card">
              <h4>Risk Tier Distribution</h4>
              <div className="bar-list">
                <div className="bar-row">
                  <span>HIGH Risk ({summary.by_risk_tier.HIGH})</span>
                  <div className="bar-bg"><div className="bar-fill high" style={{ width: `${(summary.by_risk_tier.HIGH / summary.total_cases) * 100}%` }}></div></div>
                </div>
                <div className="bar-row">
                  <span>MEDIUM Risk ({summary.by_risk_tier.MEDIUM})</span>
                  <div className="bar-bg"><div className="bar-fill medium" style={{ width: `${(summary.by_risk_tier.MEDIUM / summary.total_cases) * 100}%` }}></div></div>
                </div>
                <div className="bar-row">
                  <span>LOW Risk ({summary.by_risk_tier.LOW})</span>
                  <div className="bar-bg"><div className="bar-fill low" style={{ width: `${(summary.by_risk_tier.LOW / summary.total_cases) * 100}%` }}></div></div>
                </div>
              </div>
            </div>

            <div className="breakdown-card">
              <h4><Cpu size={16} /> Agent Activation Counts</h4>
              <ul className="simple-list">
                {Object.entries(summary.worker_activation_counts || {}).map(([worker, count]) => (
                  <li key={worker}>
                    <strong>{worker.toUpperCase()} Worker:</strong> {count} activations
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      ) : (
        <p>No analytics data available.</p>
      )}
    </div>
  );
};
