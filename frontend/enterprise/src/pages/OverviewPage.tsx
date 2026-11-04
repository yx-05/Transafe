/** Screen A — the presentation screen. */

import { useEffect } from "react";
import LiveEventFeed from "../components/LiveEventFeed";
import NervousSystem from "../components/NervousSystem";
import MetricBar from "../components/MetricBar";
import { useCampaignStore } from "../store/useCampaignStore";

export function OverviewPage() {
  const overview = useCampaignStore((s) => s.overview);
  const loadOverview = useCampaignStore((s) => s.loadOverview);

  useEffect(() => {
    if (!overview) void loadOverview();
  }, [overview, loadOverview]);

  return (
    <div className="overview" data-testid="overview-page">
      <LiveEventFeed />
      <NervousSystem />
      <MetricBar metrics={overview?.metrics ?? []} />
    </div>
  );
}

export default OverviewPage;
