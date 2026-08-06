import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useSimulation } from '../context/SimulationContext';
import { UserHeader } from '../components/UserHeader';
import robotLineArt from '../assets/robot.png';

export const HomePage: React.FC = () => {
  const { accountBalance, transactions } = useSimulation();
  const navigate = useNavigate();

  return (
    <div className="user-app-layout pb-28 min-h-screen relative bg-[#f8f9fa]">
      {/* Blue Header Background Curve with Robot Line Art */}
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

      {/* Centered Main Container with Explicit Responsive Side Paddings */}
      <div className="main-content-wrapper px-4 sm:px-6 md:px-8">
        {/* Top Header App Bar */}
        <UserHeader />

        {/* Main Content Area */}
        <main className="flex flex-col gap-8 relative z-10 pt-2">
          {/* Welcome Heading */}
          <div className="text-white">
            <h2 className="text-2xl md:text-4xl font-bold tracking-tight">
              Welcome back, JOHN
            </h2>
            <p className="text-white/80 mt-1 text-sm md:text-base">
              Here is what's happening with your accounts today.
            </p>
          </div>

          {/* Desktop Grid: Left Column (Balance + Quick Actions) | Right Column (Activity) */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
            {/* Left Column: Balance Card & Quick Services */}
            <div className="lg:col-span-7 flex flex-col gap-8">
              {/* Savings Account Balance Card */}
              <div className="bg-white rounded-[32px] p-6 md:p-10 shadow-[0_20px_50px_rgba(0,0,0,0.08)] border border-gray-100">
                <p className="text-xs md:text-sm font-bold text-gray-500 uppercase tracking-widest mb-3">
                  Savings Account
                </p>
                <h2 className="text-3xl md:text-5xl font-extrabold text-gray-900 mb-8">
                  RM {accountBalance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </h2>
                <div className="flex flex-col sm:flex-row gap-4">
                  <button
                    onClick={() => navigate('/transfer')}
                    className="flex-1 bg-[#0066ff] text-white font-bold py-4 px-6 rounded-[20px] hover:bg-[#0050cb] transition-all flex justify-center items-center gap-2 shadow-lg shadow-blue-500/20 active:scale-[0.98]"
                  >
                    <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>
                      send
                    </span>
                    Send Money
                  </button>
                  <button
                    className="flex-1 bg-[#dee3eb] text-[#5f656c] font-bold py-4 px-6 rounded-[20px] hover:bg-gray-300 transition-all flex justify-center items-center gap-2 active:scale-[0.98]"
                  >
                    <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>
                      add
                    </span>
                    Add Funds
                  </button>
                </div>
              </div>

              {/* Quick Services Grid */}
              <div>
                <h3 className="text-xl md:text-2xl font-bold text-gray-900 mb-4">Quick Services</h3>
                <div className="grid grid-cols-3 md:grid-cols-6 gap-4">
                  <button
                    onClick={() => navigate('/profile')}
                    className="flex flex-col items-center justify-center bg-white p-4 rounded-[24px] shadow-sm hover:shadow-md transition-all group aspect-square border border-gray-100"
                  >
                    <div className="w-12 h-12 bg-[#dae1ff] rounded-[16px] flex items-center justify-center mb-2 group-hover:scale-110 transition-transform">
                      <span className="material-symbols-outlined text-[#0050cb]" style={{ fontVariationSettings: "'FILL' 0" }}>
                        account_circle
                      </span>
                    </div>
                    <span className="text-xs font-semibold text-gray-900 text-center">My Account</span>
                  </button>

                  <button
                    onClick={() => navigate('/transfer')}
                    className="flex flex-col items-center justify-center bg-white p-4 rounded-[24px] shadow-sm hover:shadow-md transition-all group aspect-square border border-gray-100"
                  >
                    <div className="w-12 h-12 bg-[#dae1ff] rounded-[16px] flex items-center justify-center mb-2 group-hover:scale-110 transition-transform">
                      <span className="material-symbols-outlined text-[#0050cb]" style={{ fontVariationSettings: "'FILL' 0" }}>
                        sync_alt
                      </span>
                    </div>
                    <span className="text-xs font-semibold text-gray-900 text-center">Transfer</span>
                  </button>

                  <button
                    onClick={() => navigate('/scan')}
                    className="flex flex-col items-center justify-center bg-white p-4 rounded-[24px] shadow-sm hover:shadow-md transition-all group aspect-square border border-gray-100"
                  >
                    <div className="w-12 h-12 bg-[#dae1ff] rounded-[16px] flex items-center justify-center mb-2 group-hover:scale-110 transition-transform">
                      <span className="material-symbols-outlined text-[#0050cb]" style={{ fontVariationSettings: "'FILL' 0" }}>
                        description
                      </span>
                    </div>
                    <span className="text-xs font-semibold text-gray-900 text-center">Scan Fraud</span>
                  </button>

                  <button
                    onClick={() => navigate('/call-active')}
                    className="flex flex-col items-center justify-center bg-white p-4 rounded-[24px] shadow-sm hover:shadow-md transition-all group aspect-square border border-gray-100"
                  >
                    <div className="w-12 h-12 bg-[#dae1ff] rounded-[16px] flex items-center justify-center mb-2 group-hover:scale-110 transition-transform">
                      <span className="material-symbols-outlined text-[#0050cb]" style={{ fontVariationSettings: "'FILL' 0" }}>
                        real_estate_agent
                      </span>
                    </div>
                    <span className="text-xs font-semibold text-gray-900 text-center">Copilot</span>
                  </button>

                  <button
                    onClick={() => navigate('/transfer')}
                    className="flex flex-col items-center justify-center bg-white p-4 rounded-[24px] shadow-sm hover:shadow-md transition-all group aspect-square border border-gray-100"
                  >
                    <div className="w-12 h-12 bg-[#dae1ff] rounded-[16px] flex items-center justify-center mb-2 group-hover:scale-110 transition-transform">
                      <span className="material-symbols-outlined text-[#0050cb]" style={{ fontVariationSettings: "'FILL' 0" }}>
                        account_balance_wallet
                      </span>
                    </div>
                    <span className="text-xs font-semibold text-gray-900 text-center">Deposits</span>
                  </button>

                  <button className="flex flex-col items-center justify-center bg-white p-4 rounded-[24px] shadow-sm hover:shadow-md transition-all group aspect-square border border-gray-100">
                    <div className="w-12 h-12 bg-[#dee3eb] rounded-[16px] flex items-center justify-center mb-2 group-hover:scale-110 transition-transform">
                      <span className="material-symbols-outlined text-[#595f66]" style={{ fontVariationSettings: "'FILL' 0" }}>
                        add
                      </span>
                    </div>
                    <span className="text-xs font-semibold text-gray-900 text-center">More</span>
                  </button>
                </div>
              </div>
            </div>

            {/* Right Column: Recent Activity List */}
            <div className="lg:col-span-5">
              <div className="bg-white p-6 md:p-8 rounded-[32px] shadow-[0_10px_30px_rgba(0,0,0,0.05)] border border-gray-200">
                <div className="flex justify-between items-center mb-6">
                  <h3 className="text-xl md:text-2xl font-bold text-gray-900">Recent Activity</h3>
                  <button className="text-[#0050cb] text-sm font-bold hover:underline">See All</button>
                </div>

                <div className="flex flex-col gap-4">
                  {transactions.slice(0, 4).map((tx) => (
                    <div
                      key={tx.id}
                      className="p-4 rounded-[20px] flex items-center justify-between hover:bg-gray-50 transition-colors cursor-pointer border border-transparent hover:border-gray-200"
                    >
                      <div className="flex items-center gap-4">
                        <div
                          className={`w-12 h-12 rounded-full flex items-center justify-center ${
                            tx.type === 'debit' ? 'bg-[#ffdad6]' : 'bg-[#dae1ff]'
                          }`}
                        >
                          <span
                            className={`material-symbols-outlined ${tx.type === 'debit' ? 'text-[#ba1a1a]' : 'text-[#0050cb]'}`}
                            style={{ fontVariationSettings: "'FILL' 0" }}
                          >
                            {tx.type === 'debit' ? 'arrow_upward' : 'arrow_downward'}
                          </span>
                        </div>
                        <div>
                          <p className="text-base font-semibold text-gray-900">{tx.recipient}</p>
                          <p className="text-xs text-gray-500">{tx.date} • {tx.category}</p>
                        </div>
                      </div>

                      <div className="text-right">
                        <p className={`text-base font-bold ${tx.type === 'debit' ? 'text-gray-900' : 'text-[#0050cb]'}`}>
                          {tx.type === 'debit' ? '-' : '+'}RM {tx.amount.toFixed(2)}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Promo Card */}
                <div className="mt-8 p-6 bg-[#0066ff] rounded-[24px] text-white">
                  <h4 className="font-bold text-lg mb-1">New Savings Goal?</h4>
                  <p className="text-sm opacity-90 mb-4">Start a goal today and get up to 4.5% p.a. interest.</p>
                  <button className="bg-white text-[#0066ff] px-4 py-2 rounded-xl text-sm font-bold hover:bg-gray-100 transition-colors">
                    Learn More
                  </button>
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
};
