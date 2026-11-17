import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { PageHead } from "../components/shell";
import { CodeAgain } from "../components/TwoFactor";
import { Banner, Card, Empty, Field, Pill } from "../components/ui";
import {
  AccessLogEntry, PeoplePermissionsPage, PeopleScopePage, PeopleScopeRow, PersonRow, api,
} from "../lib/api";

/**
 * 2026-11-17: the People Command Center's pages (apps/people). A page per
 * company, at each person's level: HR Director, HR Generalist (sensitive
 * fields masked), senior leadership's directory, a manager's reports, an
 * employee's own record. Permissions and the access log for the practice
 * owner and the client owner. Every People screen says "HR guidance, not
 * legal advice". The records are placeholders until the next build.
 */

const GUIDANCE = "HR guidance, not legal advice";
const FIELD_LABELS: Record<string, string> = {
  pay_rate: "Pay rate", home_address: "Home address", date_of_birth: "Date of birth",
  personal_phone: "Personal phone", personal_email: "Personal email",
  emergency_contact: "Emergency contact", documents: "Documents",
};

type Refusal = { status?: number; data?: { two_factor?: string; detail?: string } };

/** A People screen's two-factor gates: enroll first, or the code again. */
function Gate({ error, retry }: { error: unknown; retry: () => void }) {
  const e = error as Refusal;
  if (e?.data?.two_factor === "enroll") {
    return (
      <Card title="Set up two-factor sign-in first">
        <p style={{ marginTop: 0 }}>{e.data.detail}</p>
        <Link className="btn primary" to="/profile">Go to Profile</Link>
      </Card>
    );
  }
  if (e?.data?.two_factor === "recheck") {
    return <CodeAgain message={e.data.detail ?? ""} onDone={retry} />;
  }
  return <Empty>Nothing here.</Empty>;
}

function Guidance() {
  return <p className="small muted" role="note" style={{ marginTop: 0 }}>{GUIDANCE}.</p>;
}

export function PeopleHome() {
  const home = useQuery<{ guidance: string; scopes: PeopleScopeRow[] }>({
    queryKey: ["people-home"], queryFn: () => api.get("/api/people/"), retry: false });
  return (
    <>
      <PageHead title="People" sub="Each company's people, at your level of access." />
      <Guidance />
      {home.isError ? <Gate error={home.error} retry={() => home.refetch()} /> : (
        <Card>
          <ul aria-label="Companies">
            {(home.data?.scopes ?? []).map((s) => (
              <li key={s.key}>
                <Link to={`/people/${s.key}`}>{s.name}</Link>{" "}
                <Pill>{s.level_label}</Pill>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}

export function PeopleScope() {
  const { scope = "" } = useParams();
  const [tab, setTab] = useState<"people" | "permissions" | "log">("people");
  const page = useQuery<PeopleScopePage>({
    queryKey: ["people", scope], queryFn: () => api.get(`/api/people/${scope}/`), retry: false });
  const p = page.data;
  return (
    <>
      <PageHead title={p ? `People · ${p.name}` : "People"}
        sub={p ? `Your access: ${p.level_label}` : undefined} />
      <Guidance />
      {page.isError && <Gate error={page.error} retry={() => page.refetch()} />}
      {p && (
        <>
          {p.manages && (
            <div className="row tight" role="tablist" aria-label="People sections">
              {(["people", "permissions", "log"] as const).map((t) => (
                <button key={t} role="tab" aria-selected={tab === t}
                  className={tab === t ? "primary small" : "small"} onClick={() => setTab(t)}>
                  {t === "people" ? "People" : t === "permissions" ? "Permissions"
                    : "Access log"}</button>
              ))}
            </div>
          )}
          {tab === "people" && <PeopleList scope={scope} page={p} />}
          {tab === "permissions" && p.manages && <Permissions scope={scope} />}
          {tab === "log" && p.manages && <AccessLog scope={scope} />}
        </>
      )}
    </>
  );
}

function Sensitive({ person }: { person: PersonRow }) {
  if (!person.sensitive) return null;
  return (
    <dl className="small" aria-label={`Sensitive details of ${person.name}`}>
      {Object.entries(person.sensitive).map(([key, value]) => (
        <div key={key} className="row tight">
          <dt className="muted">{FIELD_LABELS[key] ?? key}</dt>
          <dd style={{ margin: 0 }}>{Array.isArray(value) ? value.join(", ") || "None"
            : value || "None"}</dd>
        </div>
      ))}
    </dl>
  );
}

function PeopleList({ scope, page }: { scope: string; page: PeopleScopePage }) {
  const [adding, setAdding] = useState(false);
  return (
    <Card title="People" actions={
      <div className="row tight">
        {page.may_export && (
          <a className="btn small" href={`/api/people/${scope}/export/`}>Export (CSV)</a>)}
        {page.may_add && !adding && (
          <button className="small" onClick={() => setAdding(true)}>Add a placeholder
            person</button>)}
      </div>}>
      <p className="small muted" style={{ marginTop: 0 }}>Placeholder records, to prove who
        reaches what. The employee records arrive in the next build.
        {page.level === "generalist" && " As HR Generalist, sensitive fields are masked."}</p>
      {adding && <AddPerson scope={scope} page={page} onDone={() => setAdding(false)} />}
      {page.records.length === 0 ? <Empty>No one here yet.</Empty> : (
        <table className="cards-on-phone">
          <thead><tr><th>Name</th><th>Title</th><th>Team</th><th>Work email</th>
            <th>Manager</th><th>Sensitive</th></tr></thead>
          <tbody>
            {page.records.map((r) => (
              <tr key={r.id}>
                <td className="card-title">{r.name}{r.own && <> <Pill>You</Pill></>}</td>
                <td data-label="Title">{r.title}</td>
                <td data-label="Team">{r.team}</td>
                <td data-label="Work email">{r.work_email}</td>
                <td data-label="Manager">{r.manager?.name ?? ""}</td>
                <td data-label="Sensitive">{r.sensitive ? <>
                  {r.masked && <Pill kind="warn">Masked</Pill>}<Sensitive person={r} /></>
                  : <span className="muted small">Directory only</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function AddPerson({ scope, page, onDone }: {
  scope: string; page: PeopleScopePage; onDone: () => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ first_name: "", last_name: "", title: "", team: "",
                                     work_email: "", manager: "", member: "", pay_rate: "" });
  const set = (patch: Partial<typeof form>) => setForm({ ...form, ...patch });
  const save = useMutation({
    mutationFn: () => api.post(`/api/people/${scope}/records/`, {
      first_name: form.first_name, last_name: form.last_name, title: form.title,
      team: form.team, work_email: form.work_email, manager: form.manager || null,
      member: form.member || null, sensitive: { pay_rate: form.pay_rate } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["people", scope] }); onDone(); },
  });
  return (
    <form aria-label="Add a placeholder person" className="card-inset"
      onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
      <div className="row" style={{ flexWrap: "wrap" }}>
        {(["first_name", "last_name", "title", "team", "work_email"] as const).map((k) => (
          <Field key={k} label={k.replace("_", " ").replace(/^./, (c) => c.toUpperCase())}>
            <input aria-label={k.replace("_", " ")} value={form[k]}
              onChange={(e) => set({ [k]: e.target.value })} />
          </Field>
        ))}
        <Field label="Manager">
          <select aria-label="Manager" value={form.manager}
            onChange={(e) => set({ manager: e.target.value })}>
            <option value="">None</option>
            {page.records.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </Field>
        <Field label="Their sign-in">
          <select aria-label="Their sign-in" value={form.member}
            onChange={(e) => set({ member: e.target.value })}>
            <option value="">None</option>
            {page.members.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </Field>
        <Field label="Pay rate (sensitive)">
          <input aria-label="Pay rate" value={form.pay_rate}
            onChange={(e) => set({ pay_rate: e.target.value })} />
        </Field>
      </div>
      <div className="row tight">
        <button className="primary" type="submit" disabled={!form.first_name || save.isPending}>
          Add</button>
        <button className="ghost" type="button" onClick={onDone}>Cancel</button>
      </div>
    </form>
  );
}

function Permissions({ scope }: { scope: string }) {
  const qc = useQueryClient();
  const page = useQuery<PeoplePermissionsPage>({
    queryKey: ["people-permissions", scope],
    queryFn: () => api.get(`/api/people/${scope}/permissions/`), retry: false });
  const [member, setMember] = useState("");
  const [level, setLevel] = useState<"generalist" | "director">("generalist");
  const [all, setAll] = useState(false);
  const done = () => qc.invalidateQueries({ queryKey: ["people-permissions", scope] });
  const grant = useMutation({
    mutationFn: () => api.post(`/api/people/${scope}/permissions/`, { member, level, all }),
    onSuccess: () => { setMember(""); done(); } });
  const revoke = useMutation({
    mutationFn: (id: string) => api.post(`/api/people/${scope}/permissions/${id}/revoke/`, {}),
    onSuccess: done });
  const p = page.data;
  if (page.isError) return <Gate error={page.error} retry={() => page.refetch()} />;
  if (!p) return null;
  return (
    <Card title="HR permissions">
      <p className="small muted" style={{ marginTop: 0 }}>HR Director sees everything the app
        holds; HR Generalist sees sensitive fields masked. Whoever holds one must use
        two-factor sign-in.</p>
      {grant.isError && <Banner kind="bad">{(grant.error as Error).message}</Banner>}
      {p.grants.length === 0 ? <Empty>No one has been given an HR permission here.</Empty> : (
        <ul aria-label="HR permissions">
          {p.grants.map((g) => (
            <li key={g.id} className="row tight" style={{ flexWrap: "wrap" }}>
              <span>{g.user} · {g.level_label} · <span className="muted">{g.scope_label}</span>
                {!g.two_factor && <> <Pill kind="warn">Two-factor not set up yet</Pill></>}</span>
              <button className="small ghost" aria-label={`Take back ${g.user}'s permission`}
                disabled={revoke.isPending} onClick={() => revoke.mutate(g.id)}>Take back</button>
            </li>
          ))}
        </ul>
      )}
      {p.grantable.length > 0 && (
        <form className="row tight" style={{ flexWrap: "wrap" }} aria-label="Give an HR permission"
          onSubmit={(e) => { e.preventDefault(); if (member) grant.mutate(); }}>
          <Field label="Who">
            <select aria-label="Who" value={member} onChange={(e) => setMember(e.target.value)}>
              <option value="">Choose</option>
              {p.grantable.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </Field>
          <Field label="Level">
            <select aria-label="Level" value={level}
              onChange={(e) => setLevel(e.target.value as "generalist" | "director")}>
              <option value="generalist">HR Generalist</option>
              <option value="director">HR Director</option>
            </select>
          </Field>
          {p.may_grant_all && (
            <label className="check small"><input type="checkbox" checked={all}
              onChange={(e) => setAll(e.target.checked)} /> For all: the practice and every
              client</label>
          )}
          <button className="primary small" type="submit" disabled={!member || grant.isPending}>
            Give it</button>
        </form>
      )}
    </Card>
  );
}

function AccessLog({ scope }: { scope: string }) {
  const log = useQuery<{ entries: AccessLogEntry[] }>({
    queryKey: ["people-log", scope], queryFn: () => api.get(`/api/people/${scope}/access-log/`),
    retry: false });
  if (log.isError) return <Gate error={log.error} retry={() => log.refetch()} />;
  const rows = log.data?.entries ?? [];
  return (
    <Card title="Access log">
      <p className="small muted" style={{ marginTop: 0 }}>Every view, change and export of a
        person's sensitive details: who, when, whose, which fields, from where. Nobody can
        edit it.</p>
      {rows.length === 0 ? <Empty>Nothing yet.</Empty> : (
        <table className="cards-on-phone" aria-label="Access log entries">
          <thead><tr><th>When</th><th>Who</th><th>What</th><th>Whose</th><th>Fields</th>
            <th>From</th></tr></thead>
          <tbody>
            {rows.map((e, i) => (
              <tr key={i}>
                <td className="card-title">{new Date(e.at).toLocaleString()}</td>
                <td data-label="Who">{e.who}</td>
                <td data-label="What">{e.action_label}</td>
                <td data-label="Whose">{e.person}</td>
                <td data-label="Fields">{e.fields.map((f) => FIELD_LABELS[f] ?? f).join(", ")}</td>
                <td data-label="From"><span className="small">{e.from}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
