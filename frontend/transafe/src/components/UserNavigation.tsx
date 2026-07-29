import React from 'react';
import { NavLink } from 'react-router-dom';

const NavItem: React.FC<{ to: string; icon: string; label: string }> = ({ to, icon, label }) => (
  <NavLink to={to} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
    {({ isActive }) => (
      <>
        <span
          className="material-symbols-outlined nav-link-icon"
          style={{ fontVariationSettings: isActive ? "'FILL' 1" : "'FILL' 0", color: isActive ? 'var(--primary)' : 'var(--secondary)' }}
        >
          {icon}
        </span>
        <span className="nav-link-label" style={{ color: isActive ? 'var(--primary)' : 'var(--secondary)', fontWeight: isActive ? 700 : 500 }}>
          {label}
        </span>
      </>
    )}
  </NavLink>
);

export const UserNavigation: React.FC = () => {
  return (
    <nav className="bottom-nav">
      <NavItem to="/" icon="home" label="Home" />
      <NavItem to="/transfer" icon="sync_alt" label="Transfer" />
      <NavItem to="/scan" icon="verified_user" label="Scan" />
      <NavItem to="/call-active" icon="real_estate_agent" label="Copilot" />
    </nav>
  );
};
