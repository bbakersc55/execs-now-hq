import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Card, Empty, Pill, when } from "../components/ui";
import { DigestRow, Me, api } from "../lib/api";

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
