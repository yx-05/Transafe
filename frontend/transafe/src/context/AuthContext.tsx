import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';

// ── Types ──────────────────────────────────────────────────────
export interface AuthUser {
  id: string;
  display_name: string;
  risk_profile: string;
}

export interface AuthAccount {
  account_number: string;
  account_type: string;
  balance_myr: number;
  status: string;
}

interface AuthSession {
  token: string;
  expires_at: string;
  user: AuthUser;
  account: AuthAccount;
}

interface AuthContextType {
  /** Current authenticated session, or null if not logged in. */
  session: AuthSession | null;
  /** True while a login request is in-flight. */
  isLoading: boolean;
  /** Last auth error message, if any. */
  error: string | null;
  /** Attempt to sign in with account number and PIN. */
  signIn: (accountNumber: string, pin: string) => Promise<boolean>;
  /** Clear session and redirect to login. */
  signOut: () => void;
  /** Whether the user is currently authenticated. */
  isAuthenticated: boolean;
  /** The backend base URL. */
  backendUrl: string;
}

const AUTH_STORAGE_KEY = 'transafe_auth_session';

// ── Default backend URL ────────────────────────────────────────
const DEFAULT_BACKEND_URL = import.meta.env.VITE_BACKEND_URL || (typeof window !== 'undefined' && window.location.hostname === 'localhost' ? 'http://localhost:8000' : 'https://transafe-production.up.railway.app');

// ── Context ────────────────────────────────────────────────────
const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = (): AuthContextType => {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
};

// ── Provider ───────────────────────────────────────────────────
export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const backendUrl = DEFAULT_BACKEND_URL;

  // Restore session from localStorage on mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem(AUTH_STORAGE_KEY);
      if (stored) {
        const parsed: AuthSession = JSON.parse(stored);
        // Check if token is expired
        const expiresAt = new Date(parsed.expires_at).getTime();
        if (Date.now() < expiresAt) {
          setSession(parsed);
        } else {
          localStorage.removeItem(AUTH_STORAGE_KEY);
        }
      }
    } catch {
      localStorage.removeItem(AUTH_STORAGE_KEY);
    }
  }, []);

  const signIn = useCallback(async (accountNumber: string, pin: string): Promise<boolean> => {
    setIsLoading(true);
    setError(null);

    try {
      const res = await fetch(`${backendUrl}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_number: accountNumber, pin }),
      });

      const json = await res.json();

      if (!res.ok || !json.success) {
        const errMsg = json?.error?.message || json?.detail?.message || 'Authentication failed.';
        setError(errMsg);
        setIsLoading(false);
        return false;
      }

      const authSession: AuthSession = {
        token: json.data.token,
        expires_at: json.data.expires_at,
        user: json.data.user,
        account: json.data.account,
      };

      setSession(authSession);
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(authSession));
      setIsLoading(false);
      return true;
    } catch (err) {
      // Network error — fall back to offline demo mode
      console.warn('Backend unreachable, using offline demo mode:', err);
      const offlineSession: AuthSession = {
        token: 'offline-demo-token',
        expires_at: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
        user: {
          id: '619ebd02-82fc-4a13-81f6-ff575c20278d',
          display_name: 'John Doe',
          risk_profile: 'normal',
        },
        account: {
          account_number: accountNumber,
          account_type: 'SAVINGS',
          balance_myr: 24850.75,
          status: 'active',
        },
      };

      setSession(offlineSession);
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(offlineSession));
      setIsLoading(false);
      return true;
    }
  }, [backendUrl]);

  const signOut = useCallback(() => {
    setSession(null);
    setError(null);
    localStorage.removeItem(AUTH_STORAGE_KEY);
  }, []);

  const isAuthenticated = session !== null;

  return (
    <AuthContext.Provider
      value={{ session, isLoading, error, signIn, signOut, isAuthenticated, backendUrl }}
    >
      {children}
    </AuthContext.Provider>
  );
};
