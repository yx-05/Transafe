import { useCallback, useEffect, useState } from "react";
import EvalScreen from "../components/EvalScreen";
import { api } from "../services/api";
import { useEventSubscription } from "../hooks/useEventSubscription";
import type { EvalComparison } from "../types/api";

const EMPTY: EvalComparison = { before: null, after: null };

export function EvalPage() {
  const [comparison, setComparison] = useState<EvalComparison>(EMPTY);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    setComparison(await api.getLatestEval());
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Results refresh when the harness emits eval_completed — never on a poll.
  useEventSubscription(
    () => {
      void load().finally(() => setRunning(false));
    },
    { eventTypes: ["eval_completed"] },
  );

  return (
    <EvalScreen
      comparison={comparison}
      running={running}
      onRun={async () => {
        setRunning(true);
        try {
          await api.runEval();
          await load();
        } finally {
          setRunning(false);
        }
      }}
    />
  );
}

export default EvalPage;
