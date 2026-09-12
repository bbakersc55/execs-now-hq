import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Card, Empty, Field, Pill, when } from "../components/ui";
import { Contact, DigestRow, Me, api } from "../lib/api";

const CAN_APPROVE = ["FF", "CF"];

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

  const digests = useQuery<DigestRow[]>({
    queryKey: ["digests"], queryFn: () => api.get<DigestRow[]>("/api/digests/"),
  });

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
      <h2>Digests awaiting approval</h2>
      <p className="sub">
        Nothing here has been sent. Every digest waits for a person while
        <span className="mono"> hold_all_digests</span> is on, which is the default — and an
        AI-written one waits even when it is off.
      </p>
      {note && <Banner kind="info">{note}</Banner>}

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
                sends {when(d.send_window_at)} · {d.item_count} update{d.item_count === 1 ? "" : "s"}{" "}
                {d.is_ai_generated ? <Pill kind="ai">AI narrative</Pill> : <Pill>plain list</Pill>}
              </p>

              {d.is_stale && (
                <Banner kind="warn">
                  <strong>Overtaken by events.</strong> {d.stale_reason} You can approve it as
                  it stands, or rebuild it with what has happened since.
                  <br />
                  <button onClick={() => act.mutate({ id: d.id, path: "regenerate" })}>
                    Regenerate
                  </button>
                </Banner>
              )}

              {editing === d.id ? (
                <>
                  <textarea aria-label="Digest text" rows={12} value={draft}
                    onChange={(e) => setDraft(e.target.value)} />
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
