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
 *
 * Two corrections to the folklore above, both measured against the live system.
 * A sweep takes ~173 s and the RESET before it ~24 s, so a single end-to-end
 * budget of 180 s expired while the pipeline was still working: the panel cried
 * "Timed out" and the campaign that sweep went on to propose went unreported.
 * The budget is therefore armed per step, not per chain.
 *
 * And it is sweep **1** that promotes, not sweep 2. After a reseed the campaign
 * is novel, so the proposal lands just *before* that sweep's completion event —
 * which is why gating the "ready" transition on `sweeping2` meant it almost
 * never fired. One sweep normally suffices; sweep 2 is a fallback for when it
 * does not.
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

/** Give up after this long on any single step, rather than spinning forever. */
const STEP_TIMEOUT_MS = 300_000;

/** Stages that are waiting on the pipeline — the ones a timer is armed for. */
const WAITING_STAGES: ReadonlySet<PrepStage> = new Set([
  "resetting",
  "sweeping",
  "sweeping2",
]);

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

  // Set when this warm-up sees its own sweep start. A candidate replayed out of
  // the socket backlog arrives before that, so it cannot report the warm-up as
  // finished before the sweep it is waiting for has even begun. Comparing
  // timestamps would do locally but breaks on a hosted demo whose viewer's clock
  // is skewed, so this uses a server-side ordering fact instead.
  const sawSweepStartRef = useRef(false);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  /**
   * Move to a stage, re-arming the budget.
   *
   * Arming per step is what stops a long sweep from being charged against the
   * time the previous step already spent.
   */
  const moveTo = useCallback(
    (next: PrepStage, message: string) => {
      stageRef.current = next;
      setStage(next);
      setDetail(message);

      clearTimer();
      if (WAITING_STAGES.has(next)) {
        timerRef.current = window.setTimeout(() => {
          // Only report a timeout if this step is still the one waiting.
          if (!WAITING_STAGES.has(stageRef.current)) return;
          stageRef.current = "failed";
          setStage("failed");
          setDetail("Timed out waiting for the pipeline. Check the backend log.");
        }, STEP_TIMEOUT_MS);
      }
    },
    [clearTimer],
  );

  useEffect(() => clearTimer, [clearTimer]);

  const startWarmup = useCallback(async () => {
    // ``moveTo`` arms the step budget for every waiting stage it enters.
    sawSweepStartRef.current = false;
    moveTo("resetting", "Clearing v2 state and reseeding…");

    try {
      await api.resetDemo();
      await api.runDiscovery();
      moveTo("sweeping", "Sweep 1 — looking for a promotable campaign…");
    } catch (error) {
      clearTimer();
      moveTo("failed", `Warm-up failed: ${String(error)}`);
    }
  }, [clearTimer, moveTo]);

  // Sweep 1 finished without proposing anything → fire the fallback sweep.
  // When it *did* propose, the stage is already "ready" and this is a no-op.
  useEventSubscription(
    () => {
      if (stageRef.current !== "sweeping") return;
      moveTo("sweeping2", "Sweep 2 — re-checking for a promotable campaign…");
      void api.runDiscovery().catch((error) => {
        clearTimer();
        moveTo("failed", `Second sweep failed: ${String(error)}`);
      });
    },
    { eventTypes: ["discovery_sweep_completed"] },
  );

  // The sweep we asked for has actually begun.
  useEventSubscription(
    () => {
      if (!WAITING_STAGES.has(stageRef.current)) return;
      sawSweepStartRef.current = true;
    },
    { eventTypes: ["discovery_sweep_started"] },
  );

  // A candidate exists → done. Accepted from either sweep: the proposal is
  // emitted *before* its own sweep's completion event, so gating this on
  // "sweeping2" meant it almost never fired and the chain always timed out.
  useEventSubscription(
    () => {
      if (!WAITING_STAGES.has(stageRef.current)) return;
      if (!sawSweepStartRef.current) return;
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
