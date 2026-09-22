import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Check, FileText, FolderSync, RefreshCw, X } from "lucide-react";

import { PageHead } from "../components/shell";
import { Banner, Card, Empty, Field, Pill, when } from "../components/ui";
import { Me, MeetingProposal, ProposalItem, api } from "../lib/api";

/**
 * Module 5 — the review queue (PRD §7).
 *
 * **The whole module is a review queue with a parser in front of it.** Nothing
 * on this screen has happened yet: every row is something Claude proposed, and
 * the buttons are a person deciding. Each item carries the passage of the
 * document it came from, so a reviewer can check the claim rather than trust
 * it (FR-5.14).
 */
export function Meetings({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const health = useQuery<{ connected: boolean; folder_id: string; last_polled_at: string | null;
                            last_error: string; files_pending: number; files_failed: number;
                            files_skipped: number }>({
    queryKey: ["drive-watch"], queryFn: () => api.get("/api/drive-watch/"),
  });
  const proposals = useQuery<MeetingProposal[]>({
    queryKey: ["meeting-proposals"],
    queryFn: () => api.get<MeetingProposal[]>("/api/meeting-proposals/"),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["meeting-proposals"] });
    qc.invalidateQueries({ queryKey: ["drive-watch"] });
    qc.invalidateQueries({ queryKey: ["meeting-proposal"] });
  };
  const sync = useMutation({
    mutationFn: () => api.post<{ recorded: number; skipped: unknown[]; error: string }>(
      "/api/drive-watch/sync/"),
    onSuccess: (result) => {
      setNote(result.error
        ? `Drive said: ${result.error}. The cursor has not moved; it will try again.`
        : `Read ${result.recorded} new file${result.recorded === 1 ? "" : "s"}.`);
      refresh();
    },
    onError: (e: Error) => setNote(e.message),
  });

  const rows = proposals.data ?? [];
  return (
    <>
      <PageHead title="Meeting queue"
        sub="What Claude read in your notes folder, waiting for you. Nothing here
             has been created — approving is what creates it."
        action={
          <button className="primary" disabled={sync.isPending}
            onClick={() => sync.mutate()}>
            <FolderSync size={16} /> {sync.isPending ? "Reading…" : "Sync now"}
          </button>
        } />

      {note && <Banner kind="info">{note}</Banner>}
      {health.data && !health.data.connected && (
        <Banner kind="warn">
          No folder is connected yet. Paste the folder's id from its Drive URL
          on the settings screen to start watching it.
        </Banner>
      )}
      {health.data?.last_error && (
        <Banner kind="bad">{health.data.last_error}</Banner>
      )}
      {health.data?.connected && (
        <p className="small muted">
          Last looked {health.data.last_polled_at ? when(health.data.last_polled_at) : "never"}
          {" · "}{health.data.files_pending} waiting
          {health.data.files_failed > 0 && ` · ${health.data.files_failed} failed`}
          {health.data.files_skipped > 0 && ` · ${health.data.files_skipped} skipped`}
        </p>
      )}

      {rows.length === 0 && (
        <Empty>Nothing waiting. New notes appear here within ten minutes.</Empty>
      )}
      {rows.map((proposal) => (
        <Card key={proposal.id} title={proposal.title || proposal.source_file.name}
          actions={
            <span className="inline">
              <Pill>{proposal.counts.pending} to review</Pill>
              <button className="small" onClick={() =>
                setOpen(open === proposal.id ? null : proposal.id)}>
                {open === proposal.id ? "Close" : "Review"}
              </button>
            </span>
          }>
          <p className="small muted">
            {proposal.meeting_date ?? "no date in the notes"}
            {" · "}<FileText size={12} /> {proposal.source_file.name}
            {proposal.counts.approved > 0 && ` · ${proposal.counts.approved} approved`}
            {proposal.counts.rejected > 0 && ` · ${proposal.counts.rejected} rejected`}
          </p>
          {open === proposal.id && (
            <ProposalDetail id={proposal.id} onChanged={refresh} setNote={setNote}
              me={me} />
          )}
        </Card>
      ))}
    </>
  );
}

function ProposalDetail({ id, onChanged, setNote }: {
  id: string; onChanged: () => void; setNote: (text: string) => void; me: Me;
}) {
  const detail = useQuery<MeetingProposal>({
    queryKey: ["meeting-proposal", id],
    queryFn: () => api.get<MeetingProposal>(`/api/meeting-proposals/${id}/`),
  });
  const [summary, setSummary] = useState<string | null>(null);
  const saveSummary = useMutation({
    mutationFn: (body: object) => api.patch(`/api/meeting-proposals/${id}/`, body),
    onSuccess: () => onChanged(),
  });
  const reparse = useMutation({
    mutationFn: () => api.post(`/api/meeting-proposals/${id}/reparse/`),
    onSuccess: () => { setNote("Read again. Anything you had already approved stands.");
                       onChanged(); },
    onError: (e: Error) => setNote(e.message),
  });

  if (!detail.data) return <p className="small muted">Opening…</p>;
  const proposal = detail.data;
  const items = proposal.items ?? [];
  const of = (kind: ProposalItem["kind"]) => items.filter((i) => i.kind === kind);

  return (
    <div style={{ marginTop: "var(--s3)" }}>
      {/* R11a — the drafted summary is reviewed with the proposal: editable
          before approval, and discardable, in which case the meeting is
          created with none. */}
      {/* `??` alone would keep `summary`'s empty string — its initial state —
          and the drafted summary would never appear. */}
      <Field label="The meeting summary — yours to edit or discard">
        <textarea aria-label="Meeting summary" rows={4}
          value={summary ?? (proposal.summary || proposal.proposed_summary)}
          onChange={(e) => setSummary(e.target.value)}
          onBlur={() => summary !== null && saveSummary.mutate({ summary })} />
      </Field>
      <div className="row tight">
        <button className="small" onClick={() =>
          saveSummary.mutate({ summary_discarded: !proposal.summary_discarded })}>
          {proposal.summary_discarded ? "Keep a summary after all" : "Discard the summary"}
        </button>
        <button className="small" disabled={reparse.isPending}
          onClick={() => reparse.mutate()}>
          <RefreshCw size={14} /> Read it again
        </button>
      </div>

      {(["participant", "action_item", "deliverable"] as const).map((kind) => (
        of(kind).length > 0 && (
          <div key={kind} style={{ marginTop: "var(--s4)" }}>
            <h4>{kind === "participant" ? "Who was there"
              : kind === "action_item" ? "What was agreed" : "What was promised"}</h4>
            {of(kind).map((item) => (
              <ItemRow key={item.id} item={item} onChanged={onChanged}
                setNote={setNote} />
            ))}
          </div>
        )
      ))}
    </div>
  );
}

/** One proposed thing. Approve or reject on its own — partial approval is the
 *  normal outcome, not an edge case (FR-5.15). */
function ItemRow({ item, onChanged, setNote }: {
  item: ProposalItem; onChanged: () => void; setNote: (text: string) => void;
}) {
  const payload = item.payload ?? {};
  const [type, setType] = useState<string>(payload.proposed_contact_type ?? "prospect");
  const [pick, setPick] = useState<string>("");
  const [categories, setCategories] = useState("");

  const act = useMutation({
    mutationFn: ({ verb, body }: { verb: string; body?: object }) =>
      api.post(`/api/proposal-items/${item.id}/${verb}/`, body),
    onSuccess: () => onChanged(),
    onError: (e: Error) => setNote(e.message),
  });

  const decided = item.state !== "pending";
  return (
    <div className="card" style={{ opacity: decided ? 0.6 : 1 }}>
      <div className="spread" style={{ alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{ margin: 0, fontWeight: 550 }}>
            {item.kind === "participant"
              ? `${payload.parsed_name}${payload.parsed_email ? ` · ${payload.parsed_email}` : ""}`
              : payload.text}
          </p>
          {/* FR-5.14 — what it was drawn from, so the claim is checkable. */}
          {item.source_excerpt && (
            <p className="tiny muted" style={{ margin: "2px 0 0", fontStyle: "italic" }}>
              “{item.source_excerpt}”
            </p>
          )}
        </div>
        {decided && <Pill kind={item.state === "approved" ? "ok" : ""}>{item.state}</Pill>}
      </div>

      {!decided && item.kind === "participant" && (
        <div className="row" style={{ marginTop: "var(--s2)" }}>
          <Field label="Who is this">
            <select aria-label={`Match for ${payload.parsed_name}`} value={pick}
              onChange={(e) => setPick(e.target.value)}>
              <option value="">Someone new — create them</option>
              {(payload.existing_candidates ?? []).map((row) => (
                <option key={row.contact_id} value={row.contact_id}>
                  {row.name}{row.company ? ` · ${row.company}` : ""} — matched on{" "}
                  {row.match_reason.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </Field>
          <Field label="What they are to us">
            <select aria-label={`Type for ${payload.parsed_name}`} value={type}
              onChange={(e) => setType(e.target.value)}>
              <option value="prospect">Prospect</option>
              <option value="client">Client</option>
              <option value="referral_partner">Referral partner</option>
              <option value="vendor">Vendor</option>
              <option value="coworker">Coworker</option>
            </select>
          </Field>
          {type === "vendor" && (
            <Field label="What they do — comma separated">
              <input aria-label={`Service categories for ${payload.parsed_name}`}
                value={categories} placeholder="Duct cleaning, grease traps"
                onChange={(e) => setCategories(e.target.value)} />
            </Field>
          )}
        </div>
      )}

      {!decided && (
        <div className="row tight" style={{ marginTop: "var(--s2)" }}>
          <button className="primary small" disabled={act.isPending}
            aria-label={`Approve ${payload.parsed_name ?? payload.text}`}
            onClick={() => act.mutate({ verb: "approve", body: {
              ...(item.kind === "participant"
                ? { contact_id: pick, contact_type: type,
                    service_categories: categories.split(",").map((c) => c.trim())
                      .filter(Boolean) }
                : {}),
            } })}>
            <Check size={14} /> Approve
          </button>
          <button className="small danger" disabled={act.isPending}
            aria-label={`Reject ${payload.parsed_name ?? payload.text}`}
            onClick={() => act.mutate({ verb: "reject" })}>
            <X size={14} /> Reject
          </button>
        </div>
      )}
    </div>
  );
}
