/**
 * Screen G — MCP Access Log.
 *
 * Rows appear live as third parties call in. Selecting a role **refetches the
 * log through that role's redaction lens**, so the audience watches the
 * payload itself shrink rather than a caption change under unchanged data.
 *
 * Why there is no visibility table in this file
 * ---------------------------------------------
 * There used to be one, and it drifted: it advertised `legal` as seeing
 * account numbers, customer PII and transcripts when the server grants none of
 * the three, and listed `transcripts` as visible to `compliance` — the exact
 * disclosure the server was hardened to prevent. A second copy of an
 * access-control policy, in a language that cannot see the first, will drift
 * again. So this component holds no policy at all:
 *
 * - the withheld categories come from `row.redacted_fields`, computed
 *   server-side by `redacted_categories_for` for the role being read as;
 * - the role list comes from the API's `roles` key, `sorted(ROLE_VISIBILITY)`,
 *   which also makes an unrecognised `as_role` unsendable by construction;
 * - `McpRole` is a display hint and is deliberately not used here.
 *
 * Fail-closed rendering
 * ---------------------
 * When `redacted_fields` is absent the lens is *unknown*, not empty. Rendering
 * "nothing withheld" would be the one wrong answer, so an unknown lens is
 * labelled as least privilege — the same deny-by-default direction the server
 * takes for an unrecognised role.
 */

import { useMemo } from "react";
import { clockTime } from "../lib/format";
import type { McpLogRow } from "../types/api";

/**
 * Initial selection only — a starting lens, never an entitlement. The server
 * decides what `fraud_ops` may read; this just picks the option that shows the
 * unredacted payload first, so switching away from it makes the redaction
 * visible as a change.
 */
export const DEFAULT_LENS = "fraud_ops";

interface Props {
  entries: McpLogRow[];
  /** Authoritative role vocabulary from the API. */
  roles: string[];
  /** The lens currently applied server-side. */
  role: string;
  onRoleChange: (role: string) => void;
  /**
   * Calls observed via `mcp_call` whose audit write failed, and which are
   * therefore **absent from `entries`**. Counted by the container, because the
   * event is the only carrier of that fact — a row that was never written
   * cannot describe its own absence.
   */
  unrecorded?: number;
}

/**
 * The withheld-category list for the current lens, or `null` when unknown.
 *
 * Every row carries the same list when read through a lens, so the first row
 * that declares one speaks for the view. `null` means no row declared one —
 * the offline fixture, or a server too old to send the field.
 */
function lensOf(entries: McpLogRow[]): string[] | null {
  for (const row of entries) {
    if (Array.isArray(row.redacted_fields)) return row.redacted_fields;
  }
  return null;
}

/** Render `params` without the nulls a projected row leaves behind. */
function paramPairs(params: Record<string, unknown> | null): string[] {
  if (!params) return [];
  return Object.entries(params)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`);
}

export function McpAccessLog({
  entries,
  roles,
  role,
  onRoleChange,
  unrecorded = 0,
}: Props) {
  const lens = useMemo(() => lensOf(entries), [entries]);
  // Never render an empty selector: fall back to the current lens alone.
  const options = roles.length > 0 ? roles : [role];

  return (
    <div className="mcp" data-testid="mcp-access-log">
      <section className="panel">
        <div className="panel-title">
          MCP ACCESS LOG
          <span style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
            <span className="muted" style={{ letterSpacing: 0 }}>
              view as role
            </span>
            <select
              className="role-select"
              value={role}
              onChange={(e) => onRoleChange(e.target.value)}
              aria-label="role"
              data-testid="role-select"
            >
              {options.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </span>
        </div>

        <div className="diff-summary" data-testid="redaction-summary">
          {lens === null ? (
            <span className="redacted">
              redaction lens unavailable — assuming least privilege
            </span>
          ) : lens.length === 0 ? (
            <>
              <span className="add">full visibility</span>
              <span className="muted"> · nothing withheld from this role</span>
            </>
          ) : (
            <>
              withheld from {role}:{" "}
              {lens.map((f) => (
                <span key={f} className="redacted" style={{ marginRight: 8 }}>
                  {f}
                </span>
              ))}
            </>
          )}
        </div>

        {unrecorded > 0 && (
          <div className="diff-summary" data-testid="audit-gap-warning">
            <span className="redacted">
              ⚠ {unrecorded} call{unrecorded === 1 ? "" : "s"} not recorded —
              audit write failed, so {unrecorded === 1 ? "it is" : "they are"}{" "}
              missing from the log below
            </span>
          </div>
        )}

        <div className="panel-body flush">
          {entries.length === 0 ? (
            <p className="ticker-empty">
              no MCP calls yet — this fills when an external agent queries TranSafe
            </p>
          ) : (
            entries.map((row) => {
              const pairs = paramPairs(row.params);
              // `citation_count` is set by `project_log_entry` and by nothing
              // else, so it is the honest discriminator between "this row was
              // read through a lens" and "this call simply had no params".
              // Without it `params: {}` (no arguments) and `params:
              // {outcome: null}` (arguments withheld) render identically.
              const projected = row.citation_count !== undefined;
              // A lens that withholds nothing (fraud_ops) is still projected,
              // so "projected" alone would wrongly claim its params were cut.
              // An unknown lens counts as withholding — fail closed.
              const fullLens =
                Array.isArray(row.redacted_fields) && row.redacted_fields.length === 0;
              const paramsWithheld = projected && !fullLens;
              const withheldCitations = paramsWithheld && (row.citation_count ?? 0) > 0;

              return (
                <div className="mcp-row" key={row.id} data-testid="mcp-row">
                  <span className="muted">{clockTime(row.ts)}</span>
                  <span className="caller">{row.caller}</span>
                  <span className="role">{row.role}</span>
                  <span className="detail">
                    {row.tool}
                    {pairs.length > 0 && (
                      <span className="muted"> {pairs.join(" ")}</span>
                    )}
                    {paramsWithheld && (
                      <span className="redacted"> [params withheld]</span>
                    )}
                    {row.citations && row.citations.length > 0 && (
                      <span style={{ color: "var(--green)" }}>
                        {" "}
                        ↳ cited {row.citations.join(", ")}
                      </span>
                    )}
                    {withheldCitations && (
                      <span className="redacted">
                        {" "}
                        ↳ {row.citation_count} citation
                        {row.citation_count === 1 ? "" : "s"} withheld
                      </span>
                    )}
                  </span>
                  <span className="lat">{row.latency_ms ?? "—"}ms</span>
                </div>
              );
            })
          )}
        </div>
      </section>
    </div>
  );
}

export default McpAccessLog;
