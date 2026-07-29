import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useSimulation } from '../context/SimulationContext';
import { UserHeader } from '../components/UserHeader';
import robotLineArt from '../assets/robot.png';

export const HomePage: React.FC = () => {
  const { accountBalance, transactions } = useSimulation();
  const navigate = useNavigate();

  return (
    <div style={{ minHeight: '100vh', backgroundColor: 'var(--background)', position: 'relative' }}>
      {/* Blue Header Background Curve with Line Art */}
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

      {/* Top Header App Bar */}
      <div className="header-padding-wrapper">
        <UserHeader />
      </div>

      {/* Main Content */}
      <main className="home-page-main" style={{ position: 'relative', zIndex: 10, display: 'flex', flexDirection: 'column', gap: '24px', marginTop: '-16px' }}>
        {/* Welcome Heading */}
        <div>
          <h2 className="welcome-heading">Welcome back, JOHN</h2>
          <p className="welcome-sub">Here is what's happening with your accounts today.</p>
        </div>

        {/* Desktop Grid: Left Column (Balance + Quick Actions) | Right Column (Activity) */}
        <div className="desktop-grid">
          {/* Left Column */}
          <div className="desktop-left-col">
            {/* Balance Card */}
            <div className="balance-card">
              <p className="balance-label">Savings Account</p>
              <h2 className="balance-amount">
                RM {accountBalance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginTop: '24px' }}>
                <button
                  onClick={() => navigate('/transfer')}
                  className="btn-send-money"
                  style={{ width: '100%' }}
                >
                  <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>
                    send
                  </span>
                  Send Money
                </button>
                <button
                  className="btn-secondary-action"
                >
                  <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>
                    add
                  </span>
                  Add Funds
                </button>
              </div>
            </div>

            {/* Quick Actions */}
            <div>
              <h3 className="quick-services-title">Quick Services</h3>
              <div className="quick-actions-grid">
                <button onClick={() => navigate('/transfer')} className="quick-action-btn">
                  <div className="quick-action-icon">
                    <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 0" }}>account_circle</span>
                  </div>
                  <span className="quick-action-label">My Account</span>
                </button>

                <button onClick={() => navigate('/transfer')} className="quick-action-btn">
                  <div className="quick-action-icon">
                    <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 0" }}>sync_alt</span>
                  </div>
                  <span className="quick-action-label">Transfer</span>
                </button>

                <button onClick={() => navigate('/scan')} className="quick-action-btn">
                  <div className="quick-action-icon">
                    <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 0" }}>description</span>
                  </div>
                  <span className="quick-action-label">Statement</span>
                </button>

                <button onClick={() => navigate('/call-active')} className="quick-action-btn">
                  <div className="quick-action-icon">
                    <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 0" }}>real_estate_agent</span>
                  </div>
                  <span className="quick-action-label">My Loans</span>
                </button>

                <button onClick={() => navigate('/transfer')} className="quick-action-btn">
                  <div className="quick-action-icon">
                    <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 0" }}>account_balance_wallet</span>
                  </div>
                  <span className="quick-action-label">Deposits</span>
                </button>

                <button className="quick-action-btn">
                  <div className="quick-action-icon more">
                    <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 0" }}>add</span>
                  </div>
                  <span className="quick-action-label">More</span>
                </button>
              </div>
            </div>
          </div>

          {/* Right Column: Recent Activity */}
          <div className="desktop-right-col">
            <div className="activity-sidebar-card">
              <div className="activity-section-header">
                <h3 className="activity-title">Recent Activity</h3>
                <button className="activity-see-all">See All</button>
              </div>

              <div className="activity-list">
                {transactions.slice(0, 3).map((tx) => (
                  <div key={tx.id} className="activity-item">
                    <div className="activity-item-left">
                      <div className={`activity-icon ${tx.type === 'debit' ? 'debit' : 'credit'}`}>
                        <span className="material-symbols-outlined" style={{ fontSize: '20px', fontVariationSettings: "'FILL' 0" }}>
                          {tx.type === 'debit' ? 'arrow_upward' : 'arrow_downward'}
                        </span>
                      </div>
                      <div>
                        <p className="activity-name">{tx.recipient}</p>
                        <p className="activity-date">{tx.date}</p>
                      </div>
                    </div>

                    <p className={`activity-amount ${tx.type === 'debit' ? 'debit' : 'credit'}`}>
                      {tx.type === 'debit' ? '-' : '+'}RM {tx.amount.toFixed(2)}
                    </p>
                  </div>
                ))}
              </div>

              {/* Promo Card */}
              <div className="promo-card">
                <h4 className="promo-title">New Savings Goal?</h4>
                <p className="promo-text">Start a goal today and get up to 4.5% p.a. interest.</p>
                <button className="promo-btn">Learn More</button>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
};
