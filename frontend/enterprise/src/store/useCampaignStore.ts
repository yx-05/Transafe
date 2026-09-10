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
