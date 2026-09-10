/**
 * Persistent shell — header, always-visible mode badge, counters, navigation.
 *
 * ┌─ TRANSAFE ENTERPRISE ───── [● LIVE ⇄ REPLAY] [▶ Run Scenario] [↺ Reset] ─┐
 * │  Cases 47 │ Open 12 │ ⚠ Unrecognised 1 │ Campaigns 2 │ Core v7 │ RM …    │
 * └──────────────────────────────────────────────────────────────────────────┘
 */

import { useCallback, useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Activity, Play, RotateCcw, Repeat } from "lucide-react";
import { useEventStore } from "../store/useEventStore";
import { useCampaignStore } from "../store/useCampaignStore";
import { useEventSubscription } from "../hooks/useEventSubscription";
import { loadReplaySequence } from "../services/replay";
import { api } from "../services/api";
import { formatNumber } from "../lib/format";

const NAV = [
  { to: "/", label: "OVERVIEW", end: true },
  { to: "/cases", label: "CASES" },
  { to: "/graph", label: "SCAM GRAPH" },
  { to: "/validation", label: "VALIDATION" },
  { to: "/registry", label: "REGISTRY" },
  { to: "/eval", label: "EVALUATION" },
  { to: "/mcp", label: "MCP LOG" },
];

export function Shell() {
  const mode = useEventStore((s) => s.mode);
  const isConnected = useEventStore((s) => s.isConnected);
  const activate = useEventStore((s) => s.activate);
  const clearEvents = useEventStore((s) => s.clearEvents);
  const overview = useCampaignStore((s) => s.overview);
  const loadOverview = useCampaignStore((s) => s.loadOverview);
  const [busy, setBusy] = useState(false);

  // Open the LIVE stream on mount. The socket replays a backlog on connect;
  // we also hydrate from GET /enterprise/events so a page refresh mid-demo
  // shows the history the operator already narrated.
  useEffect(() => {
    activate("LIVE");
    void useEventStore.getState().hydrate(100);
    return () => useEventStore.getState().disconnect();
    // activate is stable (zustand action)
  }, [activate]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  // Counters refresh when the system actually did something — never on a timer.
  useEventSubscription(
    () => {
      void loadOverview();
    },
    { eventTypes: ["case_ingested", "campaign_proposed", "campaign_approved", "artifact_published"] },
  );

  const toggleMode = useCallback(async () => {
    setBusy(true);
    try {
      if (mode === "LIVE") {
        const recorded = await loadReplaySequence();
        clearEvents();
        void api.startScenario("replay", 1);
        activate("REPLAY", { replay: recorded, speed: 1 });
      } else {
        clearEvents();
        activate("LIVE");
      }
    } finally {
      setBusy(false);
    }
  }, [mode, activate, clearEvents]);

  const runScenario = useCallback(async () => {
    setBusy(true);
    try {
      if (mode === "REPLAY") {
        const recorded = await loadReplaySequence();
        clearEvents();
        activate("REPLAY", { replay: recorded, speed: 1 });
      } else {
        await api.startScenario("live", 1);
      }
    } finally {
      setBusy(false);
    }
  }, [mode, activate, clearEvents]);

  const reset = useCallback(async () => {
    setBusy(true);
    try {
      clearEvents();
      await api.resetDemo();
      await loadOverview();
    } finally {
      setBusy(false);
    }
  }, [clearEvents, loadOverview]);

  // One-key switch: M toggles mode, R resets.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (e.key === "m" || e.key === "M") void toggleMode();
      if (e.key === "r" || e.key === "R") void reset();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleMode, reset]);

  const c = overview?.counters;

  return (
    <div className="shell">
      <header className="shell-header">
        <div className="shell-header-top">
          <div className="brand">
            TRANSAFE <span>ENTERPRISE</span>
          </div>

          <div className="shell-actions">
            <span
              className={`mode-badge ${mode === "LIVE" ? "live" : "replay"}`}
              data-testid="mode-badge"
              title={
                mode === "LIVE"
                  ? "Full pipeline — every layer running for real"
                  : "Recorded ns_events from a real LIVE run"
              }
            >
              <span className={`mode-dot ${isConnected ? "" : "off"}`} />
              {mode}
            </span>
            <button
              type="button"
              className="btn"
              onClick={() => void toggleMode()}
              disabled={busy}
              title="Switch event source (M)"
            >
              <Repeat size={12} /> {mode === "LIVE" ? "REPLAY" : "LIVE"}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void runScenario()}
              disabled={busy}
            >
              <Play size={12} /> RUN SCENARIO
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => void reset()}
              disabled={busy}
              title="Reset to clean pre-campaign state (R)"
            >
              <RotateCcw size={12} /> RESET
            </button>
          </div>
        </div>

        <div className="counter-strip" data-testid="counter-strip">
          <span className="counter">
            <Activity size={11} style={{ verticalAlign: "-1px" }} /> Cases{" "}
            <b>{c ? formatNumber(c.cases) : "—"}</b>
          </span>
          <span className="counter">
            Open <b>{c ? formatNumber(c.open_cases) : "—"}</b>
          </span>
          <span className={`counter ${c && c.unrecognised > 0 ? "alert" : ""}`}>
            ⚠ Unrecognised <b>{c ? formatNumber(c.unrecognised) : "—"}</b>
          </span>
          <span className="counter">
            Campaigns <b>{c ? formatNumber(c.campaigns) : "—"}</b>
          </span>
          <span className="counter">
            Core <b>v{c?.core_version ?? "—"}</b>
          </span>
          <span className="counter">
            Exposure <b>RM {c ? formatNumber(c.exposure_rm) : "—"}</b>
          </span>
        </div>
      </header>

      <nav className="shell-nav">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <main className="shell-body">
        <Outlet />
      </main>
    </div>
  );
}

export default Shell;
