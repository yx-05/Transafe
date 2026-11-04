/**
 * Tests for the demo warm-up chain.
 *
 * The rule being protected is the one an operator otherwise has to remember:
 * **discovery must run twice.** The first sweep does not promote. Encoding it
 * here means a future change that breaks the chain fails a test rather than
 * failing on stage.
 *
 * That rule is wrong, and the live system says so. Measured against the running
 * pipeline, sweep **1** is the one that promotes — after a reseed the campaign
 * is novel — and it emits `campaign_proposed` *before* its own
 * `discovery_sweep_completed`. A sweep takes ~173 s and the reset before it
 * ~24 s, so the old 180 s end-to-end budget expired mid-flight and the panel
 * reported a timeout for a warm-up that had actually succeeded. The tests below
 * pin the corrected ordering; the stale-proposal guard is now expressed as
 * "this warm-up has seen its own sweep start", which holds regardless of how
 * many sweeps turn out to be needed.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useDemoPrep } from "./useDemoPrep";
import { useEventStore } from "../store/useEventStore";
import { api, __resetFixtureState } from "../services/api";
import type { NsEvent } from "../types/events";

function emit(eventType: string, layer: NsEvent["layer"] = "discovery") {
  const event = {
    id: Date.now(),
    ts: new Date().toISOString(),
    layer,
    event_type: eventType,
    severity: "info",
    payload: {},
  } as unknown as NsEvent;
  useEventStore.setState({ lastEvent: event });
}

describe("useDemoPrep", () => {
  let resetSpy: ReturnType<typeof vi.spyOn>;
  let discoverySpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    __resetFixtureState();
    useEventStore.setState({ lastEvent: null });
    resetSpy = vi.spyOn(api, "resetDemo").mockResolvedValue({ ok: true } as never);
    discoverySpy = vi.spyOn(api, "runDiscovery").mockResolvedValue({ ok: true } as never);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts idle", () => {
    const { result } = renderHook(() => useDemoPrep());
    expect(result.current.stage).toBe("idle");
    expect(result.current.busy).toBe(false);
  });

  it("resets, then runs the first sweep", async () => {
    const { result } = renderHook(() => useDemoPrep());

    await act(async () => {
      await result.current.startWarmup();
    });

    expect(resetSpy).toHaveBeenCalledTimes(1);
    expect(discoverySpy).toHaveBeenCalledTimes(1);
    expect(result.current.stage).toBe("sweeping");
  });

  it("runs a SECOND sweep when the first one completes", async () => {
    // The whole point: one sweep yields nothing, and an operator who does not
    // know that reads it as a broken pipeline.
    const { result } = renderHook(() => useDemoPrep());

    await act(async () => {
      await result.current.startWarmup();
    });
    expect(discoverySpy).toHaveBeenCalledTimes(1);

    act(() => emit("discovery_sweep_completed"));

    await waitFor(() => expect(discoverySpy).toHaveBeenCalledTimes(2));
    expect(result.current.stage).toBe("sweeping2");
  });

  it("does not queue a second sweep before the first has finished", async () => {
    const { result } = renderHook(() => useDemoPrep());

    await act(async () => {
      await result.current.startWarmup();
    });
    // Two completion events for one in-flight sweep must not fan out.
    act(() => emit("discovery_sweep_completed"));
    await waitFor(() => expect(discoverySpy).toHaveBeenCalledTimes(2));

    act(() => emit("discovery_sweep_completed"));

    expect(discoverySpy).toHaveBeenCalledTimes(2);
  });

  it("is ready once a candidate is proposed", async () => {
    const { result } = renderHook(() => useDemoPrep());

    await act(async () => {
      await result.current.startWarmup();
    });
    act(() => emit("discovery_sweep_started"));
    act(() => emit("discovery_sweep_completed"));
    await waitFor(() => expect(result.current.stage).toBe("sweeping2"));

    act(() => emit("campaign_proposed", "compiler"));

    expect(result.current.stage).toBe("ready");
    expect(result.current.busy).toBe(false);
  });

  it("is ready when the FIRST sweep proposes, without waiting for a second", async () => {
    // Measured against the live system: after a reseed the campaign is novel,
    // so sweep 1 emits `campaign_proposed` and only afterwards reports
    // `discovery_sweep_completed`. Gating "ready" on the second sweep therefore
    // never matched, and the chain always died on its timeout while the
    // pipeline had in fact succeeded.
    const { result } = renderHook(() => useDemoPrep());

    await act(async () => {
      await result.current.startWarmup();
    });
    act(() => emit("discovery_sweep_started"));
    act(() => emit("campaign_proposed", "discovery"));

    expect(result.current.stage).toBe("ready");
    // The proposal is the finish line — no second sweep should be queued.
    expect(discoverySpy).toHaveBeenCalledTimes(1);
  });

  it("ignores a candidate that arrives before this warm-up's own sweep starts", async () => {
    // A campaign left over from a previous run can still be replayed out of the
    // socket backlog on a reconnect. It must not report the warm-up as finished
    // before the sweep it is waiting for has even started.
    const { result } = renderHook(() => useDemoPrep());

    await act(async () => {
      await result.current.startWarmup();
    });
    act(() => emit("campaign_proposed", "compiler"));

    expect(result.current.stage).toBe("sweeping");
  });

  it("reports a failure instead of spinning when reset throws", async () => {
    resetSpy.mockRejectedValue(new Error("backend offline"));
    const { result } = renderHook(() => useDemoPrep());

    await act(async () => {
      await result.current.startWarmup();
    });

    expect(result.current.stage).toBe("failed");
    expect(result.current.detail).toContain("backend offline");
    expect(result.current.busy).toBe(false);
  });

  it("reports a failure when the second sweep cannot start", async () => {
    const { result } = renderHook(() => useDemoPrep());

    await act(async () => {
      await result.current.startWarmup();
    });
    discoverySpy.mockRejectedValue(new Error("sweep engine down"));
    act(() => emit("discovery_sweep_completed"));

    await waitFor(() => expect(result.current.stage).toBe("failed"));
    expect(result.current.detail).toContain("sweep engine down");
  });

  it("starts no work until asked", async () => {
    // A readiness panel that resets the demo on open would be a trap.
    renderHook(() => useDemoPrep());
    await waitFor(() => expect(resetSpy).not.toHaveBeenCalled());
    expect(discoverySpy).not.toHaveBeenCalled();
  });
});
