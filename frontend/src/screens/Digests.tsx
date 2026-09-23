import { PageHead } from "../components/shell";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Banner, Card, Empty, Field, Pill, countdown, when } from "../components/ui";
import { Contact, DigestRow, Me, TickStatus, UpcomingDigest, api } from "../lib/api";

const CAN_APPROVE = ["FF", "CF"];

/** A clock that moves. A countdown rendered once is wrong a minute later. */
function useNow(everyMs = 30_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(id);
  }, [everyMs]);
  return now;
}

/**
 * FR-3.29 — the approval screen, and the last thing standing between the app
 * and a client's inbox. It shows the **whole rendered digest**, not a summary
 * of it, because approving something you have not read is the failure this
 * screen exists to prevent.
 *
 * Matrix 8.1/8.2/8.3 — a VA sees everything here and has no approve control.
 */
export function Digests({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const mayApprove = !!me.role && CAN_APPROVE.includes(me.role);

  // Refreshed on its own: expiry and generation happen on the server's tick,
  // and this list used to go on showing a digest as pending after the tick had
  // expired it (Check 3). Window focus does not refetch in this app.
  const digests = useQuery<DigestRow[]>({
    queryKey: ["digests"], queryFn: () => api.get<DigestRow[]>("/api/digests/"),
    refetchInterval: 30_000,
  });
  const tick = useQuery<TickStatus>({
    queryKey: ["tick-status"],
    queryFn: () => api.get<TickStatus>("/api/digests/tick-status/"),
    refetchInterval: 60_000,
  });
  const upcoming = useQuery<UpcomingDigest[]>({
    queryKey: ["digests-upcoming"],
    queryFn: () => api.get<UpcomingDigest[]>("/api/digests/upcoming/"),
    refetchInterval: 30_000,
  });
  const now = useNow();

  const refresh = () => qc.invalidateQueries({ queryKey: ["digests"] });
  const act = useMutation({
    mutationFn: ({ id, path, body }: { id: string; path: string; body?: object }) =>
      api.post(`/api/digests/${id}/${path}/`, body),
    onSuccess: () => { setNote(""); setEditing(null); refresh(); },
    onError: (e: Error) => setNote(e.message),
  });
  const approveAll = useMutation({
    mutationFn: () => api.post<{ approved: string[]; refused: { detail: string }[] }>(
      "/api/digests/approve-selected/", { ids: picked }),
    onSuccess: (r) => {
      setNote(`${r.approved.length} approved.`
        + (r.refused.length ? ` ${r.refused.length} refused: ${r.refused[0].detail}` : ""));
      setPicked([]);
      refresh();
    },
    onError: (e: Error) => setNote(e.message),
  });

  const rows = digests.data ?? [];

  return (
    <>
      <PageHead title="Digests awaiting approval"
        sub={<>Nothing here has been sent. Every digest waits for a person while
        <span className="mono"> hold_all_digests</span> is on, which is the default — and an
        AI-written one waits even when it is off.</>} />
      {note && <Banner kind="info">{note}</Banner>}

      {tick.data?.stale && (
        <Banner kind="bad">
          <strong>The scheduled tick has not run in the last {tick.data.stale_after_minutes} minutes.</strong>{" "}
          Nothing on this screen expires, generates or sends until it does.
          {tick.data.last_success_at
            ? ` Last successful run: ${when(tick.data.last_success_at)}.`
            : " There is no record of it running."}
          {tick.data.last_failure && ` Last failure: ${tick.data.last_failure}`}
          {" "}Restart <span className="mono">qcluster</span>, and run migrations first if the
          failure names a missing column.
        </Banner>
      )}

      {(upcoming.data ?? []).length > 0 && (
        <Card title="Coming up">
          <ul className="timeline">
            {upcoming.data!.map((u) => (
              <li key={u.contact.id}>
                <div>{comingUpLine(u)}</div>
                <div className="when">
                  {u.update_count} update{u.update_count === 1 ? "" : "s"} waiting
                  {u.tasks.length > 1 && ` on ${u.tasks.join(", ")}`} · last change {when(u.last_change_at)}
                </div>
              </li>
            ))}
          </ul>
          <p className="small muted">
            Every-update digests wait for 30 minutes of quiet, so one editing session is one email.
            Nothing here has been generated or sent yet, and each new change moves the time.
          </p>
        </Card>
      )}

      {me.dev_tools && <GenerateNow onDone={(text) => { setNote(text); refresh(); }} />}
      {!mayApprove && (
        <Banner kind="info">
          You can read and edit these to get them ready. Approving and sending is the
          founder's or a contractor fractional's call.
        </Banner>
      )}

      {rows.length === 0 ? <Empty>Nothing waiting. Nobody is owed an email.</Empty> : (
        <>
          {mayApprove && (
            <Card>
              <div className="row">
                <button className="primary" disabled={!picked.length || approveAll.isPending}
                  onClick={() => approveAll.mutate()}>
                  Approve {picked.length || ""} selected
                </button>
                <button className="ghost" onClick={() => setPicked(rows.map((d) => d.id))}>
                  Select all
                </button>
                {picked.length > 0 && (
                  <button className="ghost" onClick={() => setPicked([])}>Clear</button>
                )}
              </div>
              <p className="small muted">
                Select-all still approves each one individually, and tells you if any was refused.
              </p>
            </Card>
          )}

          {rows.map((d) => (
            <Card key={d.id} title={`${d.contact.name} · ${d.cadence.replace(/_/g, " ")}`}
              actions={mayApprove ? (
                <label className="small" style={{ display: "inline-flex", gap: ".4rem" }}>
                  <input type="checkbox" style={{ width: "auto" }}
                    aria-label={`Select the digest for ${d.contact.name}`}
                    checked={picked.includes(d.id)}
                    onChange={(e) => setPicked(e.target.checked
                      ? [...picked, d.id]
                      : picked.filter((x) => x !== d.id))} />
                  Select
                </label>
              ) : undefined}>
              <p className="small muted">
                To {d.to_address} · covers {when(d.period_start)} to {when(d.period_end)} ·
                {d.cadence === "every_update"
                  ? <>sends as soon as approved</>
                  : <>sends {when(d.send_window_at)}</>}
                {" "}· {d.item_count} update{d.item_count === 1 ? "" : "s"}{" "}
                {d.is_ai_generated ? <Pill kind="ai">AI narrative</Pill> : <Pill>plain list</Pill>}
              </p>

              {d.state === "pending" && Date.parse(d.send_window_at) > now && (
                <p className="small">
                  <Pill kind="warn">Expires {countdown(d.send_window_at, now)}</Pill>{" "}
                  <span className="muted">
                    {when(d.send_window_at)} — unapproved by then it sends nothing, and its
                    updates are owed again next period.
                  </span>
                </p>
              )}

              {d.state === "pending" && Date.parse(d.send_window_at) <= now && (
                <Banner kind="warn">
                  Its window has passed. The next tick expires it unsent and its updates are
                  owed again; approving now is refused.
                </Banner>
              )}

              {d.is_stale && (
                <Banner kind="warn">
                  <strong>Overtaken by events.</strong> {d.stale_reason} You can approve it as
                  it stands, or rebuild it with what has happened since.
                  <br />
                  {/* Single-submit. Two of these a few milliseconds apart raced
                      in the engine on 2026-09-17 and left the draft skipped
                      while it still held its claims. The server takes a row
                      lock now; the button no longer offers the second click. */}
                  <button disabled={act.isPending}
                    onClick={() => act.mutate({ id: d.id, path: "regenerate" })}>
                    {act.isPending ? "Regenerating…" : "Regenerate"}
                  </button>
                </Banner>
              )}

              {editing === d.id ? (
                <>
                  <textarea aria-label="Digest text" rows={12} value={draft}
                    onChange={(e) => setDraft(e.target.value)} />
                  <p className="small muted">
                    Edited wording is sent as written, in plain paragraphs — without the task
                    grouping and status chips. Regenerate to get those back.
                  </p>
                  <div className="row">
                    <button className="primary"
                      onClick={() => act.mutate({ id: d.id, path: "edit",
                                                  body: { body_text: draft } })}>
                      Save the wording
                    </button>
                    <button className="ghost" onClick={() => setEditing(null)}>Cancel</button>
                  </div>
                </>
              ) : (
                <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: 0 }}>
                  {d.body_text}
                </pre>
              )}

              <div className="row" style={{ marginTop: ".75rem" }}>
                {mayApprove && (
                  <button className="primary"
                    onClick={() => act.mutate({ id: d.id, path: "approve" })}>
                    Approve and send
                  </button>
                )}
                {me.dev_tools && d.state === "pending" && (
                  <a className="btn ghost" href={`/api/digests/${d.id}/preview/`} target="_blank"
                    rel="noreferrer" aria-label={`Preview the email to ${d.contact.name}`}>
                    Preview email
                  </a>
                )}
                <button onClick={() => { setEditing(d.id); setDraft(d.body_text); }}>
                  Edit the wording
                </button>
                {mayApprove && (
                  <button className="danger" onClick={() => act.mutate({ id: d.id, path: "skip" })}>
                    Skip this one
                  </button>
                )}
              </div>
              {mayApprove && (
                <p className="small muted">
                  Skipping sends nothing and hands its content back to the next period.
                </p>
              )}
            </Card>
          ))}
        </>
      )}
    </>
  );
}


/**
 * Development only — the server says so, through `me.dev_tools`, and the
 * endpoint behind it does not exist off localhost.
 *
 * It runs the ordinary generation path for one person over a period you choose,
 * so a manual check does not have to wait until Thursday. It creates a draft and
 * sends nothing; everything after that behaves exactly as it will in real use.
 */
function GenerateNow({ onDone }: { onDone: (message: string) => void }) {
  const [term, setTerm] = useState("");
  const [contact, setContact] = useState<{ id: string; name: string } | null>(null);
  const [cadence, setCadence] = useState("weekly");
  const [days, setDays] = useState(7);
  const [sendIn, setSendIn] = useState("");

  const found = useQuery<{ contacts: Contact[] }>({
    queryKey: ["digest-contact-search", term],
    queryFn: () => api.get(`/api/contacts/search/?q=${encodeURIComponent(term)}`),
    enabled: term.trim().length > 1,
  });
  const run = useMutation({
    mutationFn: () => api.post<{ detail: string }>("/api/digests/generate-now/", {
      contact: contact!.id, cadence, days,
      ...(sendIn ? { send_in_minutes: Number(sendIn) } : {}),
    }),
    onSuccess: (r) => onDone(r.detail),
    onError: (e: Error) => onDone(e.message),
  });

  return (
    <Card title="Generate a digest now — development only">
      <p className="small">
        Runs the same generation the scheduler runs on Thursday, for one person over the
        period you choose. It creates a draft in the list below and sends nothing. This
        control does not exist once the app is off this laptop.
      </p>
      <div className="row">
        <Field label="Whose digest">
          {contact ? (
            <p className="small" style={{ margin: 0 }}>
              {contact.name}{" "}
              <button className="ghost small" onClick={() => setContact(null)}>change</button>
            </p>
          ) : (
            <input aria-label="Find a stakeholder" placeholder="Start typing a name…"
              value={term} onChange={(e) => setTerm(e.target.value)} />
          )}
        </Field>
        <Field label="Cadence">
          <select aria-label="Cadence" value={cadence} onChange={(e) => setCadence(e.target.value)}>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="every_update">On every update</option>
          </select>
        </Field>
        <Field label="Covering the last">
          <select aria-label="Period in days" value={days}
            onChange={(e) => setDays(Number(e.target.value))}>
            <option value={1}>1 day</option>
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
        </Field>
        <Field label="Send window">
          <select aria-label="Send window" value={sendIn}
            onChange={(e) => setSendIn(e.target.value)}>
            <option value="">The real one (next Friday)</option>
            <option value="2">In 2 minutes — to watch it expire or send</option>
            <option value="60">In an hour</option>
          </select>
        </Field>
        <button className="primary" disabled={!contact || run.isPending}
          onClick={() => run.mutate()}>Generate</button>
      </div>
      {!contact && (
        <ul className="small" style={{ listStyle: "none", paddingLeft: 0 }}>
          {(found.data?.contacts ?? []).slice(0, 6).map((c) => (
            <li key={c.id}>
              <button className="ghost small"
                onClick={() => setContact({ id: c.id, name: `${c.first_name} ${c.last_name}` })}>
                {c.first_name} {c.last_name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}


/** FR-3.29a — "Bryan Baker · every update · generates at 11:49 AM unless the task changes again". */
function comingUpLine(u: UpcomingDigest) {
  if (u.due) return `${u.contact.name} · every update · generates on the next tick`;
  const time = new Date(u.generates_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const which = u.tasks.length > 1 ? `any of these ${u.tasks.length} tasks changes` : "the task changes";
  return `${u.contact.name} · every update · generates at ${time} unless ${which} again`;
}
