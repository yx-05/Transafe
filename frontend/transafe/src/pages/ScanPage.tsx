import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSimulation } from '../context/SimulationContext';
import { UserHeader } from '../components/UserHeader';

export const ScanPage: React.FC = () => {
  const { isScanningPhishing, phishingResult, submitPhishingScan } = useSimulation();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const navigate = useNavigate();

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setSelectedFile(file);
      setPreviewUrl(URL.createObjectURL(file));
    }
  };

  const handleAnalyze = async () => {
    if (!selectedFile) return;
    await submitPhishingScan(selectedFile);
  };

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
                <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--on-surface)', margin: 0 }}>Phishing Screenshot Analysis</h2>
                <p style={{ fontSize: '12px', color: 'var(--secondary)', margin: '4px 0 0' }}>
                  Upload suspicious WhatsApp, Telegram, or SMS chat messages for instant AI threat scanning.
                </p>
              </div>
            </div>

            {/* Upload Area */}
            {!phishingResult && !isScanningPhishing && (
              <div>
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
                    marginBottom: '24px'
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
                  {previewUrl ? (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                      <img
                        src={previewUrl}
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
                    onChange={handleFileChange}
                    style={{ display: 'none' }}
                  />
                </div>

                {/* Action Buttons */}
                <div style={{ display: 'flex', gap: '16px' }}>
                  <button
                    onClick={() => document.getElementById('file-input')?.click()}
                    className="btn-secondary"
                    style={{ flex: 1, padding: '14px', justifyContent: 'center' }}
                  >
                    <span className="material-symbols-outlined">file_open</span>
                    {selectedFile ? 'Change File' : 'Choose File'}
                  </button>
                  
                  <button
                    onClick={handleAnalyze}
                    disabled={!selectedFile}
                    className="btn-primary"
                    style={{
                      flex: 1,
                      padding: '14px',
                      justifyContent: 'center',
                      opacity: !selectedFile ? 0.5 : 1,
                      cursor: !selectedFile ? 'not-allowed' : 'pointer'
                    }}
                  >
                    <span className="material-symbols-outlined">troubleshoot</span>
                    Analyze
                  </button>
                </div>
              </div>
            )}

            {/* Scanning Loader */}
            {isScanningPhishing && (
              <div style={{ textAlign: 'center', padding: '48px 16px' }}>
                <div style={{ width: '64px', height: '64px', border: '4px solid var(--primary-fixed)', borderTopColor: 'var(--primary)', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto 24px' }}></div>
                <h3 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--on-surface)', marginBottom: '8px' }}>Analyzing Chat Screenshot...</h3>
                <p style={{ fontSize: '12px', color: 'var(--secondary)' }}>
                  Running Tesseract OCR & Phishing Lure classifier against 5,000+ national scam templates.
                </p>
              </div>
            )}

            {/* Results Output */}
            {phishingResult && !isScanningPhishing && (
              <div>
                {/* High Risk Banner */}
                <div style={{
                  padding: '16px',
                  borderRadius: '16px',
                  backgroundColor: 'var(--error-container)',
                  border: '2px solid var(--error)',
                  color: 'var(--on-error-container)',
                  marginBottom: '24px',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '12px'
                }}>
                  <span className="material-symbols-outlined" style={{ color: 'var(--error)', fontSize: '28px', flexShrink: 0 }}>gpp_bad</span>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                      <h4 style={{ fontSize: '16px', fontWeight: 800, margin: 0 }}>HIGH RISK PHISHING DETECTED</h4>
                      <span className="risk-pill high" style={{ fontSize: '10px', padding: '2px 8px' }}>
                        {phishingResult.confidence}% Confidence
                      </span>
                    </div>
                    <p style={{ fontSize: '12px', marginTop: '4px', fontWeight: 500 }}>{phishingResult.verdict}</p>
                  </div>
                </div>

                {/* OCR Extracted Text */}
                <div style={{
                  padding: '16px',
                  borderRadius: '12px',
                  backgroundColor: '#0b0f19',
                  color: '#10b981',
                  fontFamily: 'monospace',
                  fontSize: '12px',
                  marginBottom: '24px'
                }}>
                  <p style={{ color: '#9ca3af', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px', fontSize: '10px' }}>
                    Extracted OCR Text Payload:
                  </p>
                  <p style={{ lineHeight: '1.6', backgroundColor: 'rgba(0,0,0,0.4)', padding: '12px', borderRadius: '8px', border: '1px solid #374151' }}>
                    &ldquo;{phishingResult.extractedText}&rdquo;
                  </p>
                </div>

                {/* Result Buttons */}
                <div style={{ display: 'flex', gap: '16px' }}>
                  <button
                    onClick={() => {
                      setSelectedFile(null);
                      setPreviewUrl(null);
                    }}
                    className="btn-secondary"
                    style={{ flex: 1, padding: '14px', justifyContent: 'center' }}
                  >
                    Scan Another Image
                  </button>
                  <button
                    onClick={() => navigate('/admin')}
                    className="btn-primary"
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
    </div>
  );
};
