import React, { createContext, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { TranSafeApiClient } from '../services/api';
import type { BackendConfig } from '../types/api';
import { useAuth } from './AuthContext';

// ── Defaults ───────────────────────────────────────────────────
const DEFAULT_API_KEY = 'transafe-hackathon-key-2026';
const DEFAULT_ADMIN_KEY = 'transafe-admin-key-2026';
const SEED_USER_ID = '619ebd02-82fc-4a13-81f6-ff575c20278d';

/**
 * Resolve the backend base URL.
 * - Tunnel hosts (trycloudflare / loca.lt / ngrok) serve the API from the same
 *   origin, so fall back to `window.location.origin` and let the Vite proxy
 *   forward `/api`, `/admin` and `/ws` to the backend.
 * - Local dev uses `{protocol}//{host}:8000` directly.
 */
export function getInitialBaseUrl(): string {
  if (typeof window === 'undefined') return 'http://localhost:8000';
  const host = window.location.hostname || 'localhost';
  if (host === 'localhost') {
    return 'http://localhost:8000';
  }
  if (/(trycloudflare\.com|loca\.lt|ngrok)/.test(window.location.host)) {
    return window.location.origin;
  }
  return import.meta.env.VITE_BACKEND_URL || 'https://transafe-production.up.railway.app';
}

export function getDefaultConfig(): BackendConfig {
  return {
    baseUrl: getInitialBaseUrl(),
    apiKey: DEFAULT_API_KEY,
    adminKey: DEFAULT_ADMIN_KEY,
  };
}

// ── Context ────────────────────────────────────────────────────
interface ApiContextType {
  config: BackendConfig;
  setConfig: React.Dispatch<React.SetStateAction<BackendConfig>>;
  client: TranSafeApiClient;
  /** Resolved user id: auth session user id when logged in, else seed user. */
  userId: string;
  /** Stable client session id for telemetry / triggers. */
  sessionId: string;
}

const ApiContext = createContext<ApiContextType | undefined>(undefined);

export const useApi = (): ApiContextType => {
  const ctx = useContext(ApiContext);
  if (!ctx) throw new Error('useApi must be used within an ApiProvider');
  return ctx;
};

const CLIENT_SESSION_KEY = 'transafe_client_session_id';

export const ApiProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const { session } = useAuth();
  const [config, setConfig] = useState<BackendConfig>(() => getDefaultConfig());

  // Stable per-browser session id (persisted so telemetry is consistent)
  const [sessionId] = useState<string>(() => {
    try {
      const existing = localStorage.getItem(CLIENT_SESSION_KEY);
      if (existing) return existing;
      const fresh = 'sess-web-' + Math.random().toString(36).substring(2, 10);
      localStorage.setItem(CLIENT_SESSION_KEY, fresh);
      return fresh;
    } catch {
      return 'sess-web-' + Math.random().toString(36).substring(2, 10);
    }
  });

  const userId = useMemo(() => {
    if (session?.user?.id) return session.user.id;
    return SEED_USER_ID;
  }, [session]);

  const client = useMemo(() => new TranSafeApiClient(config), [config]);

  const value = useMemo(
    () => ({ config, setConfig, client, userId, sessionId }),
    [config, client, userId, sessionId]
  );

  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>;
};
