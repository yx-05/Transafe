import React, { useState, useRef, useEffect } from 'react';
import type { BackendConfig, WsCallEventMessage } from '../../types/api';
import { TranSafeApiClient } from '../../services/api';
import { CallAudioStreamer } from '../../services/audioRecorder';
import { CallEventsWebSocketClient } from '../../services/websocket';
import { Skull, PhoneOutgoing, Mic, MicOff, Radio, Volume2 } from 'lucide-react';

interface ScammerCallSimulatorProps {
  config: BackendConfig;
  victimUserId: string;
}

export const ScammerCallSimulator: React.FC<ScammerCallSimulatorProps> = ({
  config,
  victimUserId,
}) => {
  const [callerNumber, setCallerNumber] = useState('+60161234567'); // Default blacklisted Macau scammer number
  const [callerName, setCallerName] = useState('Inspector Tan (PDRM Fake)');
  const [scamType, setScamType] = useState('MACAU_SCAM');

  const [loading, setLoading] = useState(false);
  const [activeCallSessionId, setActiveCallSessionId] = useState<string | null>(null);
  const [audioStatus, setAudioStatus] = useState<string>('Idle');
  const [isLive, setIsLive] = useState<boolean>(false);

  const audioStreamerRef = useRef<CallAudioStreamer>(new CallAudioStreamer());
  const eventsWsClientRef = useRef<CallEventsWebSocketClient>(new CallEventsWebSocketClient());

  useEffect(() => {
    return () => {
      audioStreamerRef.current.stopStreaming();
      eventsWsClientRef.current.close();
    };
  }, []);

  const handleSimulateScamCall = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setActiveCallSessionId(null);

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
          received_at: new Date().toISOString(),
          stt_engine: 'nova-3',
        },
      });

      setActiveCallSessionId(res.call_session_id);
      setIsLive(true);
      setAudioStatus('Connecting Microphone & WebSockets...');

      // Connect Events WebSocket to listen for call_ended or decline from Customer
      eventsWsClientRef.current.connect(
        config.baseUrl,
        res.call_session_id,
        config.apiKey,
        (msg: WsCallEventMessage) => {
          if (msg.type === 'call_ended') {
            audioStreamerRef.current.stopStreaming();
            setIsLive(false);
            setActiveCallSessionId(null);
            setAudioStatus('Call Ended by Customer');
          }
        },
        (err) => console.error('Scammer Events WS error:', err),
        () => console.log('Scammer Events WS closed')
      );

      // Connect Scammer Microphone & Audio Relay
      audioStreamerRef.current.startStreaming(
        config.baseUrl,
        res.call_session_id,
        config.apiKey,
        'SCAMMER',
        (status) => setAudioStatus(status),
        (err) => setAudioStatus(`Mic Error: ${err}`)
      );
    } catch (err: any) {
      alert(`Scammer call simulation failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleEndScammerCall = () => {
    audioStreamerRef.current.stopStreaming();
    eventsWsClientRef.current.close();
    setIsLive(false);
    setActiveCallSessionId(null);
    setAudioStatus('Call Ended');
  };

  return (
    <div className="card test-card scammer-card">
      <div className="card-header">
        <div className="card-title">
          <Skull className="card-icon text-red" size={20} />
          <h3>Scammer Live Call Terminal & Simulator</h3>
        </div>
        <span className="card-tag red">REAL SCAMMER ROLE</span>
      </div>

      {!isLive ? (
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
            <PhoneOutgoing size={16} /> 📞 Fire Incoming Call & Connect Scammer Mic
          </button>
        </form>
      ) : (
        <div className="active-call-panel red-border">
          <div className="call-status-bar">
            <div className="status-live">
              <Radio className="pulse text-red" size={18} />
              <span>SCAMMER LIVE SESSION: <code>{activeCallSessionId}</code></span>
            </div>
            <button className="btn-danger" onClick={handleEndScammerCall}>
              <MicOff size={16} /> Hang Up Call
            </button>
          </div>

          <div className="audio-stream-status text-red">
            <Mic size={16} /> <strong>Scammer Microphone & Speaker Relay:</strong> {audioStatus}
          </div>

          <div className="scammer-live-banner">
            <Volume2 size={20} className="pulse" />
            <div>
              <strong>🎙️ Real Scammer Terminal Active!</strong>
              <p>Speak into your microphone. Your audio is being relayed to the Victim customer, while TranSafe AI monitors for scam phrases in real time.</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
