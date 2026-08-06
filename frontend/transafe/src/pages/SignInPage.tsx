import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import robotLineArt from '../assets/robot.png';

export const SignInPage: React.FC = () => {
  const navigate = useNavigate();
  const { signIn, error: authError, isLoading: authLoading } = useAuth();

  // Default Account Number from /backend/mock_frontend: 6373-5093-3430-8430
  const [bank, setBank] = useState<string>('Maybank');
  const [accountNumber, setAccountNumber] = useState<string>('6373-5093-3430-8430');
  const [pin, setPin] = useState<string>('123456');
  const [rememberMe, setRememberMe] = useState<boolean>(true);
  const [isAuthenticating, setIsAuthenticating] = useState<boolean>(false);
  const [authStep, setAuthStep] = useState<string>('');
  const [loginError, setLoginError] = useState<string | null>(null);

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsAuthenticating(true);
    setLoginError(null);
    setAuthStep('Validating Account Number & Device Fingerprint...');

    await new Promise((res) => setTimeout(res, 500));
    setAuthStep('Connecting to TranSafe Authentication Server...');

    // Call the real backend auth endpoint
    const success = await signIn(accountNumber, pin);

    if (success) {
      setAuthStep('Session Authenticated! Redirecting to Dashboard...');
      await new Promise((res) => setTimeout(res, 400));
      setIsAuthenticating(false);
      navigate('/');
    } else {
      setIsAuthenticating(false);
      setLoginError(authError || 'Authentication failed. Please check your credentials.');
    }
  };

  const applyDemoAccount = (accNum: string, accBank: string) => {
    setAccountNumber(accNum);
    setBank(accBank);
    setLoginError(null);
  };

  return (
    <div className="min-h-screen relative bg-[#f8f9fa] flex flex-col justify-center items-center px-4 sm:px-6 py-12 font-sans overflow-hidden">
      {/* Blue Header Background Curve */}
      <div className="blue-header-bg">
        <img
          src={robotLineArt}
          alt=""
          className="header-line-art"
          style={{
            position: 'absolute',
            right: 0,
            bottom: 0,
            height: '100%',
            width: 'auto',
            opacity: 0.10,
            pointerEvents: 'none',
            userSelect: 'none',
          }}
        />
      </div>

      {/* Brand Title Banner */}
      <div className="relative z-10 text-center text-white mb-8">
        <h1 className="text-4xl md:text-5xl font-extrabold tracking-tight mb-2">
          TranSafe
        </h1>
        <p className="text-white/80 text-sm md:text-base font-medium max-w-sm mx-auto">
          AI Multi-Agent Fraud Prevention Platform
        </p>
      </div>

      {/* Main Sign In Card Container */}
      <div className="bg-white rounded-[32px] p-6 md:p-10 shadow-[0_20px_50px_rgba(0,0,0,0.12)] border border-gray-100 max-w-md w-full relative z-10">
        <div className="flex items-center justify-between border-b pb-4 mb-6">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">Sign In to Online Banking</h2>
            <p className="text-xs text-gray-500 mt-1">Enter your bank account credentials to access your account.</p>
          </div>
          <div className="w-10 h-10 rounded-2xl bg-blue-100 text-[#0050cb] flex items-center justify-center flex-shrink-0">
            <span className="material-symbols-outlined text-2xl">lock</span>
          </div>
        </div>

        {/* Error Banner */}
        {loginError && (
          <div className="mb-5 p-3.5 rounded-2xl bg-red-50 border border-red-200 flex items-center gap-2.5 text-xs text-red-900">
            <span className="material-symbols-outlined text-red-600 text-base flex-shrink-0">error</span>
            <span className="font-semibold">{loginError}</span>
          </div>
        )}

        {/* Demo Account Presets */}
        <div className="mb-6 p-4 rounded-2xl bg-gray-50 border border-gray-200">
          <div className="flex items-center gap-2 text-xs font-bold text-gray-700 mb-2 uppercase tracking-wider">
            <span className="material-symbols-outlined text-[#0050cb] text-base">badge</span>
            <span>Quick Test Account Presets:</span>
          </div>
          <div className="flex flex-col gap-2">
            <button
              type="button"
              onClick={() => applyDemoAccount('6373-5093-3430-8430', 'Maybank')}
              className="p-2.5 rounded-xl bg-white border border-gray-200 text-left hover:border-blue-400 transition-colors flex justify-between items-center"
            >
              <div>
                <p className="text-xs font-bold text-gray-900">John Doe (Default)</p>
                <p className="text-[11px] font-mono text-gray-500">6373-5093-3430-8430 • Maybank</p>
              </div>
              <span className="text-[10px] font-bold bg-blue-50 text-[#0050cb] px-2 py-0.5 rounded-full">
                DEFAULT
              </span>
            </button>

            <button
              type="button"
              onClick={() => applyDemoAccount('1122-3344-5566-7788', 'CIMB Bank')}
              className="p-2.5 rounded-xl bg-white border border-gray-200 text-left hover:border-blue-400 transition-colors flex justify-between items-center"
            >
              <div>
                <p className="text-xs font-bold text-gray-900">Sarah Tan (Premier Account)</p>
                <p className="text-[11px] font-mono text-gray-500">1122-3344-5566-7788 • CIMB Bank</p>
              </div>
              <span className="text-[10px] font-bold bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
                PREMIER
              </span>
            </button>
          </div>
        </div>

        {/* Sign In Form */}
        <form onSubmit={handleSignIn} className="flex flex-col gap-5">
          {/* Bank Selector */}
          <div className="form-group mb-0">
            <label className="form-label text-xs uppercase tracking-wider text-gray-500 font-bold mb-2">
              Select Your Bank
            </label>
            <select
              value={bank}
              onChange={(e) => setBank(e.target.value)}
              className="form-select text-xs font-semibold text-gray-900"
            >
              <option value="Maybank">Maybank (Malayan Banking Berhad)</option>
              <option value="CIMB Bank">CIMB Bank Berhad</option>
              <option value="Public Bank">Public Bank Berhad</option>
              <option value="RHB Bank">RHB Bank Berhad</option>
              <option value="Hong Leong Bank">Hong Leong Bank Berhad</option>
              <option value="Bank Islam">Bank Islam Malaysia Berhad</option>
            </select>
          </div>

          {/* Account Number Input */}
          <div className="form-group mb-0">
            <label className="form-label text-xs uppercase tracking-wider text-gray-500 font-bold mb-2">
              Bank Account Number
            </label>
            <div className="relative flex items-center">
              <span className="absolute left-4 text-gray-400 pointer-events-none z-10 flex items-center justify-center">
                <span className="material-symbols-outlined text-lg">credit_card</span>
              </span>
              <input
                type="text"
                value={accountNumber}
                onChange={(e) => setAccountNumber(e.target.value)}
                placeholder="e.g. 6373-5093-3430-8430"
                className="form-input font-mono text-sm font-bold text-gray-900"
                style={{ paddingLeft: '48px' }}
                required
              />
            </div>
          </div>

          {/* PIN / Password Input */}
          <div className="form-group mb-0">
            <label className="form-label text-xs uppercase tracking-wider text-gray-500 font-bold mb-2">
              6-Digit Online Banking PIN
            </label>
            <div className="relative flex items-center">
              <span className="absolute left-4 text-gray-400 pointer-events-none z-10 flex items-center justify-center">
                <span className="material-symbols-outlined text-lg">key</span>
              </span>
              <input
                type="password"
                maxLength={6}
                value={pin}
                onChange={(e) => setPin(e.target.value)}
                placeholder="••••••"
                className="form-input font-mono text-base font-bold text-gray-900 tracking-widest"
                style={{ paddingLeft: '48px' }}
                required
              />
            </div>
          </div>

          {/* Remember Account Checkbox */}
          <div className="flex items-center justify-between text-xs text-gray-600">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                className="rounded text-[#0066ff] focus:ring-[#0066ff]"
              />
              <span>Remember Account Number</span>
            </label>
            <a href="#forgot" onClick={(e) => e.preventDefault()} className="text-[#0050cb] font-bold hover:underline">
              Forgot PIN?
            </a>
          </div>

          {/* Security Status Banner */}
          <div className="p-3 rounded-2xl bg-emerald-50 border border-emerald-200 flex items-center gap-2.5 text-xs text-emerald-900">
            <span className="w-2 h-2 bg-emerald-500 rounded-full animate-ping flex-shrink-0"></span>
            <span className="font-semibold text-[11px]">BNM Multi-Agent AI Fraud Shield Active</span>
          </div>

          {/* Sign In Button */}
          <button
            type="submit"
            disabled={isAuthenticating || authLoading}
            className="btn-primary w-full py-4 justify-center bg-[#0066ff] hover:bg-[#0050cb] text-white font-bold shadow-lg shadow-blue-500/20 text-sm mt-2"
          >
            {isAuthenticating ? (
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                <span>Authenticating...</span>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-xl">login</span>
                <span>Sign In Securely</span>
              </div>
            )}
          </button>
        </form>

        {/* Authentication Progress Modal Overlay */}
        {isAuthenticating && (
          <div className="absolute inset-0 bg-white/95 backdrop-blur-sm rounded-[32px] z-30 flex flex-col items-center justify-center p-6 text-center">
            <div className="w-16 h-16 border-4 border-blue-200 border-t-[#0066ff] rounded-full animate-spin mb-4"></div>
            <h3 className="text-lg font-bold text-gray-900 mb-1">Authenticating Session</h3>
            <p className="text-xs text-[#0050cb] font-mono animate-pulse">{authStep}</p>
          </div>
        )}
      </div>

      {/* Footer copyright */}
      <p className="text-xs text-gray-500 mt-8 relative z-10">
        © 2026 TranSafe Platform.
      </p>
    </div>
  );
};
