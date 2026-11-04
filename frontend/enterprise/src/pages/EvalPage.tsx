import { useCallback, useEffect, useState } from "react";
import EvalScreen from "../components/EvalScreen";
import { api } from "../services/api";
import { useEventSubscription } from "../hooks/useEventSubscription";
import type { EvalComparison, RedteamCorpus } from "../types/api";

const EMPTY: EvalComparison = { before: null, after: null };

export function EvalPage() {
  const [comparison, setComparison] = useState<EvalComparison>(EMPTY);
  const [redteam, setRedteam] = useState<RedteamCorpus | null>(null);
  const [running, setRunning] = useState(false);
  const [adapting, setAdapting] = useState(false);

  const load = useCallback(async () => {
    const [comparisonPayload, redteamPayload] = await Promise.all([
      api.getLatestEval(),
      api.getRedteamCorpus(),
    ]);
    setComparison(comparisonPayload);
    setRedteam(redteamPayload);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Results refresh when the harness emits eval_completed — never on a poll.
  // One adaptation cycle emits it twice (before and after), and the second
  // refresh is what reveals the jump, so both `running` flags clear on either.
  //
  // `demo_reset` belongs here too: a reset purges eval_runs. Without it, a reset
  // made while this screen is open leaves the previous run's bars on screen, so
  // the chart contradicts the pipeline — precisely what this screen is supposed
  // to be trustworthy about.
  useEventSubscription(
    () => {
      void load().finally(() => {
        setRunning(false);
        setAdapting(false);
      });
    },
    { eventTypes: ["eval_completed", "demo_reset"] },
  );

  return (
    <EvalScreen
      comparison={comparison}
      redteam={redteam}
      running={running}
      adapting={adapting}
      onRun={async () => {
        setRunning(true);
        try {
          await api.runEval();
          await load();
        } finally {
          setRunning(false);
        }
      }}
      onAdapt={async () => {
        setAdapting(true);
        try {
          // Slower than a plain run: it scores the corpus twice and publishes
          // an artifact in between. The subscription above still clears the
          // flag if the response is what arrives last.
          await api.runAdaptation();
          await load();
        } finally {
          setAdapting(false);
        }
      }}
    />
  );
}

export default EvalPage;
