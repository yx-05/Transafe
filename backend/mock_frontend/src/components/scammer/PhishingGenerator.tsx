import React, { useState } from 'react';
import type { BackendConfig } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { Link2, Send, Copy, Check } from 'lucide-react';

interface PhishingGeneratorProps {
  config: BackendConfig;
  victimUserId: string;
}

export const PhishingGenerator: React.FC<PhishingGeneratorProps> = ({ config, victimUserId }) => {
  const [phishingUrl, setPhishingUrl] = useState('http://maybank-verify-sec.com/login');
  const [smsText, setSmsText] = useState(
    'Maybank Alert: RM9,800 transferred from account. If not initiated by you, immediately login to cancel at http://maybank-verify-sec.com'
  );
  const [muleAccount, setMuleAccount] = useState('7653123456789012');

  const [copied, setCopied] = useState(false);
  const [dispatched, setDispatched] = useState(false);

  const handleCopyText = () => {
    navigator.clipboard.writeText(smsText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDispatchPhishing = async () => {
    setDispatched(true);
    const client = new TranSafeApiClient(config);
    const sessionId = `sess-scam-phish-${Date.now()}`;
    try {
      await client.triggerPhishing({
        user_id: victimUserId,
        session_id: sessionId,
        phishing_material: {
          source_type: 'TEXT',
          content: smsText,
        },
      });
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="card test-card scammer-card">
      <div className="card-header">
        <div className="card-title">
          <Link2 className="card-icon text-red" size={20} />
          <h3>Phishing Link & Message Generator</h3>
        </div>
        <span className="card-tag red">SCAMMER ROLE</span>
      </div>

      <div className="card-form">
        <div className="form-group">
          <label>Target Phishing Domain / Link</label>
          <input
            type="text"
            value={phishingUrl}
            onChange={(e) => setPhishingUrl(e.target.value)}
          />
        </div>

        <div className="form-group">
          <label>Scammer Mule Account Number</label>
          <input
            type="text"
            value={muleAccount}
            onChange={(e) => setMuleAccount(e.target.value)}
          />
        </div>

        <div className="form-group">
          <label>Generated Phishing SMS Message Payload</label>
          <textarea
            rows={3}
            value={smsText}
            onChange={(e) => setSmsText(e.target.value)}
          />
        </div>

        <div className="button-group-row">
          <button type="button" className="btn-secondary" onClick={handleCopyText}>
            {copied ? <Check size={16} /> : <Copy size={16} />}
            {copied ? 'Copied to Clipboard' : 'Copy Message Text'}
          </button>

          <button type="button" className="btn-danger-submit" onClick={handleDispatchPhishing}>
            <Send size={16} /> Send directly to Phishing Analyzer
          </button>
        </div>

        {dispatched && (
          <p className="success-msg">✓ Phishing payload dispatched to backend pipeline!</p>
        )}
      </div>
    </div>
  );
};
