/**
 * Demo warm-up and readiness, driven by real events rather than timers.
 *
 * The manual runbook is: RESET, then `POST /discovery/run` **twice** — the
 * first sweep does not promote, the second does. That "press it twice" rule is
 * folklore an operator has to remember, and forgetting it looks exactly like a
 * broken system.
 *
 * The chain is observable, so it is driven rather than guessed:
 *
 *   reset → discovery #1 → `discovery_sweep_completed` → discovery #2
 *         → `campaign_proposed` → ready
 *
 * Nothing here polls. Every transition is a real event from the pipeline, the
 * same discipline every screen in this console follows.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../services/api";
import { useEventSubscription } from "./useEventSubscription";
import type { PreflightResponse } from "../types/api";

export type PrepStage =
  | "idle"
  | "resetting"
  | "sweeping"
  | "sweeping2"
  | "ready"
  | "failed";

/** Give up after this long and say so, rather than spinning forever. */
const WARMUP_TIMEOUT_MS = 180_000;

export interface DemoPrep {
  stage: PrepStage;
  detail: string;
  busy: boolean;
  preflight: PreflightResponse | null;
  checking: boolean;
  startWarmup: () => Promise<void>;
  checkReadiness: () => Promise<void>;
  clear: () => void;
}

export function useDemoPrep(): DemoPrep {
  const [stage, setStage] = useState<PrepStage>("idle");
  const [detail, setDetail] = useState("");
  const [preflight, setPreflight] = useState<PreflightResponse | null>(null);
  const [checking, setChecking] = useState(false);

  // The event handlers are registered once and must read the *current* stage,
  // not the one captured when the subscription was created.
  const stageRef = useRef<PrepStage>("idle");
  const timerRef = useRef<number | null>(null);

  const moveTo = useCallback((next: PrepStage, message: string) => {
    stageRef.current = next;
    setStage(next);
    setDetail(message);
  }, []);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => clearTimer, [clearTimer]);

  const startWarmup = useCallback(async () => {
    clearTimer();
    moveTo("resetting", "Clearing v2 state and reseeding…");
    timerRef.current = window.setTimeout(() => {
      moveTo("failed", "Timed out waiting for the pipeline. Check the backend log.");
    }, WARMUP_TIMEOUT_MS);

    try {
      await api.resetDemo();
      await api.runDiscovery();
      moveTo("sweeping", "Sweep 1 of 2 — this one does not promote.");
    } catch (error) {
      clearTimer();
      moveTo("failed", `Warm-up failed: ${String(error)}`);
    }
  }, [clearTimer, moveTo]);

  // Sweep 1 finished → fire sweep 2.
  useEventSubscription(
    () => {
      if (stageRef.current !== "sweeping") return;
      moveTo("sweeping2", "Sweep 2 of 2 — this is the one that promotes.");
      void api.runDiscovery().catch((error) => {
        clearTimer();
        moveTo("failed", `Second sweep failed: ${String(error)}`);
      });
    },
    { eventTypes: ["discovery_sweep_completed"] },
  );

  // A candidate exists → done.
  useEventSubscription(
    () => {
      if (stageRef.current !== "sweeping2") return;
      clearTimer();
      moveTo("ready", "Candidate campaign ready — open VALIDATION to review it.");
    },
    { eventTypes: ["campaign_proposed"] },
  );

  const checkReadiness = useCallback(async () => {
    setChecking(true);
    try {
      setPreflight(await api.getPreflight());
    } finally {
      setChecking(false);
    }
  }, []);

  const clear = useCallback(() => {
    clearTimer();
    moveTo("idle", "");
  }, [clearTimer, moveTo]);

  return {
    stage,
    detail,
    busy: stage === "resetting" || stage === "sweeping" || stage === "sweeping2",
    preflight,
    checking,
    startWarmup,
    checkReadiness,
    clear,
  };
}

export default useDemoPrep;
