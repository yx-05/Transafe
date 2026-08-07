import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApi } from '../context/ApiContext';
import { UserHeader } from '../components/UserHeader';
import { XaiReportModal } from '../components/XaiReportModal';
import { SessionWebSocketClient } from '../services/websocket';
import type { XaiReport } from '../types/api';

type SourceType = 'TEXT' | 'URL' | 'IMAGE';

export const ScanPage: React.FC = () => {
  const { config, client, userId } = useApi();
  const navigate = useNavigate();

  const [sourceType, setSourceType] = useState<SourceType>('TEXT');
  const [textContent, setTextContent] = useState(
    'URGENT: Your Maybank account has been locked. Verify immediately at http://maybank-verify-sec.com to avoid suspension.'
  );
  const [urlContent, setUrlContent] = useState('http://maybank-verify-sec.com');
  const [imageBase64, setImageBase64] = useState<string>('');
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const [loading, setLoading] = useState(false);
  const [statusLog, setStatusLog] = useState<string[]>([]);
  const [result, setResult] = useState<XaiReport | null>(null);
  const [activeXaiReport, setActiveXaiReport] = useState<XaiReport | null>(null);

  const wsRef = useRef<SessionWebSocketClient | null>(null);

  useEffect(() => {
    return () => wsRef.current?.close();
  }, []);

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Backend rejects images whose decoded bytes exceed 10 MB.
    if (file.size > 10 * 1024 * 1024) {
      const sizeMb = (file.size / 1024 / 1024).toFixed(1);
      setStatusLog([`Image rejected: ${sizeMb} MB exceeds the 10 MB upload limit.`]);
      setImageBase64('');
      setImagePreview(null);
      setSelectedFile(null);
      e.target.value = '';
      return;
    }

    setSelectedFile(file);
    const reader = new FileReader();
    reader.onloadend = () => {
      const b64 = reader.result as string;
      setImageBase64(b64);
      setImagePreview(b64);
    };
    reader.readAsDataURL(file);
  };

  const handleAnalyze = async (e?: React.FormEvent) => {
    e?.preventDefault();
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
      wsRef.current = wsClient;
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

  const resetScan = () => {
    setSelectedFile(null);
    setImageBase64('');
    setImagePreview(null);
    setStatusLog([]);
    setResult(null);
  };

  const scoreColor =
    (result?.risk_score || 0) > 70 ? 'var(--risk-high)' : (result?.risk_score || 0) > 30 ? 'var(--risk-med)' : 'var(--risk-low)';

  return (
    <div style={{ minHeight: '100vh', backgroundColor: 'var(--background)', position: 'relative', paddingBottom: '100px' }}>
      {/* Header Banner */}
      <div className="blue-header-bg blue-header-bg--short"></div>

      <div className="header-padding-wrapper">
        <UserHeader title="Phishing Scanner" showBack={true} />
      </div>

      <div className="main-content-wrapper">
        <div style={{ maxWidth: '600px', margin: '0 auto', position: 'relative', zIndex: 10 }}>
          <div className="neo-card" style={{ backgroundColor: '#ffffff' }}>
            {/* Card Header */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', borderBottom: '1px solid var(--surface-container)', paddingBottom: '16px', marginBottom: '24px' }}>
              <span className="material-symbols-outlined" style={{ color: 'var(--primary)', fontSize: '32px' }}>image_search</span>
              <div>
                <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--on-surface)', margin: 0 }}>Phishing Material Analyzer</h2>
                <p style={{ fontSize: '12px', color: 'var(--secondary)', margin: '4px 0 0' }}>
                  Analyze suspicious SMS, links, or screenshots with the multi-agent XAI engine.
                </p>
              </div>
            </div>

            {!loading && !result && (
              <div>
                {/* Source Tabs */}
                <div style={{ display: 'flex', gap: '8px', marginBottom: '24px', flexWrap: 'wrap' }}>
                  {([
                    { key: 'TEXT', label: 'SMS / Text', icon: 'sms' },
                    { key: 'URL', label: 'Suspicious Link', icon: 'link' },
                    { key: 'IMAGE', label: 'Screenshot Image', icon: 'image' },
                  ] as const).map((tab) => (
                    <button
                      key={tab.key}
                      type="button"
                      onClick={() => setSourceType(tab.key)}
                      style={{
                        flex: 1,
                        minWidth: '120px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '6px',
                        padding: '12px 8px',
                        borderRadius: '14px',
                        border: sourceType === tab.key ? '2px solid var(--primary)' : '1px solid var(--outline-variant)',
                        backgroundColor: sourceType === tab.key ? 'rgba(0, 84, 214, 0.06)' : 'var(--surface-container-low)',
                        color: sourceType === tab.key ? 'var(--primary)' : 'var(--on-surface-variant)',
                        fontWeight: 700,
                        fontSize: '12px',
                        cursor: 'pointer',
                        transition: 'all 0.15s',
                      }}
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>{tab.icon}</span>
                      {tab.label}
                    </button>
                  ))}
                </div>

                {/* TEXT Source */}
                {sourceType === 'TEXT' && (
                  <div style={{ marginBottom: '24px' }}>
                    <label style={{ fontSize: '12px', fontWeight: 700, color: 'var(--on-surface)', display: 'block', marginBottom: '8px' }}>
                      Raw SMS / WhatsApp Text Message
                    </label>
                    <textarea
                      rows={4}
                      value={textContent}
                      onChange={(e) => setTextContent(e.target.value)}
                      placeholder="Paste suspicious text message..."
                      style={{
                        width: '100%',
                        padding: '14px',
                        borderRadius: '12px',
                        border: '1px solid var(--outline-variant)',
                        backgroundColor: 'var(--surface-container-low)',
                        fontSize: '13px',
                        fontFamily: 'inherit',
                        resize: 'vertical',
                      }}
                      required
                    />
                  </div>
                )}

                {/* URL Source */}
                {sourceType === 'URL' && (
                  <div style={{ marginBottom: '24px' }}>
                    <label style={{ fontSize: '12px', fontWeight: 700, color: 'var(--on-surface)', display: 'block', marginBottom: '8px' }}>
                      Suspicious URL Link
                    </label>
                    <input
                      type="text"
                      value={urlContent}
                      onChange={(e) => setUrlContent(e.target.value)}
                      placeholder="http://scam-domain.xyz"
                      style={{
                        width: '100%',
                        padding: '14px',
                        borderRadius: '12px',
                        border: '1px solid var(--outline-variant)',
                        backgroundColor: 'var(--surface-container-low)',
                        fontSize: '13px',
                        fontFamily: 'monospace',
                      }}
                      required
                    />
                  </div>
                )}

                {/* IMAGE Source */}
                {sourceType === 'IMAGE' && (
                  <div style={{ marginBottom: '24px' }}>
                    <label style={{ fontSize: '12px', fontWeight: 700, color: 'var(--on-surface)', display: 'block', marginBottom: '8px' }}>
                      Upload Screenshot Image (Groq Vision OCR)
                    </label>
                    {/* Drop Zone */}
                    <div
                      style={{
                        border: '2px dashed var(--outline-variant)',
                        borderRadius: '16px',
                        padding: '32px',
                        textAlign: 'center',
                        cursor: 'pointer',
                        backgroundColor: 'var(--surface-container-low)',
                        transition: 'border-color 0.15s, background-color 0.15s',
                      }}
                      onClick={() => document.getElementById('file-input')?.click()}
                      onMouseEnter={e => {
                        e.currentTarget.style.borderColor = 'var(--primary)';
                        e.currentTarget.style.backgroundColor = 'rgba(0, 102, 255, 0.03)';
                      }}
                      onMouseLeave={e => {
                        e.currentTarget.style.borderColor = 'var(--outline-variant)';
                        e.currentTarget.style.backgroundColor = 'var(--surface-container-low)';
                      }}
                    >
                      {imagePreview ? (
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                          <img
                            src={imagePreview}
                            alt="Preview"
                            style={{ maxHeight: '240px', borderRadius: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)', border: '1px solid var(--surface-container)', marginBottom: '16px' }}
                          />
                          <p style={{ fontSize: '12px', fontWeight: 600, color: 'var(--secondary)' }}>{selectedFile?.name}</p>
                        </div>
                      ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                          <div style={{ width: '64px', height: '64px', borderRadius: '50%', backgroundColor: 'var(--primary-fixed)', color: 'var(--primary)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '16px' }}>
                            <span className="material-symbols-outlined" style={{ fontSize: '32px' }}>cloud_upload</span>
                          </div>
                          <p style={{ fontSize: '14px', fontWeight: 700, color: 'var(--on-surface)', margin: 0 }}>
                            Upload suspicious chat or message screenshot
                          </p>
                          <p style={{ fontSize: '12px', color: 'var(--secondary)', marginTop: '4px' }}>PNG, JPG, WEBP up to 10MB</p>
                        </div>
                      )}

                      <input
                        id="file-input"
                        type="file"
                        accept="image/*"
                        onChange={handleImageUpload}
                        style={{ display: 'none' }}
                      />
                    </div>
                  </div>
                )}

                {/* Status Log */}
                {statusLog.length > 0 && (
                  <div style={{
                    padding: '14px',
                    borderRadius: '12px',
                    backgroundColor: '#0b0f19',
                    color: '#9ca3af',
                    fontFamily: 'monospace',
                    fontSize: '11px',
                    marginBottom: '24px',
                    maxHeight: '160px',
                    overflowY: 'auto',
                  }}>
                    {statusLog.map((log, i) => (
                      <div key={i} style={{ color: log.startsWith('▸ Error') || log.startsWith('Error') ? '#f87171' : '#9ca3af' }}>
                        ▸ {log}
                      </div>
                    ))}
                  </div>
                )}

                {/* Action Buttons */}
                <div style={{ display: 'flex', gap: '16px' }}>
                  <button
                    onClick={() => {
                      if (sourceType === 'IMAGE') document.getElementById('file-input')?.click();
                      else resetScan();
                    }}
                    className="btn-secondary"
                    style={{ flex: 1, padding: '14px', justifyContent: 'center' }}
                  >
                    <span className="material-symbols-outlined">file_open</span>
                    {sourceType === 'IMAGE' ? (selectedFile ? 'Change File' : 'Choose File') : 'Clear'}
                  </button>

                  <button
                    onClick={handleAnalyze}
                    disabled={loading || (sourceType === 'IMAGE' && !imageBase64)}
                    className="btn-primary"
                    style={{
                      flex: 1,
                      padding: '14px',
                      justifyContent: 'center',
                      opacity: loading || (sourceType === 'IMAGE' && !imageBase64) ? 0.5 : 1,
                      cursor: loading || (sourceType === 'IMAGE' && !imageBase64) ? 'not-allowed' : 'pointer'
                    }}
                  >
                    <span className="material-symbols-outlined">troubleshoot</span>
                    {loading ? 'Analyzing...' : 'Analyze Phishing Material'}
                  </button>
                </div>
              </div>
            )}

            {/* Scanning Loader */}
            {loading && (
              <div style={{ textAlign: 'center', padding: '48px 16px' }}>
                <div style={{ width: '64px', height: '64px', border: '4px solid var(--primary-fixed)', borderTopColor: 'var(--primary)', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto 24px' }}></div>
                <h3 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--on-surface)', marginBottom: '8px' }}>Analyzing Phishing Material...</h3>
                <p style={{ fontSize: '12px', color: 'var(--secondary)' }}>
                  Stage 1 OCR → Stage 2 Vector RAG against national scam templates...
                </p>

                {/* Status Log Terminal */}
                {statusLog.length > 0 && (
                  <div style={{
                    textAlign: 'left',
                    padding: '14px',
                    borderRadius: '12px',
                    backgroundColor: '#0b0f19',
                    color: '#9ca3af',
                    fontFamily: 'monospace',
                    fontSize: '11px',
                    marginTop: '20px',
                    maxHeight: '200px',
                    overflowY: 'auto',
                  }}>
                    {statusLog.map((log, i) => (
                      <div key={i} style={{ color: log.startsWith('▸ Error') || log.startsWith('Error') ? '#f87171' : '#9ca3af' }}>
                        ▸ {log}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Results Output */}
            {result && !loading && (
              <div>
                {/* Risk Banner */}
                <div style={{
                  padding: '16px',
                  borderRadius: '16px',
                  backgroundColor: scoreColor === 'var(--risk-high)' ? 'var(--error-container)' : 'rgba(245, 158, 11, 0.08)',
                  border: `2px solid ${scoreColor === 'var(--risk-high)' ? 'var(--error)' : '#f59e0b'}`,
                  color: scoreColor === 'var(--risk-high)' ? 'var(--on-error-container)' : '#92400e',
                  marginBottom: '24px',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '12px'
                }}>
                  <span className="material-symbols-outlined" style={{ color: scoreColor === 'var(--risk-high)' ? 'var(--error)' : '#f59e0b', fontSize: '28px', flexShrink: 0 }}>gpp_bad</span>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                      <h4 style={{ fontSize: '16px', fontWeight: 800, margin: 0 }}>
                        {result.risk_tier} RISK PHISHING ({result.risk_score}/100)
                      </h4>
                    </div>
                    <p style={{ fontSize: '12px', marginTop: '4px', fontWeight: 500 }}>{result.verdict_summary}</p>
                  </div>
                </div>

                {/* Result Buttons */}
                <div style={{ display: 'flex', gap: '16px' }}>
                  <button
                    onClick={resetScan}
                    className="btn-secondary"
                    style={{ flex: 1, padding: '14px', justifyContent: 'center' }}
                  >
                    Scan Another
                  </button>
                  <button
                    onClick={() => setActiveXaiReport(result)}
                    className="btn-primary"
                    style={{ flex: 1, padding: '14px', justifyContent: 'center' }}
                  >
                    <span className="material-symbols-outlined">description</span>
                    View Full XAI Report
                  </button>
                  <button
                    onClick={() => navigate('/admin')}
                    className="btn-secondary"
                    style={{ flex: 1, padding: '14px', justifyContent: 'center' }}
                  >
                    View in Admin Ops
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* XAI Report Modal */}
      <XaiReportModal report={activeXaiReport} onClose={() => setActiveXaiReport(null)} />
    </div>
  );
};
