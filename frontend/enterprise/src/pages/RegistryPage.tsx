import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import ArtifactRegistry, { type RegistryTab } from "../components/ArtifactRegistry";
import { api } from "../services/api";
import { useEventSubscription } from "../hooks/useEventSubscription";
import type { ArtifactDetail, ArtifactGroup } from "../types/campaign";

export function RegistryPage() {
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState<RegistryTab>(
    (params.get("tier") as RegistryTab | null) ?? "core",
  );
  const [groups, setGroups] = useState<ArtifactGroup[]>([]);
  const [detail, setDetail] = useState<ArtifactDetail | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const res = await api.getArtifacts();
    setGroups(res.artifacts);
    return res.artifacts;
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // The registry updates when the compiler actually published something.
  useEventSubscription(
    () => {
      void load();
    },
    { layers: ["compiler", "registry"] },
  );

  const select = useCallback(async (name: string, version: number) => {
    setDetail(await api.getArtifact(name, version));
  }, []);

  // Deep link from the validation console: /registry?artifact=…&version=…
  useEffect(() => {
    const name = params.get("artifact");
    if (!name) return;
    const version = Number(params.get("version"));
    void select(name, Number.isFinite(version) && version > 0 ? version : 1);
  }, [params, select]);

  // Default selection: latest version of the first group in the tab.
  useEffect(() => {
    if (detail || params.get("artifact")) return;
    const first = groups.find((g) => g.tier === tab);
    if (first) void select(first.name, first.latest_version);
  }, [groups, tab, detail, params, select]);

  return (
    <ArtifactRegistry
      groups={groups}
      activeTab={tab}
      onTabChange={(next) => {
        setTab(next);
        setDetail(null);
        setParams({ tier: next });
      }}
      detail={detail}
      onSelect={(name, version) => void select(name, version)}
      busy={busy}
      onRollback={async (name, version) => {
        setBusy(true);
        try {
          await api.rollbackArtifact(name, version);
          await load();
          await select(name, version);
        } finally {
          setBusy(false);
        }
      }}
    />
  );
}

export default RegistryPage;
