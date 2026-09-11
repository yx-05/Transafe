/**
 * Tests for the demo warm-up chain.
 *
 * The rule being protected is the one an operator otherwise has to remember:
 * **discovery must run twice.** The first sweep does not promote. Encoding it
 * here means a future change that breaks the chain fails a test rather than
 * failing on stage.
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
    act(() => emit("discovery_sweep_completed"));
    await waitFor(() => expect(result.current.stage).toBe("sweeping2"));

    act(() => emit("campaign_proposed", "compiler"));

    expect(result.current.stage).toBe("ready");
    expect(result.current.busy).toBe(false);
  });

  it("ignores a candidate proposed before the second sweep", async () => {
    // A campaign left over from a previous run must not report the warm-up as
    // finished before the sweep it is waiting for has even started.
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
