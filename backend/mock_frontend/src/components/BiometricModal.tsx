import React, { useState } from 'react';
import { Fingerprint, CheckCircle2, XCircle } from 'lucide-react';

interface BiometricModalProps {
  transactionId: string;
  onSubmitResult: (result: 'PASSED' | 'FAILED' | 'DECLINED') => Promise<void>;
  onClose: () => void;
}

export const BiometricModal: React.FC<BiometricModalProps> = ({
  transactionId,
  onSubmitResult,
  onClose,
}) => {
  const [submitting, setSubmitting] = useState(false);

  const handleChoice = async (result: 'PASSED' | 'FAILED' | 'DECLINED') => {
    setSubmitting(true);
    try {
      await onSubmitResult(result);
      onClose();
    } catch (e) {
      console.error('Biometric submission failed', e);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content biometric-modal">
        <div className="biometric-icon-wrapper">
          <Fingerprint className="biometric-icon pulse" size={48} />
        </div>
        <h2>Biometric Challenge Required</h2>
        <p className="biometric-desc">
          TranSafe detected <strong>MEDIUM RISK</strong> for your pending transaction (<code>{transactionId}</code>).
          Please complete biometric authentication to authorize execution.
        </p>

        <div className="biometric-actions">
          <button
            className="btn-biometric pass"
            onClick={() => handleChoice('PASSED')}
            disabled={submitting}
          >
            <CheckCircle2 size={20} />
            <span>Simulate TouchID / FaceID PASS</span>
          </button>

          <button
            className="btn-biometric fail"
            onClick={() => handleChoice('FAILED')}
            disabled={submitting}
          >
            <XCircle size={20} />
            <span>Simulate Biometric FAIL / Cancel</span>
          </button>
        </div>
      </div>
    </div>
  );
};
