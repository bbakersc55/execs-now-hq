import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { AppFeedModal } from "./ScorecardApp";
import { BestyFeedModal } from "./ScorecardBesty";
import { SheetFeedModal } from "./ScorecardFeed";
import { HubSpotFeedModal } from "./ScorecardHubSpot";
import { ConnectorRequestModal, RailFeedModal } from "./ScorecardRails";
import { ReviewsFeedModal } from "./ScorecardReviews";
import { TrackFeedModal } from "./ScorecardTrack";
import { Banner } from "./ui";
import { api } from "../lib/api";

/**
 * Where a KPI's number comes from, chosen in the scorecard setup's KPI form
 * (Bryan, 2026-11-18). The tile's details keep their own buttons; both open
 * the same settings, because the panels here are the tile's pop-ups drawn in
 * place (`inline`).
 */
export type SourceKind = "hand" | "sheet" | "app" | "track" | "hubspot" | "besty" | "reviews"
  | "webhook" | "mcp" | "api";

export const SOURCE_LABEL: Record<SourceKind, string> = {
  hand: "By hand", sheet: "Google Sheet", app: "This app", track: "Track PMS",
  hubspot: "HubSpot", besty: "Besty", reviews: "Google reviews", webhook: "Webhook",
  mcp: "Any MCP server", api: "Any API",
};

/** Where each feed is stopped, so "By hand" can stop the one that is on. */
const STOP: Record<Exclude<SourceKind, "hand">, string> = {
  sheet: "/api/scorecard/feeds/", app: "/api/scorecard/app-feed/",
  track: "/api/scorecard/track/feed/", hubspot: "/api/scorecard/hubspot/feed/",
  besty: "/api/scorecard/besty/feed/", reviews: "/api/scorecard/reviews/feed/",
  webhook: "/api/scorecard/rails/webhook/", mcp: "/api/scorecard/rails/mcp-feed/",
  api: "/api/scorecard/rails/api-feed/",
};

const RAILS: SourceKind[] = ["webhook", "mcp", "api"];

/** The sources a KPI may have, as the tile offers them: none for a computed
 *  KPI; a sheet only for a per-person one; this app for the practice's own
 *  scorecard and Track, HubSpot, Besty and Google reviews for a client's;
 *  the Command Center's recommended ones first. */
export function sourcesFor({ practice, computed, perPerson, recommended = [] }: {
  practice: boolean; computed: boolean; perPerson: boolean; recommended?: string[];
}): { connectors: SourceKind[]; rails: SourceKind[] } {
  if (computed) return { connectors: [], rails: [] };
  const plain = !perPerson;
  const all: SourceKind[] = ["sheet", ...(plain
    ? (practice ? ["app"] as SourceKind[] : ["track", "hubspot", "besty", "reviews"] as SourceKind[])
    : [])];
  const rank = (k: string) => (recommended.includes(k) ? recommended.indexOf(k) : recommended.length + 1);
  return { connectors: [...all].sort((a, b) => rank(a) - rank(b)), rails: plain ? RAILS : [] };
}

/** "From Google Sheet", for the setup list's line. */
export function sourceWords(kind: string | undefined | null): string {
  return !kind ? "by hand" : `from ${SOURCE_LABEL[kind as SourceKind] ?? kind}`;
}

/** The choice itself: a drop-down for the KPI form's grid. */
export function SourceSelect({ id, value, onChange, practice, computed, perPerson, recommended }: {
  id: string; value: SourceKind; onChange: (v: SourceKind) => void; practice: boolean;
  computed: boolean; perPerson: boolean; recommended?: string[];
}) {
  const { connectors, rails } = sourcesFor({ practice, computed, perPerson, recommended });
  const first = connectors.filter((k) => (recommended ?? []).includes(k));
  return (
    <label className="sc-form-field" htmlFor={id}><span>The number comes from</span>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value as SourceKind)}>
        <option value="hand">{SOURCE_LABEL.hand}</option>
        {connectors.length > 0 && (
          <optgroup label={first.length ? "Connectors (recommended first)" : "Connectors"}>
            {connectors.map((k) => <option key={k} value={k}>{SOURCE_LABEL[k]}</option>)}
          </optgroup>)}
        {rails.length > 0 && (
          <optgroup label="Connect anything">
            {rails.map((k) => <option key={k} value={k}>{SOURCE_LABEL[k]}</option>)}
          </optgroup>)}
      </select>
    </label>
  );
}

/**
 * The chosen source's settings, in place, for a KPI that exists. "By hand"
 * while a feed is on offers to stop it (its readings are kept, as when the
 * tile's settings stop it).
 */
export function SourcePanel({ companyId, kpiId, kpiName, chosen, current, owner, practiceName,
  onSaved, onCancel }: {
  companyId: string; kpiId: string; kpiName: string; chosen: SourceKind;
  /** The feed on now, if any. */
  current: SourceKind | null;
  /** The practice owner makes and removes rail connections. */
  owner: boolean;
  /** For "Request a connector": the client's name, "" on the practice's own. */
  practiceName: string;
  onSaved: (text: string) => void; onCancel: () => void;
}) {
  const qc = useQueryClient();
  const [requesting, setRequesting] = useState(false);
  const stop = useMutation({
    mutationFn: (kind: Exclude<SourceKind, "hand">) =>
      api.del(`${STOP[kind]}?company=${companyId}&kpi=${kpiId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scorecard", companyId] });
      qc.invalidateQueries({ queryKey: ["scorecard-setup", companyId] });
      onSaved(`${kpiName} is entered by hand again. Its readings are kept.`);
    },
  });
  const props = { companyId, kpiId, inline: true, onClose: onCancel, onSaved: (text: string) => {
    qc.invalidateQueries({ queryKey: ["scorecard-setup", companyId] });
    onSaved(text);
  } };
  const request = (
    <p className="small muted">
      Not listed?{" "}
      <button type="button" className="link small" onClick={() => setRequesting(true)}>
        Request a connector</button>
      {requesting && <ConnectorRequestModal clientName={practiceName}
        onClose={() => setRequesting(false)} />}
    </p>
  );
  if (chosen === "hand") {
    if (!current || current === "hand") return null;
    return (
      <section className="inline-panel" aria-label={`${kpiName}: by hand`}>
        <p className="small">{kpiName} reads from {SOURCE_LABEL[current]} now. Entered by hand, nobody's
          number is replaced and its readings so far are kept.</p>
        {stop.isError && <Banner kind="bad">{(stop.error as Error).message}</Banner>}
        <button type="button" className="small" disabled={stop.isPending}
          onClick={() => stop.mutate(current)}>Stop the {SOURCE_LABEL[current]} feed</button>
      </section>
    );
  }
  return (
    <div className="sc-source">
      {chosen === "sheet" && <SheetFeedModal {...props} />}
      {chosen === "app" && <AppFeedModal {...props} />}
      {chosen === "track" && <TrackFeedModal {...props} />}
      {chosen === "hubspot" && <HubSpotFeedModal {...props} />}
      {chosen === "besty" && <BestyFeedModal {...props} />}
      {chosen === "reviews" && <ReviewsFeedModal {...props} />}
      {RAILS.includes(chosen) && (
        <RailFeedModal key={chosen} companyId={companyId} kpiId={kpiId} kpiName={kpiName} inline
          kind={chosen as "webhook" | "mcp" | "api"} owner={owner} onClose={onCancel} />)}
      {request}
    </div>
  );
}
