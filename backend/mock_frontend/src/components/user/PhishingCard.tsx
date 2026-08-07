import React, { useState } from 'react';
import type { BackendConfig, XaiReport } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { SessionWebSocketClient } from '../../services/websocket';
import { FileSearch, Upload, Image as ImageIcon, Link as LinkIcon, MessageSquare, FileText } from 'lucide-react';

interface PhishingCardProps {
  config: BackendConfig;
  userId: string;
  onOpenXaiReport: (report: XaiReport) => void;
}

export const PhishingCard: React.FC<PhishingCardProps> = ({
  config,
  userId,
  onOpenXaiReport,
}) => {
  const [sourceType, setSourceType] = useState<'TEXT' | 'URL' | 'IMAGE'>('TEXT');
  const [textContent, setTextContent] = useState(
    'URGENT: Your Maybank account has been locked. Verify immediately at http://maybank-verify-sec.com to avoid suspension.'
  );
  const [urlContent, setUrlContent] = useState('http://maybank-verify-sec.com');
  const [imageBase64, setImageBase64] = useState<string>('');
  const [imagePreview, setImagePreview] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [statusLog, setStatusLog] = useState<string[]>([]);
  const [result, setResult] = useState<XaiReport | null>(null);

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Backend rejects images whose decoded bytes exceed 10 MB.
    if (file.size > 10 * 1024 * 1024) {
      const sizeMb = (file.size / 1024 / 1024).toFixed(1);
      setStatusLog([`Image rejected: ${sizeMb} MB exceeds the 10 MB upload limit.`]);
      setImageBase64('');
      setImagePreview(null);
      e.target.value = '';
      return;
    }

    const reader = new FileReader();
    reader.onloadend = () => {
      const b64 = reader.result as string;
      setImageBase64(b64);
      setImagePreview(b64);
    };
    reader.readAsDataURL(file);
  };

  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setStatusLog(['Submitting phishing material for analysis...']);
    setResult(null);

    let contentToSend = '';
    if (sourceType === 'TEXT') contentToSend = textContent;
    else if (sourceType === 'URL') contentToSend = urlContent;
    else contentToSend = imageBase64;

    if (!contentToSend) {
      setStatusLog(['Please provide content for analysis']);
      setLoading(false);
      return;
    }

    const client = new TranSafeApiClient(config);
    const sessionId = `sess-phish-${Date.now()}`;

    // Map the UI source tab to the backend material.source taxonomy.
    const source =
      sourceType === 'TEXT' ? 'SMS' : sourceType === 'URL' ? 'WEBSITE' : 'OTHER';

    try {
      await client.triggerPhishing({
        user_id: userId,
        session_id: sessionId,
        material: {
          content_type: sourceType,
          content: contentToSend,
          source,
        },
      });

      const wsClient = new SessionWebSocketClient();
      wsClient.connect(
        config.baseUrl,
        sessionId,
        config.apiKey,
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
        (err) => {
          const errMsg = typeof err === 'string' ? err : 'WebSocket connection error';
          setStatusLog((prev) => [...prev, `▸ Error: ${errMsg}`]);
          setLoading(false);
        },
        () => {}
      );
    } catch (err: any) {
      setStatusLog((prev) => [...prev, `Error: ${err.message}`]);
      setLoading(false);
    }
  };

  return (
    <div className="card test-card">
      <div className="card-header">
        <div className="card-title">
          <FileSearch className="card-icon" size={20} />
          <h3>Phishing Material Analyzer</h3>
        </div>
        <span className="card-tag">FR-T04</span>
      </div>

      <div className="source-selector">
        <button
          type="button"
          className={`source-tab ${sourceType === 'TEXT' ? 'active' : ''}`}
          onClick={() => setSourceType('TEXT')}
        >
          <MessageSquare size={16} /> SMS / Text
        </button>
        <button
          type="button"
          className={`source-tab ${sourceType === 'URL' ? 'active' : ''}`}
          onClick={() => setSourceType('URL')}
        >
          <LinkIcon size={16} /> Suspicious Link
        </button>
        <button
          type="button"
          className={`source-tab ${sourceType === 'IMAGE' ? 'active' : ''}`}
          onClick={() => setSourceType('IMAGE')}
        >
          <ImageIcon size={16} /> Screenshot Image (OCR)
        </button>
      </div>

      <form onSubmit={handleAnalyze} className="card-form">
        {sourceType === 'TEXT' && (
          <div className="form-group">
            <label>Raw SMS / WhatsApp Text Message</label>
            <textarea
              rows={3}
              value={textContent}
              onChange={(e) => setTextContent(e.target.value)}
              placeholder="Paste suspicious text message..."
              required
            />
          </div>
        )}

        {sourceType === 'URL' && (
          <div className="form-group">
            <label>Suspicious URL Link</label>
            <input
              type="text"
              value={urlContent}
              onChange={(e) => setUrlContent(e.target.value)}
              placeholder="http://scam-domain.xyz"
              required
            />
          </div>
        )}

        {sourceType === 'IMAGE' && (
          <div className="form-group image-upload-group">
            <label><Upload size={16} /> Upload Screenshot Image (Groq Vision OCR)</label>
            <input type="file" accept="image/*" onChange={handleImageUpload} />
            {imagePreview && (
              <div className="image-preview">
                <img src={imagePreview} alt="Screenshot preview" style={{ maxHeight: 150 }} />
              </div>
            )}
          </div>
        )}

        <button type="submit" className="btn-primary" disabled={loading}>
          {loading ? 'Stage 1 OCR → Stage 2 Vector RAG...' : 'Analyze Phishing Material'}
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
            <h4>Phishing Score: {result.risk_score}/100 ({result.risk_tier})</h4>
            <button className="btn-small" onClick={() => onOpenXaiReport(result)}>
              <FileText size={14} /> View XAI Report
            </button>
          </div>
          <p>{result.verdict_summary}</p>
          {result.worker_findings?.length > 0 && (
            <div className="finding-panel">
              <h5>Indicators found</h5>
              <div className="findings-grid">
                {result.worker_findings.map((finding) => (
                  <div key={finding.worker} className={`finding-card ${finding.score >= 70 ? 'high-risk' : ''}`}>
                    <div className="finding-header">
                      <span>{finding.worker}</span>
                      <span>{finding.score}/100</span>
                    </div>
                    <ul className="evidence-list">
                      {finding.evidence.map((item, index) => (
                        <li key={`${finding.worker}-${index}`}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
