import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import CaseDetail from "../components/CaseDetail";
import StatusBadge from "../components/StatusBadge";
import { api } from "../services/api";
import { useCampaignStore } from "../store/useCampaignStore";
import { useEventSubscription } from "../hooks/useEventSubscription";
import type { CaseDetail as CaseDetailModel } from "../types/campaign";

export function CaseDetailPage() {
  const { caseId } = useParams();
  const navigate = useNavigate();
  const cases = useCampaignStore((s) => s.cases);
  const loadCases = useCampaignStore((s) => s.loadCases);
  const [detail, setDetail] = useState<CaseDetailModel | null>(null);
  const [casesLoaded, setCasesLoaded] = useState(false);

  useEffect(() => {
    void loadCases().finally(() => setCasesLoaded(true));
  }, [loadCases]);

  // A new case arriving is a real event, so refresh the list — not on a timer.
  useEventSubscription(
    () => {
      void loadCases();
    },
    { eventTypes: ["case_ingested"] },
  );

  useEffect(() => {
    if (!caseId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    void api.getCase(caseId).then((d) => {
      if (!cancelled) setDetail(d);
    });
    return () => {
      cancelled = true;
    };
  }, [caseId]);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div className="case-picker">
        {cases.length === 0 && (
          // Zero cases is a real answer once the request has returned; don't
          // leave a "loading" label sitting there forever.
          <span className="muted mono">
            {casesLoaded ? "no cases ingested yet" : "loading cases…"}
          </span>
        )}
        {cases.map((c) => (
          <button
            type="button"
            key={c.id}
            className={`btn ${c.id === caseId ? "btn-primary" : ""}`}
            onClick={() => navigate(`/cases/${c.id}`)}
          >
            #{c.case_number} <StatusBadge label={c.risk_label} />
          </button>
        ))}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
        {detail ? (
          <CaseDetail detail={detail} />
        ) : (
          <p className="empty-state">select a case to open its living record</p>
        )}
      </div>
    </div>
  );
}

export default CaseDetailPage;
