import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ValidationConsole from "../components/ValidationConsole";
import StatusBadge from "../components/StatusBadge";
import { useCampaignStore } from "../store/useCampaignStore";
import { useEventSubscription } from "../hooks/useEventSubscription";
import { api } from "../services/api";

export function ValidationPage() {
  const { campaignId } = useParams();
  const navigate = useNavigate();
  const campaigns = useCampaignStore((s) => s.campaigns);
  const selected = useCampaignStore((s) => s.selectedCampaign);
  const loadCampaigns = useCampaignStore((s) => s.loadCampaigns);
  const loadCampaign = useCampaignStore((s) => s.loadCampaign);
  const approve = useCampaignStore((s) => s.approve);
  const reject = useCampaignStore((s) => s.reject);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void loadCampaigns();
  }, [loadCampaigns]);

  useEventSubscription(
    () => {
      void loadCampaigns();
    },
    { eventTypes: ["campaign_proposed", "campaign_approved", "campaign_rejected"] },
  );

  useEffect(() => {
    const id = campaignId ?? campaigns.find((c) => c.status === "CANDIDATE")?.id;
    if (id) void loadCampaign(id);
  }, [campaignId, campaigns, loadCampaign]);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div className="case-picker">
        {campaigns.map((c) => (
          <button
            type="button"
            key={c.id}
            className={`btn ${c.id === (campaignId ?? selected?.id) ? "btn-primary" : ""}`}
            onClick={() => navigate(`/validation/${c.id}`)}
          >
            {c.code} <StatusBadge label={c.status} />
          </button>
        ))}
        {campaigns.length === 0 && <span className="muted mono">no campaigns yet</span>}
      </div>

      <div style={{ flex: 1, minHeight: 0 }}>
        {selected ? (
          <ValidationConsole
            campaign={selected}
            busy={busy}
            onApprove={async (id) => {
              setBusy(true);
              try {
                await approve(id);
              } finally {
                setBusy(false);
              }
            }}
            onReject={async (id, reason) => {
              setBusy(true);
              try {
                await reject(id, reason);
              } finally {
                setBusy(false);
              }
            }}
            onEdit={async (id, edits) => {
              await api.editCampaign(id, edits);
              await loadCampaign(id);
            }}
            onViewDiff={(name, version) =>
              navigate(`/registry?artifact=${encodeURIComponent(name)}&version=${version}`)
            }
          />
        ) : (
          <p className="empty-state">no campaign selected</p>
        )}
      </div>
    </div>
  );
}

export default ValidationPage;
