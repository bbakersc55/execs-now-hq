import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Company, Contact, Me, PlaybookRow, api } from "../lib/api";
import { Modal } from "./shell";
import { Banner, Card, Field, Pill } from "./ui";

interface PlaybooksState { playbooks: PlaybookRow[]; can_edit: boolean; next_monday: string }

const name = (p: Contact) => `${p.first_name} ${p.last_name}`.trim();

/** The practice's copy of a shipped playbook, made on first use (P8). */
async function copyOf(row: PlaybookRow): Promise<PlaybookRow> {
  if (row.id) return row;
  return api.post<PlaybookRow>("/api/playbooks/copy/", { key: row.key });
}

/**
 * "Start a playbook" on a company (P8): a goal, its projects and their tasks
 * from one of the practice's playbooks, with real dates from the start
 * date. The practice's person leads every item; the client's owner and
 * second-in-command are named for their tasks.
 */
export function StartPlaybookCard({ me, company, people }: {
  me: Me; company: Company; people: Contact[];
}) {
  const [open, setOpen] = useState(false);
  if (!(me.role === "FF" || me.role === "CF") || !company.is_client_company) return null;
  if (!(me.command_centers ?? []).length) return null;
  return (
    <Card title="Playbooks">
      <p className="small muted" style={{ marginTop: 0 }}>
        A goal with its projects and tasks, dated from the day you start.
      </p>
      <button className="small" onClick={() => setOpen(true)}>Start a playbook</button>
      {open && <StartPlaybook company={company} people={people} onClose={() => setOpen(false)} />}
    </Card>
  );
}

export function StartPlaybook({ company, people, onClose }: {
  company: Company; people: Contact[]; onClose: () => void;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const state = useQuery<PlaybooksState>({ queryKey: ["playbooks"],
    queryFn: () => api.get<PlaybooksState>("/api/playbooks/") });
  const [chosen, setChosen] = useState("");
  const [start, setStart] = useState("");
  const [owner, setOwner] = useState("");
  const [second, setSecond] = useState("");
  const [editing, setEditing] = useState<PlaybookRow | null>(null);
  const rows = state.data?.playbooks ?? [];
  const row = rows.find((p) => (p.id ?? p.key) === chosen);
  const go = useMutation({
    mutationFn: async () => {
      const playbook = await copyOf(row!);
      return api.post<{ goal: string; tasks: number }>("/api/playbooks/start/", {
        playbook: playbook.id, company: company.id,
        start_date: start || state.data!.next_monday,
        ...(owner ? { owner_contact: owner } : {}), ...(second ? { second_contact: second } : {}),
      });
    },
    onSuccess: (made) => {
      qc.invalidateQueries({ queryKey: ["playbooks"] });
      navigate(`/work/goals/${made.goal}`);
    },
  });
  const edit = useMutation({
    mutationFn: copyOf,
    onSuccess: (copy) => { qc.invalidateQueries({ queryKey: ["playbooks"] }); setEditing(copy);
      setChosen(copy.id ?? ""); },
  });
  return (
    <Modal label="Start a playbook" title={`Start a playbook at ${company.name}`} onClose={onClose}>
      {state.isError && <Banner kind="bad">{(state.error as Error).message}</Banner>}
      {go.isError && <Banner kind="bad">{(go.error as Error).message}</Banner>}
      {!state.data ? <p className="muted">Loading the playbooks…</p> : rows.length === 0 ? (
        <p>No playbooks yet. Turn on a Command Center in Settings to get its playbooks.</p>
      ) : (
        <>
          <Field label="Playbook">
            <select aria-label="Playbook" value={chosen} onChange={(e) => setChosen(e.target.value)}>
              <option value="">Choose a playbook</option>
              {rows.map((p) => (
                <option key={p.id ?? p.key} value={p.id ?? p.key}>
                  {p.name}{p.is_draft ? " (draft)" : ""}</option>
              ))}
            </select>
          </Field>
          {row && (
            <p className="small">
              {row.description} {row.weeks} weeks, {row.projects} projects, {row.tasks} tasks.{" "}
              {row.is_draft && <><Pill kind="warn">Draft, edit before first use</Pill>{" "}
                <button className="small ghost" onClick={() => edit.mutate(row)}>Edit it now</button></>}
            </p>
          )}
          <div className="row tight" style={{ flexWrap: "wrap" }}>
            <Field label="Start date">
              <input type="date" aria-label="Start date" value={start || state.data.next_monday}
                onChange={(e) => setStart(e.target.value)} />
            </Field>
            <Field label="Owner (client)">
              <select aria-label="The client's owner" value={owner} onChange={(e) => setOwner(e.target.value)}>
                <option value="">Not named</option>
                {people.map((p) => <option key={p.id} value={p.id}>{name(p)}</option>)}
              </select>
            </Field>
            <Field label="Second-in-command">
              <select aria-label="The client's second-in-command" value={second}
                onChange={(e) => setSecond(e.target.value)}>
                <option value="">Not named</option>
                {people.map((p) => <option key={p.id} value={p.id}>{name(p)}</option>)}
              </select>
            </Field>
          </div>
          <p className="small muted">You lead every item. Tasks for the owner or the
            second-in-command carry them as the client's owner.</p>
          <button className="primary" disabled={!row || row.is_draft || go.isPending}
            onClick={() => go.mutate()}>{go.isPending ? "Starting…" : "Start the playbook"}</button>
        </>
      )}
      {editing && <PlaybookEditor playbook={editing} onClose={() => setEditing(null)} />}
    </Modal>
  );
}

/** A playbook's outline, edited as text (P8). Saving it makes the copy the
 *  practice's own: it is no longer a draft. */
export function PlaybookEditor({ playbook, onClose }: { playbook: PlaybookRow; onClose: () => void }) {
  const qc = useQueryClient();
  const [d, setD] = useState({ name: playbook.name, description: playbook.description,
    outline: playbook.outline ?? "" });
  const save = useMutation({
    mutationFn: (ready: boolean) => api.patch<PlaybookRow>(`/api/playbooks/${playbook.id}/`,
      ready ? { ready: true } : d),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["playbooks"] });
      qc.invalidateQueries({ queryKey: ["command-center"] }); onClose(); },
  });
  return (
    <Modal label={`Edit ${playbook.name}`} title={`Edit: ${playbook.name}`} onClose={onClose} wide>
      {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
      {playbook.is_draft && <Banner kind="warn">Draft, edit before first use: change what does
        not fit your practice, then save.</Banner>}
      <Field label="Name"><input aria-label="Playbook name" value={d.name}
        onChange={(e) => setD({ ...d, name: e.target.value })} /></Field>
      <Field label="What it is for"><input aria-label="Playbook description" value={d.description}
        onChange={(e) => setD({ ...d, description: e.target.value })} /></Field>
      <Field label="Outline">
        <textarea className="outline-editor" aria-label="Playbook outline" value={d.outline}
          onChange={(e) => setD({ ...d, outline: e.target.value })} />
      </Field>
      <p className="small muted">"Goal:" names the goal and "Why:" says what it is for. "## Name |
        weeks 1-2" is a project; "- Task | week 1 | owner" is a task, its owner being owner,
        second-in-command or practice.</p>
      <div className="row tight">
        <button className="primary" disabled={save.isPending} onClick={() => save.mutate(false)}>Save</button>
        {playbook.is_draft && <button disabled={save.isPending} onClick={() => save.mutate(true)}>
          Mark ready as it is</button>}
        <button className="ghost" onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}
