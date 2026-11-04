import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import ScamGraph from "../components/ScamGraph";
import { api } from "../services/api";
import { useEventSubscription } from "../hooks/useEventSubscription";
import type { GraphData } from "../types/campaign";

const EMPTY: GraphData = { nodes: [], links: [], hulls: [] };

export function GraphPage() {
  const [data, setData] = useState<GraphData>(EMPTY);
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const focus = params.get("focus");

  const load = useCallback(async () => {
    setData(await api.getGraph());
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // The graph grows because the system linked something, not because of a poll.
  useEventSubscription(
    () => {
      void load();
    },
    {
      eventTypes: [
        "case_ingested",
        "entity_linked",
        "case_linked",
        "cluster_formed",
        "campaign_proposed",
        "campaign_approved",
      ],
    },
  );

  return (
    <ScamGraph
      data={data}
      focusId={focus}
      onSelectCase={(id) => navigate(`/cases/${id}`)}
    />
  );
}

export default GraphPage;
