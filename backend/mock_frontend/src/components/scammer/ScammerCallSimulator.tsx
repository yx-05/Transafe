import React, { useState } from 'react';
import type { BackendConfig } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { Skull, PhoneOutgoing, ShieldAlert } from 'lucide-react';

interface ScammerCallSimulatorProps {
  config: BackendConfig;
  victimUserId: string;
}

export const ScammerCallSimulator: React.FC<ScammerCallSimulatorProps> = ({
  config,
  victimUserId,
}) => {
  const [callerNumber, setCallerNumber] = useState('+60161234567'); // Default blacklisted Macau scammer number
  const [callerName, setCallerName] = useState('Inspecter Tan (PDRM Fake)');
  const [scamType, setScamType] = useState('MACAU_SCAM');

  const [loading, setLoading] = useState(false);
  const [sessionCreated, setSessionCreated] = useState<string | null>(null);

  const handleSimulateScamCall = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setSessionCreated(null);

    const client = new TranSafeApiClient(config);
    const sessionId = `sess-scam-${Date.now()}`;

    try {
      const res = await client.triggerCall({
        user_id: victimUserId,
        session_id: sessionId,
        call: {
          caller_number: callerNumber,
          caller_name: callerName,
          call_mode: 'LISTEN',
          call_channel: 'WEBRTC',
        },
      });

      setSessionCreated(res.call_session_id);
    } catch (err: any) {
      alert(`Scammer call simulation failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card test-card scammer-card">
      <div className="card-header">
        <div className="card-title">
          <Skull className="card-icon text-red" size={20} />
          <h3>Scammer Incoming Call Simulator</h3>
        </div>
        <span className="card-tag red">SCAMMER ROLE</span>
      </div>

      <form onSubmit={handleSimulateScamCall} className="card-form">
        <div className="form-row">
          <div className="form-group">
            <label>Scammer Phone Number (Caller ID)</label>
            <input
              type="text"
              value={callerNumber}
              onChange={(e) => setCallerNumber(e.target.value)}
              required
            />
            <div className="quick-select">
              <button
                type="button"
                className="btn-tiny"
                onClick={() => {
                  setCallerNumber('+60161234567');
                  setCallerName('Inspector Tan (PDRM Fake)');
                }}
              >
                +60161234567 (Known Blacklisted Macau Scammer)
              </button>
              <button
                type="button"
                className="btn-tiny"
                onClick={() => {
                  setCallerNumber('+60197654321');
                  setCallerName('LHDN Tax Officer (Fake)');
                }}
              >
                +60197654321 (Known Blacklisted Tax Scammer)
              </button>
            </div>
          </div>

          <div className="form-group">
            <label>Impersonated Identity Name</label>
            <input
              type="text"
              value={callerName}
              onChange={(e) => setCallerName(e.target.value)}
            />
          </div>
        </div>

        <div className="form-group">
          <label>Scam Category</label>
          <select value={scamType} onChange={(e) => setScamType(e.target.value)}>
            <option value="MACAU_SCAM">Macau / Police Impersonation Scam</option>
            <option value="INVESTMENT_SCAM">High Yield Investment Scam</option>
            <option value="LOVE_SCAM">Romance / Parcel Scam</option>
            <option value="ECOM_SCAM">E-Commerce Delivery Fraud</option>
          </select>
        </div>

        <button type="submit" className="btn-danger-submit" disabled={loading}>
          <PhoneOutgoing size={16} /> Fire Incoming Call to Victim App (User: {victimUserId})
        </button>
      </form>

      {sessionCreated && (
        <div className="result-box tier-high">
          <div className="result-header">
            <h4><ShieldAlert size={18} /> Simulated Call Session Dispatched!</h4>
          </div>
          <p>
            Call Session ID: <code>{sessionCreated}</code>. The victim user page will receive a pre-check warning if this number is blacklisted!
          </p>
        </div>
      )}
    </div>
  );
};
