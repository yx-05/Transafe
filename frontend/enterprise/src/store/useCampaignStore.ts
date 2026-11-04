/**
 * Campaigns, cases and artifacts.
 *
 * Data lives here; motion lives in useEventStore. This store re-fetches when
 * a relevant ns_event lands, so the screens stay honest without polling.
 */

import { create } from "zustand";
import { api } from "../services/api";
import type {
  ArtifactGroup,
  CampaignDetail,
  CampaignSummary,
  CaseSummary,
} from "../types/campaign";
import type { OverviewResponse } from "../types/api";

/**
 * Collapse a burst of refresh calls into one in-flight request plus a single
 * trailing re-run.
 *
 * Screens re-fetch when a real `ns_event` lands — never on a timer — so a
 * REPLAY run that emits ~25 events in a few seconds issues ~25 refreshes. One
 * overview refresh costs several Supabase round-trips, and a burst that size is
 * enough to exhaust the HTTP/2 connection pool. The API degrades to empty
 * results rather than erroring, so the failure surfaces as **zeroed counters on
 * screen at the exact moment an audience is watching** — which is how this was
 * found.
 *
 * Coalescing keeps the event-driven contract (events still drive the refresh)
 * while making the cost of a burst independent of its length.
 */
function coalesce<A extends unknown[]>(
  fn: (...args: A) => Promise<void>,
): (...args: A) => Promise<void> {
  let inFlight = false;
  let pending: A | null = null;

  return async (...args: A): Promise<void> => {
    if (inFlight) {
      // Keep only the newest request: these are idempotent refreshes, so the
      // last one supersedes every one it replaced.
      pending = args;
      return;
    }
    inFlight = true;
    try {
      await fn(...args);
      while (pending) {
        const next = pending;
        pending = null;
        await fn(...next);
      }
    } finally {
      inFlight = false;
    }
  };
}

interface CampaignStore {
  overview: OverviewResponse | null;
  cases: CaseSummary[];
  campaigns: CampaignSummary[];
  selectedCampaign: CampaignDetail | null;
  artifacts: ArtifactGroup[];
  loading: boolean;
  error: string | null;

  loadOverview: () => Promise<void>;
  loadCases: () => Promise<void>;
  loadCampaigns: () => Promise<void>;
  loadCampaign: (id: string) => Promise<void>;
  loadArtifacts: (tier?: "core" | "pack") => Promise<void>;
  approve: (id: string) => Promise<void>;
  reject: (id: string, reason: string) => Promise<void>;
}

export const useCampaignStore = create<CampaignStore>((set, get) => ({
  overview: null,
  cases: [],
  campaigns: [],
  selectedCampaign: null,
  artifacts: [],
  loading: false,
  error: null,

  loadOverview: async () => {
    set({ loading: true, error: null });
    try {
      set({ overview: await api.getOverview() });
    } catch (e) {
      set({ error: String(e) });
    } finally {
      set({ loading: false });
    }
  },

  loadCases: async () => {
    set({ loading: true, error: null });
    try {
      const res = await api.getCases();
      set({ cases: res.cases });
    } catch (e) {
      set({ error: String(e) });
    } finally {
      set({ loading: false });
    }
  },

  loadCampaigns: async () => {
    set({ loading: true, error: null });
    try {
      const res = await api.getCampaigns();
      set({ campaigns: res.campaigns });
    } catch (e) {
      set({ error: String(e) });
    } finally {
      set({ loading: false });
    }
  },

  loadCampaign: async (id: string) => {
    set({ loading: true, error: null });
    try {
      set({ selectedCampaign: await api.getCampaign(id) });
    } catch (e) {
      set({ error: String(e) });
    } finally {
      set({ loading: false });
    }
  },

  loadArtifacts: async (tier?: "core" | "pack") => {
    set({ loading: true, error: null });
    try {
      const res = await api.getArtifacts(tier);
      set({ artifacts: res.artifacts });
    } catch (e) {
      set({ error: String(e) });
    } finally {
      set({ loading: false });
    }
  },

  approve: async (id: string) => {
    await api.approveCampaign(id);
    await get().loadCampaigns();
    if (get().selectedCampaign?.id === id) await get().loadCampaign(id);
  },

  reject: async (id: string, reason: string) => {
    await api.rejectCampaign(id, reason);
    await get().loadCampaigns();
    if (get().selectedCampaign?.id === id) await get().loadCampaign(id);
  },
}));

// Refresh loaders are idempotent reads that every screen fires on every relevant
// ns_event, so they are the ones that stampede. Wrapping them here rather than
// at each call site means a screen added later inherits the protection instead
// of re-introducing the burst.
const { loadOverview, loadCases, loadCampaigns, loadArtifacts } =
  useCampaignStore.getState();

useCampaignStore.setState({
  loadOverview: coalesce(loadOverview),
  loadCases: coalesce(loadCases),
  loadCampaigns: coalesce(loadCampaigns),
  loadArtifacts: coalesce(loadArtifacts),
});
