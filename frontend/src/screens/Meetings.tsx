import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  Check, EyeOff, FileText, FolderOpen, FolderSync, Link2, RefreshCw, X,
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

import { PageHead } from "../components/shell";
import { Banner, Card, Empty, Field, Pill, when } from "../components/ui";
import {
  Backfill, BackfillPlan, DismissReason, DriveFolder, DriveHealth, FolderPast, Me,
  MeetingProposal, WatchFolder, asksToConfirm,
  ProposalItem, api,
} from "../lib/api";

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

  const [params, setParams] = useSearchParams();
  const [problem, setProblem] = useState("");

  // The Drive consent is a browser redirect, so its outcome comes back in the
  // query string rather than as a response we could have awaited.
  useEffect(() => {
    const connected = params.get("drive_connected");
    const failed = params.get("drive_error") || params.get("drive_warning");
    if (connected) setNote(`Drive access granted for ${connected}. Now choose the folder.`);
    if (failed) setProblem(failed);
    if (connected || failed) {
      setParams({}, { replace: true });
      qc.invalidateQueries({ queryKey: ["drive-watch"] });
    }
  }, [params, setParams, qc]);

  const health = useQuery<DriveHealth>({
    queryKey: ["drive-watch"], queryFn: () => api.get("/api/drive-watch/"),
    // While the folder is being imported this screen is a progress bar, so it
    // has to move. Otherwise it is a static header and polling it is waste.
    refetchInterval: (query) =>
      query.state.data?.backfill?.running ? 15_000 : false,
  });
  // Same key as the panel below, so react-query serves both from one call.
  // The folder card needs the number to say what is *not* being read.
  const past = useQuery<{ folder: FolderPast; backfill: Backfill | null }>({
    queryKey: ["drive-backfill"],
    queryFn: () => api.get("/api/drive-watch/backfill/"),
    enabled: me.role === "FF" && !!health.data?.connected
             && !health.data?.backfill?.running,
  });
  // Open is the queue; Archived is what was dismissed, and where that is undone.
  const [view, setView] = useState<"open" | "archived">("open");
  const proposals = useQuery<MeetingProposal[]>({
    queryKey: ["meeting-proposals", view],
    queryFn: () => api.get<MeetingProposal[]>(
      view === "archived" ? "/api/meeting-proposals/?state=archived"
                          : "/api/meeting-proposals/"),
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
      {problem && <Banner kind="bad">{problem}</Banner>}
      {health.data && (
        <Folder health={health.data} me={me} refresh={refresh}
          setNote={setNote} setProblem={setProblem}
          unread={past.data?.folder.outstanding ?? 0} />
      )}
      {health.data?.connected && me.role === "FF" && (
        <>
          <Past health={health.data} folder={null} setProblem={setProblem} />
          {(health.data.folders ?? []).map((folder) => (
            <Past key={folder.id} health={health.data!} folder={folder}
              setProblem={setProblem} />
          ))}
        </>
      )}

      <div className="row tight" role="group" aria-label="Which proposals"
        style={{ marginBottom: "var(--s3)" }}>
        {(["open", "archived"] as const).map((which) => (
          <button key={which} className={view === which ? "primary small" : "ghost small"}
            aria-pressed={view === which} onClick={() => { setView(which); setOpen(null); }}>
            {which === "open" ? "Open" : "Archived"}
          </button>
        ))}
      </div>

      {view === "archived" ? (
        <Archived rows={rows} onChanged={refresh} setNote={setNote} />
      ) : rows.length === 0 ? (
        <Empty>Nothing waiting. New notes appear here within ten minutes.</Empty>
      ) : null}
      {view === "open" && rows.map((proposal) => (
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

/**
 * The folder behind the queue: connecting it, and its health once connected
 * (FR-5.1, FR-5.1a).
 *
 * **Connecting has two steps that fail separately**, so the screen shows two.
 * Granting the app `drive.readonly` on the founder's Google account is one
 * thing; pointing it at a folder is another, and an FF who has done the first
 * and not the second is in a different position from one who has done
 * neither. Folding both into a single "Connect" button would leave the screen
 * unable to say which half is missing — which is exactly the state this panel
 * was built to end.
 *
 * Only the FF connects (matrix 11.10). Everyone else sees where the folder has
 * got to, because a CF or VA clearing this queue still needs to know whether
 * it is empty or merely asleep.
 */
function Folder({ health, me, refresh, setNote, setProblem, unread = 0 }: {
  health: DriveHealth; me: Me; refresh: () => void;
  setNote: (text: string) => void; setProblem: (text: string) => void;
  unread?: number;
}) {
  const qc = useQueryClient();
  const [pasted, setPasted] = useState("");
  const [found, setFound] = useState<DriveFolder | null>(null);
  const mine = me.role === "FF";

  const consent = useMutation({
    mutationFn: () => api.post<{ authorization_url: string }>("/api/drive-watch/consent/"),
    // Google's consent screen, not ours: we hand the browser the URL and get
    // the answer back on the redirect.
    onSuccess: (data) => { window.location.href = data.authorization_url; },
    onError: (e: Error) => setProblem(e.message),
  });

  const check = useMutation({
    mutationFn: () => api.post<DriveFolder>("/api/drive-watch/check/", { folder: pasted }),
    onSuccess: (data) => { setFound(data); setProblem(""); },
    onError: (e: Error) => { setFound(null); setProblem(e.message); },
  });

  const connect = useMutation({
    mutationFn: () => api.post<DriveHealth>("/api/drive-watch/", { folder: pasted }),
    onSuccess: (data) => {
      qc.setQueryData(["drive-watch"], data);
      setFound(null);
      setPasted("");
      setProblem("");
      setNote(`Watching “${data.folder_name || data.folder_id}”. `
        + "Sync now to read what is already in it.");
      refresh();
    },
    onError: (e: Error) => setProblem(e.message),
  });

  const disconnect = useMutation({
    mutationFn: () => api.post<DriveHealth>("/api/drive-watch/disconnect/"),
    onSuccess: (data) => {
      qc.setQueryData(["drive-watch"], data);
      setNote("Stopped watching. Everything already read stays in the queue, "
        + "and reconnecting the same folder picks up where it left off.");
      setProblem("");
      refresh();
    },
    onError: (e: Error) => setProblem(e.message),
  });

  if (health.connected) {
    return (
      <>
      <Card title={health.folder_name || health.folder_id}
        actions={mine && (
          <button className="small" disabled={disconnect.isPending}
            onClick={() => disconnect.mutate()}>Disconnect</button>
        )}>
        <p className="small muted">
          <FolderOpen size={12} /> Watched folder
          {" · "}last looked {health.last_polled_at ? when(health.last_polled_at) : "never"}
          {" · "}{health.files_pending} waiting
          {health.files_failed > 0 && ` · ${health.files_failed} failed`}
          {health.files_skipped > 0 && ` · ${health.files_skipped} skipped`}
          {(health.excluded ?? 0) > 0 && ` · ${health.excluded} excluded`}
        </p>
        {unread > 0 && (
          <p className="small">
            Watching for new notes; <strong>{unread} older note
            {unread === 1 ? "" : "s"} not imported</strong> — import them below.
          </p>
        )}
        {health.last_error && <Banner kind="bad">{health.last_error}</Banner>}
        {!health.drive_access && (
          <Banner kind="bad">
            The connected Google account no longer has Drive access, so this
            folder cannot be read.
            {mine && <> <button className="link" disabled={consent.isPending}
              onClick={() => consent.mutate()}>Allow Drive access again</button>.</>}
          </Banner>
        )}
      </Card>
      {(health.folders ?? []).map((folder) => (
        <ExtraFolder key={folder.id} folder={folder} mine={mine} setProblem={setProblem} />
      ))}
      {mine && <AddFolder setNote={setNote} setProblem={setProblem} />}
      <Exclusions health={health} mine={mine} setProblem={setProblem} />
      </>
    );
  }

  if (!mine) {
    return (
      <Banner kind="warn">
        No notes folder is connected yet, so nothing is being read. The founder
        fractional connects it.
      </Banner>
    );
  }

  return (
    <Card title="Connect your notes folder">
      <p className="small muted">
        Two steps, once. After this the folder is checked every ten minutes and
        everything found lands here for you to approve.
      </p>

      <div className="connect-step">
        <h4>1. Let the app read your Drive</h4>
        {!health.google_connected ? (
          <p className="small">
            Connect your Google account first, on{" "}
            <Link to="/settings/email">Email settings</Link>.
          </p>
        ) : health.drive_access ? (
          <p className="small granted">
            <Check size={14} /> Granted for {health.drive_account}.
          </p>
        ) : (
          <>
            <p className="small">
              Google will ask for read-only access to your Drive. Sending mail
              as you is asked for again at the same time and is not replaced.
            </p>
            <button className="primary" disabled={consent.isPending}
              onClick={() => consent.mutate()}>
              <Link2 size={16} /> {consent.isPending ? "Opening Google…" : "Allow Drive access"}
            </button>
          </>
        )}
      </div>

      <div className="connect-step">
        <h4>2. Choose the folder</h4>
        <Field label="Drive folder link">
          <input aria-label="Drive folder link" value={pasted}
            disabled={!health.drive_access}
            placeholder="https://drive.google.com/drive/folders/…"
            onChange={(e) => { setPasted(e.target.value); setFound(null); }} />
        </Field>
        <p className="small muted">
          Open the folder in Drive and paste its web address. The id on its own
          works too.
        </p>
        <div className="row tight">
          <button disabled={!health.drive_access || !pasted.trim() || check.isPending}
            onClick={() => check.mutate()}>
            {check.isPending ? "Looking…" : "Check folder"}
          </button>
        </div>
        {found && (
          // Nothing is saved until this is confirmed: the point of checking
          // first is to find out it is the wrong folder before it is watched.
          <div className="found-folder">
            <p><strong>{found.name}</strong></p>
            <p className="small muted">
              {found.files}{found.truncated && "+"} file{found.files === 1 ? "" : "s"}
              {" · "}{found.readable} readable as meeting notes
            </p>
            {found.readable === 0 && (
              <Banner kind="warn">
                Nothing in there can be read as notes. Docs, .txt and .docx are
                read; PDFs and recordings are not.
              </Banner>
            )}
            <button className="primary" disabled={connect.isPending}
              onClick={() => connect.mutate()}>
              {connect.isPending ? "Saving…" : "Watch this folder"}
            </button>
          </div>
        )}
      </div>
    </Card>
  );
}

/**
 * Another folder the same watch reads (owner, 2026-09-28). Google Meet keeps
 * each meeting's notes in a folder of its own, so it is read at any depth —
 * and only Docs named like the pattern, or it would read recordings and chat.
 */
function ExtraFolder({ folder, mine, setProblem }: {
  folder: WatchFolder; mine: boolean; setProblem: (text: string) => void;
}) {
  const qc = useQueryClient();
  const [pattern, setPattern] = useState(folder.name_pattern);
  const change = useMutation({
    mutationFn: (body: object | null) => body
      ? api.patch<DriveHealth>(`/api/drive-watch/folders/${folder.id}/`, body)
      : api.del<DriveHealth>(`/api/drive-watch/folders/${folder.id}/`),
    onSuccess: (data) => { setProblem(""); qc.setQueryData(["drive-watch"], data); },
    onError: (e: Error) => setProblem(e.message),
  });
  return (
    <Card title={folder.folder_name || folder.folder_id}
      actions={mine && (
        <button className="small" disabled={change.isPending}
          onClick={() => change.mutate(null)}>Stop watching</button>
      )}>
      <p className="small muted">
        <FolderOpen size={12} /> Also watched
        {" · "}{folder.depth === "any" ? "every folder inside it" : "one level down"}
        {folder.name_pattern && <> · only Google Docs named like “{folder.name_pattern}”</>}
        {" · "}{folder.files_recorded} seen
        {folder.excluded > 0 && ` · ${folder.excluded} excluded`}
      </p>
      {mine && (
        <div className="row tight">
          <input aria-label={`Name pattern for ${folder.folder_name}`} value={pattern}
            onChange={(e) => setPattern(e.target.value)} />
          <button className="small"
            disabled={change.isPending || pattern.trim() === folder.name_pattern
                      || (folder.depth === "any" && !pattern.trim())}
            onClick={() => change.mutate({ name_pattern: pattern.trim() })}>
            Save pattern
          </button>
        </div>
      )}
    </Card>
  );
}

function AddFolder({ setNote, setProblem }: {
  setNote: (text: string) => void; setProblem: (text: string) => void;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [link, setLink] = useState("");
  const [depth, setDepth] = useState<WatchFolder["depth"]>("any");
  const [pattern, setPattern] = useState("Notes by Gemini");
  const add = useMutation({
    mutationFn: () => api.post<DriveHealth>("/api/drive-watch/folders/",
      { folder: link, depth, name_pattern: pattern }),
    onSuccess: (data) => {
      setProblem(""); qc.setQueryData(["drive-watch"], data);
      qc.invalidateQueries({ queryKey: ["drive-backfill"] });
      setNote("Watching that folder too. New notes in it arrive on their own; "
              + "anything already there can be imported below.");
      setOpen(false); setLink("");
    },
    onError: (e: Error) => setProblem(e.message),
  });
  if (!open) {
    return (
      <p><button className="small" onClick={() => setOpen(true)}>
        <FolderOpen size={14} /> Watch another folder
      </button></p>
    );
  }
  return (
    <Card title="Watch another folder"
      actions={<button className="small" onClick={() => setOpen(false)}>Cancel</button>}>
      <Field label="Drive folder link">
        <input aria-label="Another Drive folder link" value={link}
          placeholder="https://drive.google.com/drive/folders/…"
          onChange={(e) => setLink(e.target.value)} />
      </Field>
      <div className="row">
        <Field label="How deep">
          <select aria-label="How deep" value={depth}
            onChange={(e) => setDepth(e.target.value as WatchFolder["depth"])}>
            <option value="any">Every folder inside it</option>
            <option value="one">This folder and one level down</option>
          </select>
        </Field>
        <Field label="Only Google Docs named like">
          <input aria-label="Only Google Docs named like" value={pattern}
            onChange={(e) => setPattern(e.target.value)} />
        </Field>
      </div>
      <p className="small muted">
        Google Meet keeps each meeting's notes in a folder of their own, so read it
        at every depth. The name keeps it to the notes: recordings, transcripts and
        chat are left alone.
      </p>
      <button className="primary"
        disabled={add.isPending || !link.trim() || (depth === "any" && !pattern.trim())}
        onClick={() => add.mutate()}>
        {add.isPending ? "Checking the folder…" : "Watch it"}
      </button>
    </Card>
  );
}

/**
 * Titles never read, in any watched folder (owner, 2026-09-28). A file whose
 * name, or a folder it sits in, has one of these as a whole word is recorded
 * as skipped and never sent to Claude.
 */
function Exclusions({ health, mine, setProblem }: {
  health: DriveHealth; mine: boolean; setProblem: (text: string) => void;
}) {
  const qc = useQueryClient();
  const [pattern, setPattern] = useState("");
  const done = (data: DriveHealth) => { setProblem(""); qc.setQueryData(["drive-watch"], data); };
  const add = useMutation({
    mutationFn: () => api.post<DriveHealth>("/api/drive-watch/exclusions/", { pattern }),
    onSuccess: (data) => { done(data); setPattern(""); },
    onError: (e: Error) => setProblem(e.message),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del<DriveHealth>(`/api/drive-watch/exclusions/${id}/`),
    onSuccess: done,
    onError: (e: Error) => setProblem(e.message),
  });
  const rows = health.exclusions ?? [];
  return (
    <Card title="Never read">
      <p className="small muted">
        Meetings whose title, or the folder they are in, contains one of these are
        noted as skipped and never sent to Claude.
      </p>
      {rows.length === 0 ? <Empty>Nothing is excluded.</Empty> : (
        <p className="inline" style={{ flexWrap: "wrap" }}>
          {rows.map((row) => (
            <span key={row.id} className="pill">
              {row.pattern}
              {mine && (
                <button className="icon-button" aria-label={`Read ${row.pattern} again`}
                  disabled={remove.isPending} onClick={() => remove.mutate(row.id)}>
                  <X size={12} />
                </button>
              )}
            </span>
          ))}
        </p>
      )}
      {mine && (
        <div className="row tight">
          <input aria-label="Exclude titles containing" value={pattern}
            placeholder="A word or phrase" onChange={(e) => setPattern(e.target.value)} />
          <button className="small" disabled={!pattern.trim() || add.isPending}
            onClick={() => add.mutate()}>Exclude</button>
        </div>
      )}
    </Card>
  );
}

/**
 * The folder's past — a choice, never a default (FR-5.1b).
 *
 * **Drive's cursor starts at "now".** A folder holding six months of notes is,
 * to the poller, empty until the next meeting happens; that is what produced
 * "0 waiting" on 167 real notes. Reading the past is a different thing from
 * watching the future: it costs one Claude call per note and fills the review
 * queue with months of work, most of it possibly long settled.
 *
 * So this panel states what is there, what each option would take and what it
 * would cost **before** anything starts, and treats "only new notes" as an
 * answer rather than as the absence of one.
 */
function Past({ health, folder, setProblem }: {
  health: DriveHealth; setProblem: (text: string) => void;
  /** One of the watch's extra folders, or null for the first one. */
  folder: WatchFolder | null;
}) {
  const qc = useQueryClient();
  const [scope, setScope] = useState<Backfill["scope"]>("all");
  const [since, setSince] = useState("");
  // One import runs at a time across every folder; this panel shows it only
  // when it is this folder's, and offers nothing while another folder's runs.
  const latest = health.backfill;
  const ours = !!latest && (latest.folder ?? null) === (folder?.id ?? null);
  const backfill = ours ? latest : null;
  const busyElsewhere = !!latest?.running && !ours;
  const which = folder ? { folder: folder.id } : {};

  // Asked every time, not only before the first decision. An import that read
  // 8 of 167 notes leaves 159 unread, and a panel that congratulates itself
  // and disappears is how they stay that way.
  const past = useQuery<{ folder: FolderPast; backfill: Backfill | null }>({
    queryKey: folder ? ["drive-backfill", folder.id] : ["drive-backfill"],
    queryFn: () => api.get(`/api/drive-watch/backfill/${folder ? `?folder=${folder.id}` : ""}`),
    enabled: !backfill?.running && !busyElsewhere,
  });

  // Asked again each time the date changes: a count and a cost the fractional
  // has not seen is a cost they have not agreed to.
  const plan = useQuery<BackfillPlan>({
    queryKey: ["drive-backfill-plan", folder?.id ?? null, since],
    queryFn: () => api.post<BackfillPlan>("/api/drive-watch/backfill/plan/",
      { since, ...which }),
    enabled: scope === "since" && /^\d{4}-\d{2}-\d{2}$/.test(since),
  });

  // Past the estimated AI balance the server asks rather than starts
  // (owner, 2026-09-28); the question is shown here, with a way to go ahead.
  const [ask, setAsk] = useState("");
  const choose = useMutation({
    mutationFn: (confirmed: boolean) => api.post<Backfill>("/api/drive-watch/backfill/",
      { scope, since: scope === "since" ? since : null, ...which,
        ...(confirmed ? { confirm_over_balance: true } : {}) }),
    onSuccess: () => { setProblem(""); setAsk("");
                       qc.invalidateQueries({ queryKey: ["drive-watch"] }); },
    onError: (e: Error) => asksToConfirm(e) ? setAsk(e.message) : setProblem(e.message),
  });

  const stop = useMutation({
    mutationFn: () => api.post<Backfill>("/api/drive-watch/backfill/stop/"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["drive-watch"] }),
    onError: (e: Error) => setProblem(e.message),
  });

  if (backfill?.running) {
    const read = backfill.done + backfill.skipped + backfill.failed;
    return (
      <Card title={`Importing the notes in ${backfill.folder_name || "the folder"}`}
        actions={<button className="small" disabled={stop.isPending}
          onClick={() => stop.mutate()}>Stop</button>}>
        <Progress done={read} total={backfill.planned} />
        <p className="small muted">
          {backfill.done} read of {backfill.planned}
          {backfill.skipped > 0 && ` · ${backfill.skipped} skipped`}
          {backfill.failed > 0 && ` · ${backfill.failed} failed`}
          {" · "}<strong>${backfill.cost_usd.slice(0, 6)} spent so far</strong>
          {" "}of about ${backfill.estimated_cost_usd}
        </p>
        <p className="small muted">
          A few a minute, oldest first, so the rest of the app keeps working.
          Each one lands in the queue below as it is read. Stopping keeps
          everything already read.
        </p>
        {backfill.last_error && <Banner kind="warn">{backfill.last_error}</Banner>}
      </Card>
    );
  }

  if (busyElsewhere) return null;
  if (past.isLoading) return <p className="small muted">Looking in the folder…</p>;
  if (!past.data) return null;
  const found = past.data.folder;
  // This folder's own last import, not whichever folder imported last.
  const last = past.data.backfill;
  const done = last && last.state !== "declined" && last.done > 0;
  const name = folder?.folder_name || found.folder_name || "this folder";
  const correction = last?.correction_note && (
    <p className="small"><strong>Correction:</strong> {last.correction_note}</p>
  );

  // Nothing left unread: say what was imported, once, and stop asking.
  if (found.outstanding === 0) {
    if (!done) return null;
    return (
      <Banner kind="info">
        Imported {last!.done} note{last!.done === 1 ? "" : "s"} from {name}
        {last!.state === "cancelled" && " before you stopped it"}, for
        ${last!.cost_usd.slice(0, 6)}. Nothing older is left unread, and new
        notes arrive on their own.
        {correction}
      </Banner>
    );
  }

  const chosen = scope === "since" ? plan.data : found;
  return (
    <Card title={done ? `Older notes in ${name} are still unread`
                      : `${name} already holds notes`}>
      {done && (
        <p className="small muted">
          You imported {last!.done} last time
          {last!.state === "cancelled" && " before stopping"}, for
          ${last!.cost_usd.slice(0, 6)}.
        </p>
      )}
      {correction}
      <p>
        <strong>{found.outstanding} readable note{found.outstanding === 1 ? "" : "s"}</strong>
        {found.oldest && <> {done ? "remain unread" : "are already in it"}, from{" "}
          {found.oldest} to {found.newest}</>}.
        {" "}
        {/* The thing that is not obvious and causes the confusion: watching
            starts now, so none of these will appear on their own — and "Sync
            now" will not bring them either. */}
        Watching only picks up notes added from now on, so “Sync now” will not
        find these. Importing them here is the only thing that will.
      </p>
      {(found.already_recorded ?? 0) > 0 && (
        <p className="small muted">
          {found.already_recorded} more {found.already_recorded === 1 ? "is a meeting" : "are meetings"}
          {" "}already recorded from another folder, so not counted or read again.
        </p>
      )}
      {(found.shared_with ?? []).map((other) => (
        <p key={other.folder ?? "first"} className="small">
          <strong>{other.count} of these are the same notes the {other.folder_name} panel
          offers.</strong> Import either one; the other then finds them already read.
        </p>
      ))}
      {(found.excluded ?? 0) > 0 && (
        <p className="small muted">
          {found.excluded} more {found.excluded === 1 ? "is" : "are"} on the exclusion
          list: {found.excluded === 1 ? "it" : "they"} will be recorded as skipped and
          never read, and {found.excluded === 1 ? "is" : "are"} not in the cost below.
        </p>
      )}
      {folder?.depth === "any" && (
        <p className="small muted">
          Counted in every folder inside it, and only Google Docs named like
          “{folder.name_pattern}”.
        </p>
      )}
      {found.subfolders.length > 0 && (
        <p className="small muted">
          Including {found.readable_in_subfolders} in{" "}
          {found.subfolders.map((s) => s.name).join(", ")} — subfolders are read too,
          one level down.
        </p>
      )}

      <fieldset className="choices">
        <legend className="small muted">What should happen to them?</legend>
        {([
          ["now", "Start from now — only new notes"],
          ["since", "Also import notes since"],
          ["all", done ? `Import the remaining ${found.outstanding}`
                       : `Import everything — all ${found.outstanding}`],
        ] as const).map(([value, label]) => (
          <label key={value} className="choice">
            <input type="radio" name="backfill-scope" value={value}
              checked={scope === value} onChange={() => setScope(value)} />
            <span>{label}</span>
            {value === "since" && (
              <input type="date" aria-label="Import notes since" value={since}
                max={found.newest || undefined} min={found.oldest || undefined}
                onChange={(e) => { setSince(e.target.value); setScope("since"); }} />
            )}
          </label>
        ))}
      </fieldset>

      {scope !== "now" && (
        // Shown before confirming, always. An estimate nobody saw is a cost
        // nobody agreed to.
        <p className="small">
          {plan.isFetching && scope === "since" ? "Counting…" : chosen ? (
            <>
              <strong>{chosen.outstanding} note{chosen.outstanding === 1 ? "" : "s"}</strong>,
              about <strong>${chosen.estimate_usd}</strong> of AI
              {" "}({found.per_note_is_measured
                ? `$${found.per_note_usd} each, your average so far`
                : `about $${found.per_note_usd} each, estimated`}),
              roughly {chosen.minutes} minute{chosen.minutes === 1 ? "" : "s"} to read.
            </>
          ) : "Pick a date to see the count and the cost."}
        </p>
      )}

      {ask && (
        <Banner kind="warn">
          {ask}{" "}
          <button className="small" disabled={choose.isPending}
            onClick={() => choose.mutate(true)}>Import anyway</button>{" "}
          <button className="small" onClick={() => setAsk("")}>Not now</button>
        </Banner>
      )}
      <button className="primary"
        disabled={choose.isPending || (scope === "since" && !plan.data)}
        onClick={() => choose.mutate(false)}>
        {choose.isPending ? "Starting…"
          : scope === "now" ? "Start from now"
          : `Import ${chosen?.outstanding ?? ""} notes`}
      </button>
    </Card>
  );
}

/** A bar, because "42 of 167" is a number and this is a wait. */
function Progress({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  return (
    <div className="progress" role="progressbar" aria-valuenow={pct}
      aria-valuemin={0} aria-valuemax={100} aria-label="Import progress">
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Dismissed proposals, with why, and the way back (owner, 2026-09-28). */
function Archived({ rows, onChanged, setNote }: {
  rows: MeetingProposal[]; onChanged: () => void; setNote: (text: string) => void;
}) {
  const restore = useMutation({
    mutationFn: (id: string) => api.post(`/api/meeting-proposals/${id}/restore/`),
    onSuccess: () => { setNote("Restored to the queue."); onChanged(); },
    onError: (e: Error) => setNote(e.message),
  });
  if (rows.length === 0) return <Empty>Nothing has been dismissed.</Empty>;
  return (
    <>
      {rows.map((proposal) => (
        <Card key={proposal.id} title={proposal.title || proposal.source_file.name}
          actions={<button className="small" disabled={restore.isPending}
            onClick={() => restore.mutate(proposal.id)}>Restore</button>}>
          <p className="small muted">
            <Pill>{proposal.dismissed?.reason_label ?? "Dismissed"}</Pill>
            {proposal.dismissed?.note && <> · {proposal.dismissed.note}</>}
            {" · "}{proposal.dismissed?.by || "someone"}
            {proposal.dismissed?.at && <>, {when(proposal.dismissed.at)}</>}
            {" · "}<FileText size={12} /> {proposal.source_file.name}
          </p>
        </Card>
      ))}
    </>
  );
}

const DISMISS_REASONS: [DismissReason, string][] = [
  ["no_meeting", "No meeting happened"],
  ["not_relevant", "Not relevant"],
  ["vendor_pitch", "Vendor pitch"],
  ["other", "Other"],
];

/**
 * Close the whole proposal with a reason; nothing is created (owner,
 * 2026-09-28). For a vendor's pitch, the vendor can be recorded — as a vendor,
 * with what they do — and everything else dismissed in the same step.
 */
function DismissPanel({ proposal, onDone, onCancel, setNote }: {
  proposal: MeetingProposal; onDone: () => void; onCancel: () => void;
  setNote: (text: string) => void;
}) {
  const [reason, setReason] = useState<DismissReason | "">("");
  const [note, setNoteText] = useState("");
  const people = (proposal.items ?? []).filter(
    (i) => i.kind === "participant" && i.state === "pending");
  const [who, setWho] = useState(people[0]?.id ?? "");
  const [link, setLink] = useState("");            // "" = a new contact
  const [categories, setCategories] = useState("");
  const person = people.find((p) => p.id === who);
  const candidates = person?.payload.existing_candidates ?? [];

  const send = useMutation({
    mutationFn: (asVendor: boolean) => api.post(
      `/api/meeting-proposals/${proposal.id}/dismiss/`, {
        reason, note,
        ...(asVendor ? { vendor: {
          item: who,
          ...(link ? { contact_id: link } : {}),
          service_categories: categories.split(",").map((c) => c.trim()).filter(Boolean),
        } } : {}),
      }),
    onSuccess: (_data, asVendor) => {
      setNote(asVendor
        ? `Recorded ${person?.payload.parsed_name ?? "them"} as a vendor; the rest is `
          + "dismissed. It is under Archived if you need it back."
        : "Dismissed. Nothing was created; it is under Archived if you need it back.");
      onDone();
    },
    onError: (e: Error) => setNote(e.message),
  });

  return (
    <Card title="Dismiss this proposal"
      actions={<button className="small" onClick={onCancel}>Cancel</button>}>
      <fieldset className="choices">
        <legend className="small muted">Why?</legend>
        {DISMISS_REASONS.map(([value, label]) => (
          <label key={value} className="choice">
            <input type="radio" name={`dismiss-${proposal.id}`} value={value}
              checked={reason === value} onChange={() => setReason(value)} />
            <span>{label}</span>
          </label>
        ))}
      </fieldset>
      <Field label={reason === "other" ? "Why (needed for Other)" : "A note (optional)"}>
        <textarea aria-label="Dismissal note" rows={2} value={note}
          onChange={(e) => setNoteText(e.target.value)} />
      </Field>

      {reason === "vendor_pitch" && people.length > 0 && (
        <div className="subpanel">
          <h4 style={{ marginTop: 0 }}>Record as vendor and dismiss the rest</h4>
          <div className="row">
            <Field label="Who is the vendor">
              <select aria-label="Who is the vendor" value={who}
                onChange={(e) => { setWho(e.target.value); setLink(""); }}>
                {people.map((p) => (
                  <option key={p.id} value={p.id}>{p.payload.parsed_name}</option>
                ))}
              </select>
            </Field>
            {candidates.length > 0 && (
              <Field label="As">
                <select aria-label="Vendor contact" value={link}
                  onChange={(e) => setLink(e.target.value)}>
                  <option value="">A new contact</option>
                  {candidates.map((c) => (
                    <option key={c.contact_id} value={c.contact_id}>
                      {c.name}{c.company ? `, ${c.company}` : ""} (already a contact)
                    </option>
                  ))}
                </select>
              </Field>
            )}
          </div>
          <Field label="What they do (service categories, comma-separated)">
            <input aria-label="Vendor service categories" value={categories}
              placeholder="Duct cleaning, grease traps"
              onChange={(e) => setCategories(e.target.value)} />
          </Field>
          <p className="small muted">
            A vendor needs at least one category, so they can be found by what they
            do. No tasks are created from this meeting.
          </p>
          <button className="primary"
            disabled={send.isPending || !who || !categories.trim()}
            onClick={() => send.mutate(true)}>
            Record as vendor and dismiss the rest
          </button>
        </div>
      )}

      <button className={reason === "vendor_pitch" ? "" : "primary"}
        disabled={send.isPending || !reason || (reason === "other" && !note.trim())}
        onClick={() => send.mutate(false)}>
        Dismiss{reason === "vendor_pitch" ? " without recording the vendor" : ""}
      </button>
    </Card>
  );
}

/** The meeting's own name, as a starting pattern: Gemini names a file
 *  "<meeting> - 2026/09/24 17:35 MDT - Notes by Gemini". */
export function meetingNameOf(fileName: string) {
  return fileName.split(/ - \d{4}\/\d{2}\/\d{2}/)[0].replace(/ - Notes by Gemini$/, "").trim();
}

function ProposalDetail({ id, onChanged, setNote, me }: {
  id: string; onChanged: () => void; setNote: (text: string) => void; me: Me;
}) {
  const qc = useQueryClient();
  const [ignoring, setIgnoring] = useState<string | null>(null);
  const [dismissing, setDismissing] = useState(false);
  const ignore = useMutation({
    mutationFn: (pattern: string) =>
      api.post(`/api/meeting-proposals/${id}/ignore/`, { pattern }),
    onSuccess: (_data, pattern) => {
      setNote(`“${pattern}” is on the never-read list. This one is out of the queue, `
              + "and meetings with that in their title or folder will not be read.");
      setIgnoring(null);
      qc.invalidateQueries({ queryKey: ["drive-watch"] });
      onChanged();
    },
    onError: (e: Error) => setNote(e.message),
  });
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
        {!dismissing && (
          <button className="small" onClick={() => setDismissing(true)}>
            <X size={14} /> Dismiss
          </button>
        )}
        {me.role === "FF" && ignoring === null && (
          <button className="small"
            onClick={() => setIgnoring(meetingNameOf(proposal.source_file.name))}>
            <EyeOff size={14} /> Ignore this file
          </button>
        )}
      </div>
      {dismissing && (
        <DismissPanel proposal={proposal} setNote={setNote}
          onCancel={() => setDismissing(false)}
          onDone={() => { setDismissing(false); onChanged(); }} />
      )}
      {ignoring !== null && (
        <div className="row tight" style={{ marginTop: "var(--s2)" }}>
          <Field label="Never read meetings whose title or folder contains">
            <input aria-label="Never read meetings whose title or folder contains"
              value={ignoring} onChange={(e) => setIgnoring(e.target.value)} />
          </Field>
          <button className="primary small" disabled={!ignoring.trim() || ignore.isPending}
            onClick={() => ignore.mutate(ignoring.trim())}>Ignore</button>
          <button className="small" onClick={() => setIgnoring(null)}>Cancel</button>
        </div>
      )}

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
  // FR-5.10a — "" is the best company we already hold, "new" creates the one
  // the notes named, "none" leaves the contact without one.
  const candidates = payload.company_candidates ?? [];
  const [company, setCompany] = useState<string>(
    candidates[0]?.company_id ?? (payload.parsed_company ? "new" : "none"));
  const [companyName, setCompanyName] = useState(payload.parsed_company ?? "");
  const [companyDomain, setCompanyDomain] = useState(payload.parsed_company_domain ?? "");
  // Whose action item it is (2026-09-28). Claude proposed; the reviewer confirms.
  const [side, setSide] = useState<"practice" | "other">(
    payload.owner_side === "other" ? "other" : "practice");
  const [kind, setKind] = useState<string>(payload.owner_kind || "third_party");
  const hasSeat = !!payload.owner_has_seat;
  const [outcome, setOutcome] = useState<string>(payload.proposed_outcome
    || (hasSeat ? "portal" : ["prospect", "third_party"].includes(kind) ? "follow_up"
        : "record_only"));
  const inAWeek = new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10);
  const [followUp, setFollowUp] = useState(payload.proposed_due_date ?? inAWeek);
  const [notifyMe, setNotifyMe] = useState(true);
  const ownerName = item.owner_contact_name || payload.proposed_owner_text || "";

  const act = useMutation({
    mutationFn: ({ verb, body }: { verb: string; body?: object }) =>
      api.post(`/api/proposal-items/${item.id}/${verb}/`, body),
    onSuccess: () => onChanged(),
    onError: (e: Error) => setNote(e.message),
  });

  const decided = item.state !== "pending";
  // FR-5.9e — our own side of the table. Shown, because who was in the room is
  // the point of the record; not asked about, because the practice is not a
  // prospect, a client, a referral partner, a vendor or a coworker of itself.
  const ours = item.is_practice;
  return (
    <div className="card" style={{ opacity: decided && !ours ? 0.6 : 1 }}>
      <div className="spread" style={{ alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{ margin: 0, fontWeight: 550 }}>
            {item.kind === "participant"
              ? `${payload.parsed_name}${payload.parsed_email ? ` · ${payload.parsed_email}` : ""}`
              : payload.text}
          </p>
          {ours && (
            <p className="tiny muted" style={{ margin: "2px 0 0" }}>
              {payload.practice_name ?? "Your practice"} — the practice. Recorded
              as attending; nothing to decide.
            </p>
          )}
          {/* FR-5.14 — what it was drawn from, so the claim is checkable. */}
          {item.source_excerpt && (
            <p className="tiny muted" style={{ margin: "2px 0 0", fontStyle: "italic" }}>
              “{item.source_excerpt}”
            </p>
          )}
        </div>
        {ours ? <Pill kind="ok">us</Pill>
          : decided && <Pill kind={item.state === "approved" ? "ok" : ""}>{item.state}</Pill>}
      </div>

      {!decided && item.kind === "action_item" && (
        <div className="ownership">
          <p className="small" style={{ margin: 0 }}>
            <strong>Owner:</strong>{" "}
            {!ownerName ? "nobody named — the practice's to do"
              : payload.owner_side === "practice"
                ? `${payload.owner_practice_name || ownerName} — the practice`
                : `${ownerName}${payload.owner_side === "other"
                    ? ` — ${(payload.owner_kind || "someone else").replace("_", " ")}`
                    + (hasSeat ? " · has a portal seat" : "") : ""}`}
            {!payload.owner_side && ownerName && (
              <span className="muted"> (not yet classified — confirm below)</span>)}
          </p>
          <div className="row tight">
            <label className="choice">
              <input type="radio" name={`side-${item.id}`} checked={side === "practice"}
                onChange={() => setSide("practice")} />
              <span>Ours — make it a task</span>
            </label>
            <label className="choice">
              <input type="radio" name={`side-${item.id}`} checked={side === "other"}
                disabled={!ownerName} onChange={() => setSide("other")} />
              <span>{ownerName ? `${ownerName}'s — a commitment` : "Someone else's"}</span>
            </label>
            {side === "other" && (
              <select aria-label={`What ${ownerName} is to us`} value={kind}
                style={{ width: "auto" }} onChange={(e) => setKind(e.target.value)}>
                <option value="client">Client</option>
                <option value="prospect">Prospect</option>
                <option value="vendor">Vendor</option>
                <option value="third_party">Third party</option>
              </select>
            )}
          </div>
          {side === "other" && (
            <fieldset className="choices">
              <legend className="small muted">When approved</legend>
              <label className="choice">
                <input type="radio" name={`outcome-${item.id}`} checked={outcome === "follow_up"}
                  onChange={() => setOutcome("follow_up")} />
                <span>Follow up — a task for us to check it happened, on</span>
                <input type="date" aria-label="Follow-up date" value={followUp}
                  style={{ width: "auto" }}
                  onChange={(e) => { setFollowUp(e.target.value); setOutcome("follow_up"); }} />
              </label>
              <label className="choice">
                <input type="radio" name={`outcome-${item.id}`} checked={outcome === "record_only"}
                  onChange={() => setOutcome("record_only")} />
                <span>Record only — keep it on {ownerName}'s record, no task</span>
              </label>
              <label className="choice" title={hasSeat ? undefined : "Only for a client user with a portal seat"}>
                <input type="radio" name={`outcome-${item.id}`} checked={outcome === "portal"}
                  disabled={!hasSeat} onChange={() => setOutcome("portal")} />
                <span>Assign in the portal — {hasSeat ? `${ownerName}'s task, waiting on the client`
                  : "needs a portal seat"}</span>
                {outcome === "portal" && (
                  <label className="inline small">
                    <input type="checkbox" style={{ width: "auto" }} checked={notifyMe}
                      onChange={(e) => setNotifyMe(e.target.checked)} />
                    tell me on every update
                  </label>
                )}
              </label>
            </fieldset>
          )}
        </div>
      )}

      {!decided && !ours && item.kind === "participant" && (
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
          {/* A contact created without its company is a contact somebody has
              to go back and fix. So the company is asked for here, beside the
              person, and not left to be noticed later. */}
          {!pick && (payload.parsed_company || candidates.length > 0) && (
            <Field label="Which company">
              <select aria-label={`Company for ${payload.parsed_name}`} value={company}
                onChange={(e) => setCompany(e.target.value)}>
                {candidates.map((row) => (
                  <option key={row.company_id} value={row.company_id}>
                    {row.name} — {row.match_reason === "created_in_this_review"
                      ? "created a moment ago in this review"
                      : `matched on ${row.match_reason.replace(/_/g, " ")}`}
                  </option>
                ))}
                {payload.parsed_company && (
                  <option value="new">Create “{payload.parsed_company}”</option>
                )}
                <option value="none">No company</option>
              </select>
            </Field>
          )}
          {!pick && company === "new" && (
            <>
              <Field label="New company name">
                <input aria-label={`New company name for ${payload.parsed_name}`}
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)} />
              </Field>
              <Field label="Email domain — optional">
                <input aria-label={`New company domain for ${payload.parsed_name}`}
                  value={companyDomain} placeholder="acme.com"
                  onChange={(e) => setCompanyDomain(e.target.value)} />
              </Field>
            </>
          )}
          {type === "vendor" && (
            <Field label="What they do — comma separated">
              <input aria-label={`Service categories for ${payload.parsed_name}`}
                value={categories} placeholder="Duct cleaning, grease traps"
                onChange={(e) => setCategories(e.target.value)} />
            </Field>
          )}
        </div>
      )}

      {!decided && !ours && (
        <div className="row tight" style={{ marginTop: "var(--s2)" }}>
          <button className="primary small" disabled={act.isPending}
            aria-label={`Approve ${payload.parsed_name ?? payload.text}`}
            onClick={() => act.mutate({ verb: "approve", body: {
              ...(item.kind === "participant"
                ? { contact_id: pick, contact_type: type,
                    service_categories: categories.split(",").map((c) => c.trim())
                      .filter(Boolean),
                    // Only ever one of the two, and neither when the reviewer
                    // said the contact has no company.
                    ...(pick || company === "none" ? {}
                      : company === "new"
                        ? { create_company: { name: companyName,
                                              domain: companyDomain } }
                        : { company_id: company }) }
                : item.kind === "action_item"
                  ? { owner_side: side,
                      ...(side === "other" ? { owner_kind: kind, outcome,
                        ...(outcome === "follow_up" ? { follow_up_date: followUp } : {}),
                        ...(outcome === "portal" ? { notify_me: notifyMe } : {}) } : {}) }
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
