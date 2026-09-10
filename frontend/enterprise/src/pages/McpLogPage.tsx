import { useCallback, useEffect, useState } from "react";
import McpAccessLog, { DEFAULT_LENS } from "../components/McpAccessLog";
import { api } from "../services/api";
import { useEventSubscription } from "../hooks/useEventSubscription";
import type { McpLogRow } from "../types/api";

/**
 * Screen G container.
 *
 * Owns the redaction lens because it owns the fetch: changing the role is a
 * server round-trip, not a local re-render. The role selector previously lived
 * in the component and never refetched, so the console always displayed the
 * unprojected operator payload no matter which role was chosen.
 */
export function McpLogPage() {
  const [entries, setEntries] = useState<McpLogRow[]>([]);
  const [roles, setRoles] = useState<string[]>([]);
  const [role, setRole] = useState<string>(DEFAULT_LENS);
  const [unrecorded, setUnrecorded] = useState(0);

  const load = useCallback(async () => {
    const res = await api.getMcpLog(role);
    setEntries(res.entries);
    // Authoritative role vocabulary. Keep the last good list if a response
    // omits it, so the selector never empties mid-demo.
    if (res.roles?.length) setRoles(res.roles);
  }, [role]);

  useEffect(() => {
    void load();
  }, [load]);

  // A row appears because an mcp_call event fired. No polling.
  //
  // The event is also the *only* place a lost audit row is observable. When
  // `log_mcp_access` fails, the server still emits the event (suppressing it
  // would make the access itself unobservable) but no row reaches
  // `mcp_access_log` — so the refetch below returns a log that simply does not
  // contain that call. Without the counter, an audit failure would present as
  // a refresh that changes nothing: the event reporting the loss would trigger
  // the fetch that hides it.
  //
  // Three states, deliberately, and `undefined` is not `false`:
  //   true      — row written, nothing to say
  //   false     — row lost, this call is missing from the table below
  //   undefined — event predates the `audit_persisted` field and carries no
  //               claim either way. Counting it as a failure would make the
  //               console retroactively accuse every correctly-audited call in
  //               its own history.
  useEventSubscription(
    (event) => {
      const persisted = (event.payload as { audit_persisted?: unknown })
        .audit_persisted;
      if (persisted === false) setUnrecorded((n) => n + 1);
      void load();
    },
    { eventTypes: ["mcp_call"] },
  );

  return (
    <McpAccessLog
      entries={entries}
      roles={roles}
      role={role}
      onRoleChange={setRole}
      unrecorded={unrecorded}
    />
  );
}

export default McpLogPage;
