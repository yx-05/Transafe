import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSimulation } from '../context/SimulationContext';
import { useAuth } from '../context/AuthContext';
import { UserHeader } from '../components/UserHeader';

export const ProfilePage: React.FC = () => {
  const { accountBalance } = useSimulation();
  const { signOut } = useAuth();
  const navigate = useNavigate();

  // State management for mock settings
  const [isCopilotEnabled, setIsCopilotEnabled] = useState<boolean>(true);
  const [isBiometricsEnabled, setIsBiometricsEnabled] = useState<boolean>(true);
  const [dailyLimit, setDailyLimit] = useState<number>(50000);
  const [showLimitModal, setShowLimitModal] = useState<boolean>(false);
  const [showKillSwitchModal, setShowKillSwitchModal] = useState<boolean>(false);
  const [isAccountFrozen, setIsAccountFrozen] = useState<boolean>(false);
  const [tempLimit, setTempLimit] = useState<number>(dailyLimit);

  const handleSaveLimit = () => {
    setDailyLimit(tempLimit);
    setShowLimitModal(false);
  };

  const handleConfirmKillSwitch = () => {
    setIsAccountFrozen(true);
    setShowKillSwitchModal(false);
  };

  return (
    <div className="user-app-layout pb-28 min-h-screen relative bg-[#f8f9fa]">
      {/* Blue Header Background Curve */}
      <div className="blue-header-bg"></div>

      {/* Main Content Wrapper */}
      <div className="main-content-wrapper px-4 sm:px-6 md:px-8">
        {/* Header App Bar */}
        <UserHeader title="My Profile" showBack={true} />

        {/* Main Content Area */}
        <main className="flex flex-col gap-8 relative z-10 pt-2">
          {/* Subheader Banner */}
          <div className="text-white flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
            <div>
              <h2 className="text-2xl md:text-4xl font-bold tracking-tight">
                Account & Security Settings
              </h2>
              <p className="text-white/80 mt-1 text-sm md:text-base">
                Manage your personal details, AI fraud defense preferences, and safety limits.
              </p>
            </div>

            <div className="flex items-center gap-2 flex-shrink-0">
              <span className="w-2.5 h-2.5 bg-emerald-400 rounded-full animate-pulse"></span>
              <span className="bg-white/20 text-white backdrop-blur-md px-3.5 py-1.5 rounded-full text-xs font-mono font-bold uppercase tracking-wider border border-white/20">
                KYC VERIFIED USER
              </span>
            </div>
          </div>

          {/* Account Frozen Alert Banner if Kill Switch activated */}
          {isAccountFrozen && (
            <div className="p-5 rounded-2xl bg-red-600 text-white shadow-xl flex items-center justify-between gap-4 border border-red-700 animate-pulse">
              <div className="flex items-center gap-3">
                <span className="material-symbols-outlined text-3xl">block</span>
                <div>
                  <h4 className="font-bold text-lg">EMERGENCY KILL SWITCH ACTIVE</h4>
                  <p className="text-xs text-red-100">
                    Your account has been frozen. All outgoing transfers and online banking access are currently blocked.
                  </p>
                </div>
              </div>
              <button
                onClick={() => setIsAccountFrozen(false)}
                className="bg-white text-red-700 font-bold px-4 py-2 rounded-xl text-xs hover:bg-gray-100 transition-colors flex-shrink-0"
              >
                Unfreeze Account
              </button>
            </div>
          )}

          {/* Grid Layout: Left Column (Identity & Emergency) + Right Column (Security & AI Defense) */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
            {/* Left Column: User Identity Card & Kill Switch */}
            <div className="lg:col-span-5 flex flex-col gap-6">
              {/* User Identity Profile Card */}
              <div className="bg-white rounded-[32px] p-6 md:p-8 shadow-[0_20px_50px_rgba(0,0,0,0.08)] border border-gray-100 flex flex-col gap-6">
                <div className="flex items-center gap-4 border-b border-gray-100 pb-6">
                  {/* Avatar Circle */}
                  <div className="relative">
                    <div className="w-16 h-16 rounded-full bg-[#0066ff] text-white font-bold text-2xl flex items-center justify-center shadow-lg shadow-blue-500/20">
                      JD
                    </div>
                    <span className="absolute bottom-0 right-0 w-5 h-5 bg-emerald-500 rounded-full border-2 border-white flex items-center justify-center text-[10px] text-white">
                      ✓
                    </span>
                  </div>

                  <div>
                    <h3 className="text-xl font-bold text-gray-900">John Doe</h3>
                    <p className="text-xs text-gray-500">Maybank Premier Savings • Account 1122-3344-5566</p>
                    <span className="inline-block mt-1 bg-emerald-50 text-emerald-700 border border-emerald-200 px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider">
                      BNM e-KYC Verified
                    </span>
                  </div>
                </div>

                {/* Profile Details List */}
                <div className="flex flex-col gap-4 text-xs">
                  <div className="flex justify-between items-center py-2 border-b border-gray-100">
                    <span className="text-gray-500 font-semibold">Customer Reference ID</span>
                    <span className="font-mono font-bold text-gray-900">TRSF-8890214-MY</span>
                  </div>

                  <div className="flex justify-between items-center py-2 border-b border-gray-100">
                    <span className="text-gray-500 font-semibold">MyKad IC Number</span>
                    <span className="font-mono font-bold text-gray-900">880412-10-5432</span>
                  </div>

                  <div className="flex justify-between items-center py-2 border-b border-gray-100">
                    <span className="text-gray-500 font-semibold">Mobile Phone</span>
                    <span className="font-semibold text-gray-900">+6012-345-6789</span>
                  </div>

                  <div className="flex justify-between items-center py-2 border-b border-gray-100">
                    <span className="text-gray-500 font-semibold">Email Address</span>
                    <span className="font-semibold text-gray-900">john.doe@example.com</span>
                  </div>

                  <div className="flex justify-between items-center py-2">
                    <span className="text-gray-500 font-semibold">Primary Balance</span>
                    <span className="font-bold text-[#0050cb] text-sm">
                      RM {accountBalance.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                </div>

                <div className="flex flex-col gap-3">
                  <button
                    onClick={() => navigate('/transfer')}
                    className="btn-primary w-full py-3.5 justify-center bg-[#0066ff] hover:bg-[#0050cb] text-white text-xs font-bold shadow-md"
                  >
                    <span className="material-symbols-outlined text-lg">sync_alt</span>
                    Make a Transfer
                  </button>

                  <button
                    onClick={() => { signOut(); navigate('/login'); }}
                    className="btn-secondary w-full py-3 justify-center bg-[#dee3eb] text-[#5f656c] hover:bg-gray-300 text-xs font-bold"
                  >
                    <span className="material-symbols-outlined text-lg">logout</span>
                    Sign Out
                  </button>
                </div>
              </div>

              {/* Emergency Account Freeze (Kill Switch Card) */}
              <div className="bg-red-50 border border-red-200 rounded-[28px] p-6 flex flex-col gap-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-2xl bg-red-600 text-white flex items-center justify-center flex-shrink-0 shadow-md">
                    <span className="material-symbols-outlined text-xl">warning</span>
                  </div>
                  <div>
                    <h4 className="text-base font-bold text-red-900">Emergency Kill Switch</h4>
                    <p className="text-xs text-red-700">Under scam attack? Freeze all transactions instantly.</p>
                  </div>
                </div>

                <button
                  onClick={() => setShowKillSwitchModal(true)}
                  disabled={isAccountFrozen}
                  className={`btn-danger w-full py-3.5 justify-center bg-[#ba1a1a] hover:bg-[#93000a] text-white font-bold text-xs shadow-md ${
                    isAccountFrozen ? 'opacity-50 cursor-not-allowed' : ''
                  }`}
                >
                  <span className="material-symbols-outlined text-lg">block</span>
                  {isAccountFrozen ? 'Account Currently Frozen' : 'Freeze Account Immediately'}
                </button>
              </div>
            </div>

            {/* Right Column: AI Defense Engine & Preferences */}
            <div className="lg:col-span-7 flex flex-col gap-6">
              {/* TranSafe AI Defense Engine Settings Card */}
              <div className="bg-white rounded-[32px] p-6 md:p-8 shadow-[0_20px_50px_rgba(0,0,0,0.08)] border border-gray-100 flex flex-col gap-6">
                <div className="flex items-center justify-between border-b border-gray-100 pb-4">
                  <div>
                    <h3 className="text-xl font-bold text-gray-900">TranSafe AI Fraud Defense</h3>
                    <p className="text-xs text-gray-500">Configure real-time scam detection and voice call protection.</p>
                  </div>
                  <span className="material-symbols-outlined text-[#0050cb] text-3xl">verified_user</span>
                </div>

                {/* Toggles */}
                <div className="flex flex-col gap-5">
                  {/* Real-time Voice Copilot Toggle */}
                  <div className="p-4 rounded-2xl bg-gray-50 border border-gray-200 flex justify-between items-center gap-4">
                    <div className="flex items-start gap-3">
                      <span className="material-symbols-outlined text-[#0050cb] text-2xl mt-0.5">phone_in_talk</span>
                      <div>
                        <h4 className="text-sm font-bold text-gray-900">Real-Time Voice Call Copilot</h4>
                        <p className="text-xs text-gray-500">Monitors incoming phone calls for scam speech patterns and coercion.</p>
                      </div>
                    </div>

                    <button
                      onClick={() => setIsCopilotEnabled(!isCopilotEnabled)}
                      className={`w-12 h-6 rounded-full transition-colors relative flex-shrink-0 ${
                        isCopilotEnabled ? 'bg-[#0066ff]' : 'bg-gray-300'
                      }`}
                    >
                      <span
                        className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-transform ${
                          isCopilotEnabled ? 'right-1' : 'left-1'
                        }`}
                      ></span>
                    </button>
                  </div>

                  {/* Voice Biometrics Toggle */}
                  <div className="p-4 rounded-2xl bg-gray-50 border border-gray-200 flex justify-between items-center gap-4">
                    <div className="flex items-start gap-3">
                      <span className="material-symbols-outlined text-[#0050cb] text-2xl mt-0.5">graphic_eq</span>
                      <div>
                        <h4 className="text-sm font-bold text-gray-900">Biometric Voice Authentication</h4>
                        <p className="text-xs text-gray-500">Requires voice verification for high-risk transfer approvals.</p>
                      </div>
                    </div>

                    <button
                      onClick={() => setIsBiometricsEnabled(!isBiometricsEnabled)}
                      className={`w-12 h-6 rounded-full transition-colors relative flex-shrink-0 ${
                        isBiometricsEnabled ? 'bg-[#0066ff]' : 'bg-gray-300'
                      }`}
                    >
                      <span
                        className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-transform ${
                          isBiometricsEnabled ? 'right-1' : 'left-1'
                        }`}
                      ></span>
                    </button>
                  </div>

                  {/* Daily Transfer Limit Card */}
                  <div className="p-4 rounded-2xl bg-gray-50 border border-gray-200 flex justify-between items-center gap-4">
                    <div className="flex items-start gap-3">
                      <span className="material-symbols-outlined text-[#0050cb] text-2xl mt-0.5">account_balance</span>
                      <div>
                        <h4 className="text-sm font-bold text-gray-900">Daily Online Transfer Limit</h4>
                        <p className="text-xs text-gray-500">
                          Current max limit per day: <strong className="text-gray-900 font-mono">RM {dailyLimit.toLocaleString('en-US')}</strong>
                        </p>
                      </div>
                    </div>

                    <button
                      onClick={() => { setTempLimit(dailyLimit); setShowLimitModal(true); }}
                      className="btn-secondary py-2 px-4 text-xs font-bold bg-[#dee3eb] text-[#5f656c] hover:bg-gray-300 flex-shrink-0"
                    >
                      Change Limit
                    </button>
                  </div>
                </div>
              </div>

              {/* Trusted Emergency Contacts Card */}
              <div className="bg-white rounded-[32px] p-6 md:p-8 shadow-[0_20px_50px_rgba(0,0,0,0.08)] border border-gray-100 flex flex-col gap-5">
                <div className="flex items-center justify-between border-b border-gray-100 pb-4">
                  <h3 className="text-xl font-bold text-gray-900">Emergency & Trusted Contacts</h3>
                  <span className="material-symbols-outlined text-[#0050cb] text-2xl">contact_phone</span>
                </div>

                <div className="flex flex-col gap-3">
                  {/* Contact 1 */}
                  <div className="p-3.5 rounded-2xl bg-gray-50 border border-gray-200 flex justify-between items-center text-xs">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-blue-100 text-[#0050cb] font-bold flex items-center justify-center">
                        SD
                      </div>
                      <div>
                        <p className="font-bold text-gray-900">Sarah Doe (Spouse)</p>
                        <p className="text-gray-500 text-[11px]">+6012-987-6543 • Trusted Guardian</p>
                      </div>
                    </div>
                    <span className="bg-emerald-100 text-emerald-800 text-[10px] font-bold px-2.5 py-1 rounded-full">
                      ACTIVE GUARDIAN
                    </span>
                  </div>

                  {/* NSRC Hotline */}
                  <div className="p-3.5 rounded-2xl bg-red-50 border border-red-200 flex justify-between items-center text-xs">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-red-600 text-white font-bold flex items-center justify-center">
                        🚨
                      </div>
                      <div>
                        <p className="font-bold text-red-900">National Scam Response Centre</p>
                        <p className="text-red-700 text-[11px]">Dial 997 • 24/7 Federal Fraud Response</p>
                      </div>
                    </div>
                    <a
                      href="tel:997"
                      className="bg-red-600 text-white text-[11px] font-bold px-3 py-1.5 rounded-xl hover:bg-red-700 transition-colors"
                    >
                      Call 997
                    </a>
                  </div>
                </div>
              </div>

              {/* Trusted Devices & Recent Log */}
              <div className="bg-white rounded-[32px] p-6 md:p-8 shadow-[0_20px_50px_rgba(0,0,0,0.08)] border border-gray-100 flex flex-col gap-5">
                <div className="flex items-center justify-between border-b border-gray-100 pb-4">
                  <h3 className="text-xl font-bold text-gray-900">Trusted Devices & Activity</h3>
                  <span className="material-symbols-outlined text-[#0050cb] text-2xl">devices</span>
                </div>

                <div className="flex flex-col gap-3 text-xs">
                  <div className="p-3.5 rounded-2xl bg-gray-50 border border-gray-200 flex justify-between items-center">
                    <div className="flex items-center gap-3">
                      <span className="material-symbols-outlined text-gray-600 text-2xl">smartphone</span>
                      <div>
                        <p className="font-bold text-gray-900">iPhone 15 Pro (Current Device)</p>
                        <p className="text-gray-500 text-[11px]">Kuala Lumpur, MY • Active Now</p>
                      </div>
                    </div>
                    <span className="text-emerald-600 font-bold text-[11px]">● Active</span>
                  </div>

                  <div className="p-3.5 rounded-2xl bg-gray-50 border border-gray-200 flex justify-between items-center">
                    <div className="flex items-center gap-3">
                      <span className="material-symbols-outlined text-gray-600 text-2xl">laptop</span>
                      <div>
                        <p className="font-bold text-gray-900">MacBook Pro 16" (Safari macOS)</p>
                        <p className="text-gray-500 text-[11px]">Last login: 2 hours ago</p>
                      </div>
                    </div>
                    <span className="text-gray-400 font-medium text-[11px]">Trusted</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>

      {/* Daily Limit Modal */}
      {showLimitModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white text-gray-900 rounded-[32px] p-8 max-w-md w-full shadow-2xl relative border border-gray-100">
            <button
              onClick={() => setShowLimitModal(false)}
              className="absolute top-6 right-6 text-gray-400 hover:text-gray-600"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
            <div className="w-12 h-12 rounded-2xl bg-blue-100 text-[#0050cb] flex items-center justify-center mb-4">
              <span className="material-symbols-outlined text-2xl">account_balance</span>
            </div>
            <h3 className="text-2xl font-bold text-gray-900 mb-2">Adjust Transfer Limit</h3>
            <p className="text-xs text-gray-600 mb-6">
              Set your maximum daily online transfer limit across all bank accounts.
            </p>

            <div className="mb-6">
              <label className="form-label text-xs uppercase tracking-wider text-gray-500 font-bold mb-2">
                Daily Limit (RM)
              </label>
              <input
                type="number"
                step="5000"
                value={tempLimit}
                onChange={(e) => setTempLimit(Number(e.target.value))}
                className="form-input text-lg font-bold font-mono text-[#0050cb]"
              />
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => setShowLimitModal(false)}
                className="btn-secondary flex-1 py-3 justify-center text-xs font-bold"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveLimit}
                className="btn-primary flex-1 py-3 justify-center bg-[#0066ff] hover:bg-[#0050cb] text-white text-xs font-bold"
              >
                Save New Limit
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Emergency Kill Switch Modal */}
      {showKillSwitchModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-md z-50 flex items-center justify-center p-4">
          <div className="bg-white text-gray-900 rounded-[32px] p-8 max-w-md w-full shadow-2xl relative border border-red-200">
            <button
              onClick={() => setShowKillSwitchModal(false)}
              className="absolute top-6 right-6 text-gray-400 hover:text-gray-600"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
            <div className="w-14 h-14 rounded-2xl bg-red-100 text-red-600 flex items-center justify-center mb-4 border border-red-200">
              <span className="material-symbols-outlined text-3xl">warning</span>
            </div>
            <h3 className="text-2xl font-bold text-red-900 mb-2">Confirm Account Freeze?</h3>
            <p className="text-xs text-gray-600 mb-6 leading-relaxed">
              Activating the <strong>Emergency Kill Switch</strong> will immediately lock your online banking, disable all outgoing transactions, and alert BNM Fraud Operations.
            </p>

            <div className="p-4 rounded-2xl bg-red-50 border border-red-200 text-xs text-red-800 mb-6">
              <p className="font-bold mb-1">What happens when frozen?</p>
              <ul className="list-disc pl-4 space-y-1 text-[11px]">
                <li>All outgoing DuitNow / IBG transfers blocked.</li>
                <li>Debit cards temporarily disabled.</li>
                <li>NSRC emergency notification logged.</li>
              </ul>
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => setShowKillSwitchModal(false)}
                className="btn-secondary flex-1 py-3 justify-center text-xs font-bold"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmKillSwitch}
                className="btn-danger flex-1 py-3 justify-center bg-[#ba1a1a] hover:bg-[#93000a] text-white text-xs font-bold"
              >
                Confirm Freeze
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
