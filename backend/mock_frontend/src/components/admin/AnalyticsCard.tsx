import React, { useState, useEffect } from 'react';
import type { AnalyticsSummary, AnalyticsTrendPoint, BackendConfig } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { BarChart3, Cpu, RefreshCw } from 'lucide-react';

interface AnalyticsCardProps {
  config: BackendConfig;
}

const maxTier = (t: AnalyticsTrendPoint[]) =>
  t.reduce((m, p) => Math.max(m, p.total), 1);

export const AnalyticsCard: React.FC<AnalyticsCardProps> = ({ config }) => {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [trend, setTrend] = useState<AnalyticsTrendPoint[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchAnalytics = async () => {
    setLoading(true);
    const client = new TranSafeApiClient(config);
    try {
      const sumRes = await client.getAnalyticsSummary();
      setSummary(sumRes);
      const trendRes = await client.getAnalyticsTrend();
      setTrend(trendRes.series || []);
    } catch (err: any) {
      console.error('Analytics fetch failed', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAnalytics();
  }, [config.baseUrl, config.adminKey]);

  const totalCases = summary?.total_cases || 1;

  return (
    <div className="card test-card admin-card">
      <div className="card-header">
        <div className="card-title">
          <BarChart3 className="card-icon" size={20} />
          <h3>Fraud Operations Analytics</h3>
        </div>
        <button className="btn-icon-text" onClick={fetchAnalytics} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh
        </button>
      </div>

      {loading && !summary ? (
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
                  <div className="bar-bg"><div className="bar-fill high" style={{ width: `${(summary.by_risk_tier.HIGH / totalCases) * 100}%` }}></div></div>
                </div>
                <div className="bar-row">
                  <span>MEDIUM Risk ({summary.by_risk_tier.MEDIUM})</span>
                  <div className="bar-bg"><div className="bar-fill medium" style={{ width: `${(summary.by_risk_tier.MEDIUM / totalCases) * 100}%` }}></div></div>
                </div>
                <div className="bar-row">
                  <span>LOW Risk ({summary.by_risk_tier.LOW})</span>
                  <div className="bar-bg"><div className="bar-fill low" style={{ width: `${(summary.by_risk_tier.LOW / totalCases) * 100}%` }}></div></div>
                </div>
              </div>
            </div>

            <div className="breakdown-card">
              <h4><Cpu size={16} /> Agent Activation Counts</h4>
              <ul className="simple-list">
                {Object.keys(summary.worker_activation_counts || {}).length === 0 ? (
                  <li className="placeholder-text">No worker activations recorded yet.</li>
                ) : (
                  Object.entries(summary.worker_activation_counts || {}).map(([worker, count]) => (
                    <li key={worker}>
                      <strong>{worker.toUpperCase()} Worker:</strong> {count} activations
                    </li>
                  ))
                )}
              </ul>
            </div>
          </div>

          {trend.length > 0 && (
            <div className="breakdown-card trend-card">
              <h4>Case Trend (Last {trend.length} Days)</h4>
              <div className="trend-bars">
                {trend.map((point) => (
                  <div key={point.date} className="trend-col" title={`${point.date}: ${point.total} cases (H:${point.HIGH} M:${point.MEDIUM} L:${point.LOW})`}>
                    <div className="trend-bar-wrap">
                      <div className="trend-bar high" style={{ height: `${(point.HIGH / maxTier(trend)) * 100}%` }}></div>
                      <div className="trend-bar medium" style={{ height: `${(point.MEDIUM / maxTier(trend)) * 100}%` }}></div>
                      <div className="trend-bar low" style={{ height: `${(point.LOW / maxTier(trend)) * 100}%` }}></div>
                    </div>
                    <span className="trend-label">{point.date.slice(5)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        <p>No analytics data available.</p>
      )}
    </div>
  );
};
