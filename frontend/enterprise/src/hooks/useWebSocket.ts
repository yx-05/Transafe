import { useEffect } from "react";
import { useEventStore } from "../store/useEventStore";
import { defaultWsUrl } from "../services/eventSource";

/**
 * Opens the LIVE event stream for the lifetime of the component.
 * REPLAY mode is entered via the shell's mode switch, which calls
 * `useEventStore.activate("REPLAY", …)` and tears this connection down.
 */
export function useWebSocket(url: string = defaultWsUrl()): boolean {
  const isConnected = useEventStore((s) => s.isConnected);
  const mode = useEventStore((s) => s.mode);

  useEffect(() => {
    if (mode !== "LIVE") return;
    const { connect, disconnect } = useEventStore.getState();
    connect(url);
    return () => disconnect();
  }, [url, mode]);

  return isConnected;
}

export default useWebSocket;
