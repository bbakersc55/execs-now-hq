import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { PageHead } from "../components/shell";
import { CodeAgain } from "../components/TwoFactor";
import { Banner, Card, Empty, Field, Pill, RowActions } from "../components/ui";
import {
  AccessEntryRow, AccessLogEntry, ChecklistFull, ChecklistItemRow, MyItemRow,
  PeoplePermissionsPage, PeopleScopePage, PeopleScopeRow, PeopleSetupPage, PersonPage,
  TemplateItemRow, ToSignRow, api,
} from "../lib/api";
import { dollars, longDate } from "../lib/money";
import { OrgChart } from "./Tools";

/**
 * 2026-11-17: the People Command Center's pages (apps/people). A page per
 * company, at each person's level: HR Director, HR Generalist (sensitive
 * fields masked), senior leadership's directory, a manager's reports, an
 * employee's own record. Permissions and the access log for the practice
 * owner and the client owner. Every People screen says "HR guidance, not
 * legal advice".
 *
 * The records (2026-11-17, later): the directory with search and filters, the
 * org chart from managers (the tools' own drawing), headcount by status, the
 * month's anniversaries and birthdays (day and month only); a person's page
 * by section; offer letters by e-signature; onboarding and offboarding
 * checklists whose items are tasks in Work; the access list and its revoke
 * tasks; the company's own checklist items and fields. Nothing sensitive is
 * in the directory: it is on the person's page, where opening it is logged.
 */

const GUIDANCE = "HR guidance, not legal advice";
const FIELD_LABELS: Record<string, string> = {
  pay_rate: "Pay rate", pay_unit: "Pay unit", pay_effective_on: "Pay effective",
  home_address: "Home address", date_of_birth: "Date of birth",
  personal_phone: "Personal phone", personal_email: "Personal email",
  emergency_contact: "Emergency contact", documents: "Documents",
  name: "Name", title: "Title", department: "Department", team: "Team",
  work_email: "Work email", work_phone: "Work phone", manager: "Manager",
  status: "Status", employment_type: "Employment type", work_state: "Work state",
  start_date: "Start date",
};
const STATUS_KIND: Record<string, string> = {
  offer_out: "warn", onboarding: "info", active: "ok", on_leave: "warn", offboarding: "warn",
  ended: "",
};
const UNITS: [string, string][] = [["hour", "an hour"], ["week", "a week"],
  ["month", "a month"], ["year", "a year"], ["project", "a project"]];
const TYPES: [string, string][] = [["full_time", "Employee, full-time"],
  ["part_time", "Employee, part-time"], ["contractor", "Contractor"]];
const ACCESS_KINDS: [string, string][] = [["system", "System"], ["email", "Email account"],
  ["phone", "Phone number"], ["equipment", "Equipment"], ["key", "Key"]];
const DOC_KINDS: [string, string][] = [["offer_letter", "Offer letter"],
  ["handbook", "Handbook acknowledgment"], ["review", "Review"],
  ["exit_interview", "Exit interview"], ["other", "Other"]];
const SECTIONS: ["people" | "it" | "manager", string][] = [["people", "People"], ["it", "IT"],
  ["manager", "Manager"]];
const ROLES: [string, string][] = [["hr", "Whoever starts it"], ["it", "The IT owner"],
  ["manager", "Their manager"], ["employee", "The person themself"]];

function failed(error: unknown): string {
  return (error as Error)?.message ?? "That didn't work.";
}

function day(iso: string | null | undefined): string {
  return iso ? longDate(iso.slice(0, 10)) : "";
}

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

type Tab = "people" | "chart" | "setup" | "permissions" | "log";

export function PeopleScope() {
  const { scope = "" } = useParams();
  const [tab, setTab] = useState<Tab>("people");
  const page = useQuery<PeopleScopePage>({
    queryKey: ["people", scope], queryFn: () => api.get(`/api/people/${scope}/`), retry: false });
  const p = page.data;
  const tabs: [Tab, string][] = p ? [
    ["people", "People"],
    ...(p.chart ? [["chart", "Org chart"] as [Tab, string]] : []),
    ...(p.may_run ? [["setup", "Checklists and fields"] as [Tab, string]] : []),
    ...(p.manages ? [["permissions", "Permissions"], ["log", "Access log"]] as [Tab, string][]
      : []),
  ] : [];
  return (
    <>
      <PageHead title={p ? `People · ${p.name}` : "People"}
        sub={p ? `Your access: ${p.level_label}` : undefined} />
      <Guidance />
      {page.isError && <Gate error={page.error} retry={() => page.refetch()} />}
      {p && (
        <>
          {tabs.length > 1 && (
            <div className="row tight" role="tablist" aria-label="People sections"
              style={{ flexWrap: "wrap" }}>
              {tabs.map(([t, label]) => (
                <button key={t} role="tab" aria-selected={tab === t}
                  className={tab === t ? "primary small" : "small"} onClick={() => setTab(t)}>
                  {label}</button>
              ))}
            </div>
          )}
          {tab === "people" && <Directory scope={scope} page={p} />}
          {tab === "chart" && p.chart && (
            <Card><OrgChart drawing={p.chart} title="The org chart, from managers" /></Card>)}
          {tab === "setup" && p.may_run && <Setup scope={scope} />}
          {tab === "permissions" && p.manages && <Permissions scope={scope} />}
          {tab === "log" && p.manages && <AccessLog scope={scope} />}
        </>
      )}
    </>
  );
}

function StatusPill({ row }: { row: { status?: string; status_label?: string } }) {
  if (!row.status) return null;
  return <Pill kind={STATUS_KIND[row.status] ?? ""}>{row.status_label}</Pill>;
}

function Directory({ scope, page }: { scope: string; page: PeopleScopePage }) {
  const [adding, setAdding] = useState(false);
  const [term, setTerm] = useState("");
  const [status, setStatus] = useState("");
  const [department, setDepartment] = useState("");
  const [kind, setKind] = useState("");
  const [state, setState] = useState("");
  const departments = useMemo(() => Array.from(new Set(page.records.map((r) => r.department)
    .filter(Boolean))).sort(), [page.records]);
  const states = useMemo(() => Array.from(new Set(page.records.map((r) => r.work_state ?? "")
    .filter(Boolean))).sort(), [page.records]);
  const seesEmployment = page.records.some((r) => r.status);
  const shown = page.records.filter((r) => {
    const text = `${r.name} ${r.title} ${r.department} ${r.team} ${r.work_email} ${
      r.manager?.name ?? ""}`.toLowerCase();
    return (!term || text.includes(term.toLowerCase())) && (!status || r.status === status)
      && (!department || r.department === department)
      && (!kind || r.employment_type === kind) && (!state || r.work_state === state);
  });
  return (
    <>
      <ToSign rows={page.to_sign} />
      <MyItems scope={scope} rows={page.my_items} />
      {(page.headcount || page.upcoming || page.client_users) && (
        <div className="grid two">
          {page.headcount && (
            <Card title="Headcount">
              <ul className="row tight" aria-label="Headcount by status"
                style={{ flexWrap: "wrap", listStyle: "none", padding: 0, margin: 0 }}>
                {page.headcount.map((h) => (
                  <li key={h.status}>
                    <button className={status === h.status ? "small primary" : "small"}
                      aria-pressed={status === h.status}
                      onClick={() => setStatus(status === h.status ? "" : h.status)}>
                      {h.label}: {h.count}</button>
                  </li>
                ))}
              </ul>
              {page.client_users && (
                <p className="small muted" style={{ marginBottom: 0 }}>
                  Client users here: {page.client_users.total} (portal sign-ins and employee
                  records, each person once), {page.client_users.blocks} block
                  {page.client_users.blocks === 1 ? "" : "s"} of {page.client_users.block_size}{" "}
                  at {dollars(1000)} a block.</p>
              )}
            </Card>
          )}
          {page.upcoming && <Upcoming upcoming={page.upcoming} />}
        </div>
      )}
      <Card title="People" actions={
        <div className="row tight" style={{ flexWrap: "wrap" }}>
          {page.may_export && (
            <a className="btn small" href={`/api/people/${scope}/export/`}>Export spreadsheet</a>)}
          {page.may_export_sensitive && (
            <a className="btn small" href={`/api/people/${scope}/export/?sensitive=1`}>
              Export with sensitive fields</a>)}
          {page.may_add && !adding && (
            <button className="small primary" onClick={() => setAdding(true)}>Add a person</button>)}
        </div>}>
        {page.level === "generalist" && (
          <p className="small muted" style={{ marginTop: 0 }}>As HR Generalist, sensitive
            fields are masked.</p>)}
        {adding && <AddPerson scope={scope} page={page} onDone={() => setAdding(false)} />}
        <div className="row tight" role="search" style={{ flexWrap: "wrap" }}>
          <Field label="Search">
            <input aria-label="Search people" value={term} placeholder="Name, title, team…"
              onChange={(e) => setTerm(e.target.value)} />
          </Field>
          {seesEmployment && (
            <Field label="Status">
              <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">Any</option>
                {(page.headcount ?? []).map((h) => (
                  <option key={h.status} value={h.status}>{h.label}</option>))}
              </select>
            </Field>
          )}
          {departments.length > 1 && (
            <Field label="Department">
              <select aria-label="Department" value={department}
                onChange={(e) => setDepartment(e.target.value)}>
                <option value="">Any</option>
                {departments.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </Field>
          )}
          {seesEmployment && (
            <Field label="Type">
              <select aria-label="Employment type" value={kind}
                onChange={(e) => setKind(e.target.value)}>
                <option value="">Any</option>
                {TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
              </select>
            </Field>
          )}
          {states.length > 1 && (
            <Field label="Work state">
              <select aria-label="Work state" value={state} onChange={(e) => setState(e.target.value)}>
                <option value="">Any</option>
                {states.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </Field>
          )}
        </div>
        {shown.length === 0 ? <Empty>No one here{term || status ? " matches" : " yet"}.</Empty> : (
          <div className="table-fit">
          <table className="cards-on-phone" aria-label="Directory">
            <thead><tr><th>Name</th><th>Title</th><th>Department</th><th>Team</th>
              <th>Work email</th><th>Manager</th>{seesEmployment && <th>Status</th>}</tr></thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.id}>
                  <td className="card-title"><Link to={`/people/${scope}/${r.id}`}>{r.name}</Link>
                    {r.own && <> <Pill>You</Pill></>}
                    {r.progress?.map((g) => (
                      <span key={g.id} className="small muted"> · {g.kind_label} {g.done + g.waived}
                        {" "}of {g.total}</span>))}</td>
                  <td data-label="Title">{r.title}</td>
                  <td data-label="Department">{r.department}</td>
                  <td data-label="Team">{r.team}</td>
                  <td data-label="Work email">{r.work_email}</td>
                  <td data-label="Manager">{r.manager?.name ?? ""}</td>
                  {seesEmployment && <td data-label="Status"><StatusPill row={r} /></td>}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </Card>
    </>
  );
}

function Upcoming({ upcoming }: { upcoming: NonNullable<PeopleScopePage["upcoming"]> }) {
  return (
    <Card title="The next 30 days">
      {upcoming.anniversaries.length === 0 && upcoming.birthdays.length === 0 ? (
        <Empty>No work anniversaries or birthdays coming up.</Empty>) : (
        <ul aria-label="Anniversaries and birthdays">
          {upcoming.anniversaries.map((a) => (
            <li key={`a-${a.id}`}>{a.name}: {a.years} year{a.years === 1 ? "" : "s"},{" "}
              {day(a.on)}</li>))}
          {upcoming.birthdays.map((b) => (
            <li key={`b-${b.id}`}>{b.name}: birthday, {b.day}</li>))}
        </ul>
      )}
    </Card>
  );
}

function ToSign({ rows }: { rows: ToSignRow[] }) {
  if (!rows.length) return null;
  return (
    <Card title="Documents for you to sign">
      <ul aria-label="Documents to sign">
        {rows.map((d) => (
          <li key={d.id}>{d.title} <Pill kind="warn">{d.state_label}</Pill>
            <span className="small muted"> The link to sign it is in the email
              {d.sent_at ? ` of ${day(d.sent_at)}` : ""}.</span></li>
        ))}
      </ul>
    </Card>
  );
}

function MyItems({ scope, rows }: { scope: string; rows: MyItemRow[] }) {
  const qc = useQueryClient();
  const done = useMutation({
    mutationFn: (id: string) => api.post(`/api/people/${scope}/items/${id}/done/`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["people", scope] }),
  });
  if (!rows.length) return null;
  return (
    <Card title="Checklist items for you">
      {done.isError && <Banner kind="bad">{failed(done.error)}</Banner>}
      <ul aria-label="Your checklist items">
        {rows.map((i) => (
          <li key={i.id} className="row tight" style={{ flexWrap: "wrap" }}>
            <span style={{ flex: "1 1 16rem", minWidth: 0 }}>{i.title} <span className="small muted">· {i.kind_label} of {i.person}
              {i.due_date ? `, due ${day(i.due_date)}` : ""}</span></span>
            <button className="small" disabled={done.isPending} onClick={() => done.mutate(i.id)}
              aria-label={`Done: ${i.title}`}>Done</button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

type Draft = Record<string, string>;

function PersonFields({ draft, set, page, managers, members }: {
  draft: Draft; set: (patch: Draft) => void; page?: PersonPage | null;
  managers: { id: string; name: string }[]; members?: { id: string; name: string }[];
}) {
  const text = (key: string, label: string, type = "text") => (
    <Field label={label}>
      <input aria-label={label} type={type} value={draft[key] ?? ""}
        onChange={(e) => set({ [key]: e.target.value })} />
    </Field>
  );
  return (
    <>
      <fieldset className="doc-fields"><legend>Directory</legend>
        {text("first_name", "First name")}{text("last_name", "Last name")}
        {text("title", "Title")}{text("department", "Department")}{text("team", "Team")}
        {text("work_email", "Work email", "email")}{text("work_phone", "Work phone")}
        <Field label="Manager">
          <select aria-label="Manager" value={draft.manager ?? ""}
            onChange={(e) => set({ manager: e.target.value })}>
            <option value="">None</option>
            {managers.filter((m) => m.id !== page?.id).map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>))}
          </select>
        </Field>
      </fieldset>
      <fieldset className="doc-fields"><legend>Employment</legend>
        <Field label="Employment type">
          <select aria-label="Employment type" value={draft.employment_type ?? "full_time"}
            onChange={(e) => set({ employment_type: e.target.value })}>
            {TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </Field>
        {text("work_state", "Work state (two letters)")}{text("start_date", "Start date", "date")}
        {members && (
          <Field label="Their portal sign-in">
            <select aria-label="Their portal sign-in" value={draft.member ?? ""}
              onChange={(e) => set({ member: e.target.value })}>
              <option value="">None (no sign-in)</option>
              {members.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </Field>
        )}
      </fieldset>
      <fieldset className="doc-fields"><legend>Pay (sensitive)</legend>
        {text("pay_rate", "Pay rate")}
        <Field label="Per">
          <select aria-label="Pay unit" value={draft.pay_unit ?? ""}
            onChange={(e) => set({ pay_unit: e.target.value })}>
            <option value="">Choose</option>
            {UNITS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </Field>
        {text("pay_effective_on", "Effective", "date")}
      </fieldset>
      <fieldset className="doc-fields"><legend>Personal (sensitive)</legend>
        {text("home_address", "Home address")}{text("date_of_birth", "Date of birth (optional)",
          "date")}
        {text("personal_phone", "Personal phone")}{text("personal_email", "Personal email",
          "email")}
        {text("emergency_contact", "Emergency contact (name, relationship, phone)")}
      </fieldset>
    </>
  );
}

const PLAIN = ["first_name", "last_name", "title", "department", "team", "work_email",
  "work_phone", "employment_type", "work_state", "start_date"];
const SENSITIVE = ["pay_rate", "pay_unit", "pay_effective_on", "home_address", "date_of_birth",
  "personal_phone", "personal_email", "emergency_contact"];

function body(draft: Draft) {
  const out: Record<string, unknown> = {};
  for (const k of PLAIN) if (k in draft) out[k] = draft[k];
  if ("manager" in draft) out.manager = draft.manager || null;
  if ("member" in draft) out.member = draft.member || null;
  const sensitive: Record<string, string> = {};
  for (const k of SENSITIVE) if (k in draft) sensitive[k] = draft[k];
  if (Object.keys(sensitive).length) out.sensitive = sensitive;
  const custom: Record<string, string> = {};
  for (const [k, v] of Object.entries(draft)) if (k.startsWith("custom:")) custom[k.slice(7)] = v;
  if (Object.keys(custom).length) out.custom = custom;
  return out;
}

function AddPerson({ scope, page, onDone }: {
  scope: string; page: PeopleScopePage; onDone: () => void;
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Draft>({ employment_type: "full_time" });
  const [offer, setOffer] = useState(false);
  const set = (patch: Draft) => setDraft({ ...draft, ...patch });
  const save = useMutation({
    mutationFn: () => api.post<PersonPage>(`/api/people/${scope}/records/`,
      { ...body(draft), offer }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["people", scope] }); onDone(); },
  });
  return (
    <form aria-label="Add a person" className="card-inset"
      onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      {save.isError && <Banner kind="bad">{failed(save.error)}</Banner>}
      <PersonFields draft={draft} set={set} managers={page.records} members={page.members} />
      <p className="small muted">{page.held_in_payroll}</p>
      {page.may_hire && (
        <label className="check"><input type="checkbox" checked={offer}
          onChange={(e) => setOffer(e.target.checked)} /> Hiring: start as "offer out", to send
          an offer letter from their page</label>
      )}
      <div className="row tight">
        <button className="primary" type="submit" disabled={!draft.first_name || save.isPending}>
          Add</button>
        <button className="ghost" type="button" onClick={onDone}>Cancel</button>
      </div>
    </form>
  );
}

// ------------------------------------------------------------ a person's page

export function PersonScreen() {
  const { scope = "", person = "" } = useParams();
  const key = ["person", scope, person];
  const page = useQuery<PersonPage>({ queryKey: key, retry: false,
    queryFn: () => api.get(`/api/people/${scope}/records/${person}/`) });
  const directory = useQuery<PeopleScopePage>({ queryKey: ["people", scope], retry: false,
    queryFn: () => api.get(`/api/people/${scope}/`), enabled: !!page.data?.may?.edit });
  const p = page.data;
  return (
    <>
      <PageHead title={p ? p.name : "Person"} sub={p?.title || undefined}
        action={<Link className="btn small" to={`/people/${scope}`}>All people</Link>} />
      <Guidance />
      {page.isError && <Gate error={page.error} retry={() => page.refetch()} />}
      {p && <PersonSections scope={scope} page={p} directory={directory.data} />}
    </>
  );
}

function Rows({ rows, label }: { rows: [string, React.ReactNode][]; label: string }) {
  return (
    <dl className="small" aria-label={label}>
      {rows.map(([k, v]) => (
        <div key={k} className="row tight">
          <dt className="muted" style={{ minWidth: "9rem" }}>{k}</dt>
          <dd style={{ margin: 0 }}>{v || <span className="muted">None</span>}</dd>
        </div>
      ))}
    </dl>
  );
}

function PersonSections({ scope, page, directory }: {
  scope: string; page: PersonPage; directory?: PeopleScopePage;
}) {
  const [editing, setEditing] = useState(false);
  const e = page.employment;
  const s = page.sensitive;
  const unit = UNITS.find(([v]) => v === s?.pay_unit)?.[1] ?? s?.pay_unit ?? "";
  return (
    <>
      <div className="grid two">
        <Card title="Directory" actions={page.may?.edit && !editing && (
          <button className="small" onClick={() => setEditing(true)}>Edit</button>)}>
          <Rows label="Directory fields" rows={[["Name", page.name], ["Title", page.title],
            ["Department", page.department], ["Team", page.team], ["Work email", page.work_email],
            ["Work phone", page.work_phone], ["Manager", page.manager?.name]]} />
          {page.progress && page.progress.length > 0 && (
            <p className="small">{page.progress.map((g) => `${g.kind_label}: ${g.done + g.waived}
              of ${g.total} done`).join(" · ")}</p>)}
        </Card>
        {e && (
          <Card title="Employment">
            <Rows label="Employment fields" rows={[["Status", <StatusPill key="s" row={e} />],
              ["Type", e.employment_type_label], ["Work state", e.work_state],
              ["Start date", day(e.start_date)], ...(e.ended_on ? [["Last day",
                day(e.ended_on)] as [string, string]] : []),
              ["Portal sign-in", e.has_sign_in ? "Yes" : "No"],
              ...(page.custom ?? []).map((c) => [c.label, c.value] as [string, string])]} />
          </Card>
        )}
      </div>
      {editing && directory && (
        <EditPerson scope={scope} page={page} directory={directory}
          onDone={() => setEditing(false)} />)}
      {s && (
        <div className="grid two">
          <Card title="Pay">
            {page.masked && <Pill kind="warn">Masked</Pill>}
            <Rows label="Pay" rows={[["Pay rate", page.masked ? s.pay_rate
              : `${s.pay_rate}${unit ? ` ${unit}` : ""}`],
              ["Effective", page.masked ? s.pay_effective_on : day(s.pay_effective_on)]]} />
          </Card>
          <Card title="Personal">
            {page.masked && <Pill kind="warn">Masked</Pill>}
            <Rows label="Personal details" rows={[["Home address", s.home_address],
              ["Date of birth", page.masked ? s.date_of_birth : day(s.date_of_birth)],
              ["Personal phone", s.personal_phone], ["Personal email", s.personal_email],
              ["Emergency contact", s.emergency_contact]]} />
            <p className="small muted" style={{ marginBottom: 0 }}>{page.held_in_payroll}</p>
          </Card>
        </div>
      )}
      {page.documents !== undefined && <Documents scope={scope} page={page} />}
      {page.to_sign && page.to_sign.length > 0 && <ToSign rows={page.to_sign} />}
      {page.access && <AccessList scope={scope} page={page} />}
      {page.checklists && <Checklists scope={scope} page={page} />}
    </>
  );
}

function EditPerson({ scope, page, directory, onDone }: {
  scope: string; page: PersonPage; directory: PeopleScopePage; onDone: () => void;
}) {
  const qc = useQueryClient();
  const s = page.sensitive;
  const [draft, setDraft] = useState<Draft>({
    first_name: page.first_name, last_name: page.last_name, title: page.title,
    department: page.department, team: page.team, work_email: page.work_email,
    work_phone: page.work_phone, manager: page.manager?.id ?? "",
    employment_type: page.employment?.employment_type ?? "full_time",
    work_state: page.employment?.work_state ?? "", start_date: page.employment?.start_date ?? "",
    ...(s && !page.masked ? s : {}),
  });
  const [status, setStatus] = useState(page.employment?.status ?? "");
  const save = useMutation({
    mutationFn: () => {
      const out = body(draft);
      if (status !== page.employment?.status) out.status = status;
      return api.patch(`/api/people/${scope}/records/${page.id}/`, out);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["person", scope, page.id] });
      qc.invalidateQueries({ queryKey: ["people", scope] });
      onDone();
    },
  });
  const canLeave = ["active", "on_leave"].includes(page.employment?.status ?? "");
  return (
    <Card title={`Edit ${page.name}`}>
      <form aria-label={`Edit ${page.name}`} onSubmit={(ev) => { ev.preventDefault(); save.mutate(); }}>
        {save.isError && <Banner kind="bad">{failed(save.error)}</Banner>}
        <PersonFields draft={draft} set={(patch) => setDraft({ ...draft, ...patch })} page={page}
          managers={directory.records} />
        {canLeave && (
          <Field label="Status">
            <select aria-label="Status" value={status} onChange={(ev) => setStatus(ev.target.value as typeof status)}>
              <option value="active">Active</option><option value="on_leave">On leave</option>
            </select>
          </Field>
        )}
        {(page.custom ?? []).length > 0 && (
          <fieldset className="doc-fields"><legend>The company's own fields</legend>
            {(page.custom ?? []).map((c) => (
              <Field key={c.id} label={c.label}>
                <input aria-label={c.label} value={draft[`custom:${c.id}`] ?? c.value}
                  onChange={(ev) => setDraft({ ...draft, [`custom:${c.id}`]: ev.target.value })} />
              </Field>
            ))}
          </fieldset>
        )}
        <div className="row tight">
          <button className="primary" type="submit" disabled={save.isPending}>Save</button>
          <button className="ghost" type="button" onClick={onDone}>Cancel</button>
        </div>
      </form>
    </Card>
  );
}

function Documents({ scope, page }: { scope: string; page: PersonPage }) {
  const qc = useQueryClient();
  const [kind, setKind] = useState("review");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [email, setEmail] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["person", scope, page.id] });
  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("kind", kind); form.append("title", title || file?.name || "");
      if (file) form.append("file", file);
      return api.post(`/api/people/${scope}/records/${page.id}/documents/`, form);
    },
    onSuccess: () => { setFile(null); setTitle(""); refresh(); },
  });
  const send = useMutation({
    mutationFn: (what: "offer" | "handbook") =>
      api.post<{ detail: string }>(`/api/people/${scope}/records/${page.id}/${what}/`,
        email ? { email } : {}),
    onSuccess: refresh,
  });
  const docs = page.documents;
  return (
    <Card title="Documents">
      {typeof docs === "string" ? (
        <p><Pill kind="warn">Masked</Pill> {docs || "None"}</p>
      ) : docs && docs.length > 0 ? (
        <ul aria-label="Their documents">
          {docs.map((d) => (
            <li key={d.id}>{d.title} <span className="small muted">· {d.kind_label}</span>
              {d.signature && <> <Pill kind={d.signature.state === "complete" ? "ok" : "warn"}>
                {d.signature.state_label}</Pill></>}
              {d.has_file && <> <a className="small" href={`/api/people/${scope}/documents/${d.id}/`}>
                Download</a></>}
            </li>
          ))}
        </ul>
      ) : <Empty>No documents yet.</Empty>}
      {(page.may?.offer || page.may?.handbook) && (
        <div className="row tight" style={{ flexWrap: "wrap" }}>
          {send.isError && <Banner kind="bad">{failed(send.error)}</Banner>}
          {send.isSuccess && <div role="status"><Banner kind="ok">{send.data.detail}</Banner></div>}
          <Field label="Send it to (email)">
            <input aria-label="Send it to" type="email" value={email}
              placeholder="Their email on file" onChange={(ev) => setEmail(ev.target.value)} />
          </Field>
          {page.may?.offer && (
            <button className="primary small" disabled={send.isPending}
              onClick={() => send.mutate("offer")}>Send the offer letter</button>)}
          {page.may?.handbook && (
            <button className="small" disabled={send.isPending}
              onClick={() => send.mutate("handbook")}>Send the handbook acknowledgment</button>)}
        </div>
      )}
      {page.may?.upload && (
        <form aria-label="Add a document" className="row tight" style={{ flexWrap: "wrap" }}
          onSubmit={(ev) => { ev.preventDefault(); if (file) upload.mutate(); }}>
          {upload.isError && <Banner kind="bad">{failed(upload.error)}</Banner>}
          <Field label="Kind">
            <select aria-label="Kind of document" value={kind} onChange={(ev) => setKind(ev.target.value)}>
              {DOC_KINDS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
          </Field>
          <Field label="Title">
            <input aria-label="Document title" value={title} onChange={(ev) => setTitle(ev.target.value)} />
          </Field>
          <Field label="File">
            <input aria-label="File" type="file" accept=".pdf,.docx,.png,.jpg,.jpeg"
              onChange={(ev) => setFile(ev.target.files?.[0] ?? null)} />
          </Field>
          <button className="small" type="submit" disabled={!file || upload.isPending}>Add</button>
          <p className="small muted" style={{ flexBasis: "100%" }}>Don't upload Social Security
            cards or numbers, bank details, I-9 documents, medical or leave paperwork, background
            checks or benefits forms: those are held in payroll, not here.</p>
        </form>
      )}
    </Card>
  );
}

function AccessList({ scope, page }: { scope: string; page: PersonPage }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState({ kind: "system", name: "", detail: "", given_on: "",
                                       given_by_name: "" });
  const add = useMutation({
    mutationFn: () => api.post<AccessEntryRow>(`/api/people/${scope}/records/${page.id}/access/`,
      draft),
    onSuccess: () => {
      setDraft({ ...draft, name: "", detail: "" });
      qc.invalidateQueries({ queryKey: ["person", scope, page.id] });
    },
  });
  const rows = page.access ?? [];
  return (
    <Card title="Access list">
      <p className="small muted" style={{ marginTop: 0 }}>Every system, email account, phone
        number, piece of equipment and key they were given. Offboarding makes a revoke task for
        each.</p>
      {rows.length === 0 ? <Empty>Nothing given yet.</Empty> : (
        <div className="table-fit">
        <table className="cards-on-phone" aria-label="Access list">
          <thead><tr><th>What</th><th>Kind</th><th>Given</th><th>By</th><th>Revoked</th></tr></thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id}>
                <td className="card-title">{a.name}{a.detail && <span className="small muted"> · {a.detail}</span>}</td>
                <td data-label="Kind">{a.kind_label}</td>
                <td data-label="Given">{day(a.given_on)}</td>
                <td data-label="By">{a.given_by}</td>
                <td data-label="Revoked">{a.revoked_at ? day(a.revoked_at) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
      {page.may?.run && (
        <form aria-label="Add to the access list" className="row tight" style={{ flexWrap: "wrap" }}
          onSubmit={(ev) => { ev.preventDefault(); add.mutate(); }}>
          {add.isError && <Banner kind="bad">{failed(add.error)}</Banner>}
          <Field label="Kind">
            <select aria-label="Kind of access" value={draft.kind}
              onChange={(ev) => setDraft({ ...draft, kind: ev.target.value })}>
              {ACCESS_KINDS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
          </Field>
          <Field label="What">
            <input aria-label="What was given" value={draft.name}
              onChange={(ev) => setDraft({ ...draft, name: ev.target.value })} />
          </Field>
          <Field label="Detail">
            <input aria-label="Detail" value={draft.detail}
              onChange={(ev) => setDraft({ ...draft, detail: ev.target.value })} />
          </Field>
          <Field label="Given on">
            <input aria-label="Given on" type="date" value={draft.given_on}
              onChange={(ev) => setDraft({ ...draft, given_on: ev.target.value })} />
          </Field>
          <Field label="By whom (if not you)">
            <input aria-label="By whom" value={draft.given_by_name}
              onChange={(ev) => setDraft({ ...draft, given_by_name: ev.target.value })} />
          </Field>
          <button className="small" type="submit" disabled={!draft.name || add.isPending}>Add</button>
        </form>
      )}
    </Card>
  );
}

function Checklists({ scope, page }: { scope: string; page: PersonPage }) {
  const open = (page.checklists ?? []).filter((c) => !c.closed_at);
  const kinds = new Set(open.map((c) => c.kind));
  const status = page.employment?.status;
  return (
    <>
      {(page.checklists ?? []).map((c) => <Checklist key={c.id} scope={scope} page={page} list={c} />)}
      {page.may?.run && (
        <div className="grid two">
          {!kinds.has("onboarding") && status && !["offboarding", "ended"].includes(status) && (
            <StartChecklist scope={scope} page={page} kind="onboarding" />)}
          {!kinds.has("offboarding") && status && !["offer_out", "ended"].includes(status) && (
            <StartChecklist scope={scope} page={page} kind="offboarding" />)}
        </div>
      )}
    </>
  );
}

function StartChecklist({ scope, page, kind }: {
  scope: string; page: PersonPage; kind: "onboarding" | "offboarding";
}) {
  const qc = useQueryClient();
  const [anchor, setAnchor] = useState(kind === "onboarding" ? page.employment?.start_date ?? ""
    : "");
  const [it, setIt] = useState("");
  const [reason, setReason] = useState("");
  const [custom, setCustom] = useState<Record<string, string>>({});
  const start = useMutation({
    mutationFn: () => api.post<ChecklistFull>(`/api/people/${scope}/records/${page.id}/checklists/`,
      { kind, anchor_date: anchor, it_owner: it || null, reason, custom }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["person", scope, page.id] }),
  });
  const fields = page.checklist_fields?.[kind] ?? [];
  const label = kind === "onboarding" ? "Start onboarding" : "Start offboarding";
  return (
    <Card title={label}>
      <form aria-label={label} onSubmit={(ev) => { ev.preventDefault(); start.mutate(); }}>
        {start.isError && <Banner kind="bad">{failed(start.error)}</Banner>}
        <Field label={kind === "onboarding" ? "Start date" : "Last day"}>
          <input aria-label={kind === "onboarding" ? "Start date" : "Last day"} type="date"
            value={anchor} onChange={(ev) => setAnchor(ev.target.value)} />
        </Field>
        {kind === "offboarding" && (
          <Field label="Reason">
            <select aria-label="Reason" value={reason} onChange={(ev) => setReason(ev.target.value)}>
              <option value="">Choose</option>
              {(page.reasons ?? []).map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </Field>
        )}
        <Field label="IT owner">
          <select aria-label="IT owner" value={it} onChange={(ev) => setIt(ev.target.value)}>
            <option value="">You</option>
            {(page.owners ?? []).map((o) => (
              <option key={o.id} value={o.id}>{o.name}{o.side === "client" ? " (client)" : ""}</option>))}
          </select>
        </Field>
        {fields.map((f) => (
          <Field key={f.id} label={f.label}>
            <input aria-label={f.label} value={custom[f.id] ?? ""}
              onChange={(ev) => setCustom({ ...custom, [f.id]: ev.target.value })} />
          </Field>
        ))}
        <p className="small muted">Each item becomes a task in Work, due from the
          {kind === "onboarding" ? " start date" : " last day"}.
          {kind === "offboarding" && " A revoke task is made for everything on the access list. This doesn't end anyone in payroll: a person does that in the payroll provider."}</p>
        <button className="primary small" type="submit"
          disabled={start.isPending || (kind === "offboarding" && (!anchor || !reason))}>
          {label}</button>
      </form>
    </Card>
  );
}

function Checklist({ scope, page, list }: { scope: string; page: PersonPage; list: ChecklistFull }) {
  const qc = useQueryClient();
  const [waiving, setWaiving] = useState("");
  const [note, setNote] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["person", scope, page.id] });
  const act = useMutation({
    mutationFn: ({ id, what }: { id: string; what: "done" | "waive" | "reopen" }) =>
      api.post<ChecklistItemRow>(`/api/people/${scope}/items/${id}/${what}/`,
        what === "waive" ? { note } : {}),
    onSuccess: () => { setWaiving(""); setNote(""); refresh(); },
  });
  const close = useMutation({
    mutationFn: () => api.post(`/api/people/${scope}/checklists/${list.id}/close/`, {}),
    onSuccess: () => { refresh(); qc.invalidateQueries({ queryKey: ["people", scope] }); },
  });
  const run = !!page.may?.run && !list.closed_at;
  const title = `${list.kind_label}${list.kind === "offboarding" ? `, last day ${day(list.anchor_date)}`
    : `, starting ${day(list.anchor_date)}`}`;
  return (
    <Card title={title} actions={<span className="small">{list.done + list.waived} of {list.total} done
      {list.closed_at && <> · <Pill kind="ok">Closed</Pill></>}</span>}>
      {list.reason_label && <p className="small" style={{ marginTop: 0 }}>Reason: {list.reason_label}</p>}
      {list.no_payroll && <p className="small muted" style={{ marginTop: 0 }}>{list.no_payroll}</p>}
      {list.custom.length > 0 && <Rows label="Checklist fields"
        rows={list.custom.map((c) => [c.label, c.value] as [string, string])} />}
      {(act.isError || close.isError) && (
        <Banner kind="bad">{failed(act.error ?? close.error)}</Banner>)}
      {SECTIONS.map(([section, label]) => {
        const items = list.items.filter((i) => i.section === section);
        if (!items.length) return null;
        return (
          <section key={section} aria-label={`${list.kind_label}: ${label}`}>
            <h4 style={{ marginBottom: ".25rem" }}>{label}</h4>
            <ul style={{ listStyle: "none", paddingLeft: 0, margin: 0 }}>
              {items.map((i) => (
                <li key={i.id} className="row tight" style={{ flexWrap: "wrap", padding: ".2rem 0" }}>
                  <span style={{ flex: "1 1 14rem" }}>
                    {i.done ? "✓ " : i.waived ? "– " : "○ "}{i.title}
                    <span className="small muted"> · {i.owner}{i.due_date ? `, due ${day(i.due_date)}` : ""}</span>
                    {i.waived && <span className="small muted"> · Waived: {i.waive_note}</span>}
                  </span>
                  {!list.closed_at && !i.done && !i.waived && (run || i.mine) && (
                    <button className="small" disabled={act.isPending}
                      aria-label={`Done: ${i.title}`}
                      onClick={() => act.mutate({ id: i.id, what: "done" })}>Done</button>)}
                  {run && !i.done && !i.waived && (
                    <button className="small ghost" aria-label={`Waive: ${i.title}`}
                      onClick={() => setWaiving(i.id)}>Waive</button>)}
                  {run && (i.done || i.waived) && (
                    <button className="small ghost" aria-label={`Reopen: ${i.title}`}
                      onClick={() => act.mutate({ id: i.id, what: "reopen" })}>Reopen</button>)}
                  {waiving === i.id && (
                    <form className="row tight" style={{ flexBasis: "100%" }}
                      aria-label={`Waive ${i.title}`}
                      onSubmit={(ev) => { ev.preventDefault(); act.mutate({ id: i.id, what: "waive" }); }}>
                      <input aria-label="Why it is waived" value={note} placeholder="Why (required)"
                        onChange={(ev) => setNote(ev.target.value)} />
                      <button className="small" type="submit" disabled={!note.trim()}>Waive it</button>
                    </form>
                  )}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
      {run && (
        <div className="row tight" style={{ marginTop: ".5rem" }}>
          <button className="primary small" disabled={!list.can_close || close.isPending}
            onClick={() => close.mutate()}>Close the {list.kind_label.toLowerCase()}</button>
          {!list.can_close && <span className="small muted">Each item is done, or waived with a
            note, before it closes.</span>}
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------ the company's setup

function Setup({ scope }: { scope: string }) {
  const qc = useQueryClient();
  const key = ["people-setup", scope];
  const setup = useQuery<PeopleSetupPage>({ queryKey: key, retry: false,
    queryFn: () => api.get(`/api/people/${scope}/setup/`) });
  const change = useMutation({
    mutationFn: ({ path, data }: { path: string; data: unknown }) =>
      api.post<PeopleSetupPage>(`/api/people/${scope}/setup/${path}`, data),
    onSuccess: (next) => qc.setQueryData(key, next),
  });
  if (setup.isError) return <Gate error={setup.error} retry={() => setup.refetch()} />;
  const s = setup.data;
  if (!s) return null;
  return (
    <>
      {change.isError && <Banner kind="bad">{failed(change.error)}</Banner>}
      {(["onboarding", "offboarding"] as const).map((kind) => (
        <TemplateCard key={kind} kind={kind} rows={s.items[kind]} busy={change.isPending}
          onChange={(path, data) => change.mutate({ path, data })} />
      ))}
      <Card title="The company's own fields">
        <p className="small muted" style={{ marginTop: 0 }}>{s.held_in_payroll} A field for any
          of those is refused.</p>
        {(["record", "onboarding", "offboarding"] as const).map((target) => (
          <FieldList key={target} target={target} rows={s.fields[target]} busy={change.isPending}
            onChange={(path, data) => change.mutate({ path, data })} />
        ))}
      </Card>
    </>
  );
}

function TemplateCard({ kind, rows, busy, onChange }: {
  kind: "onboarding" | "offboarding"; rows: TemplateItemRow[]; busy: boolean;
  onChange: (path: string, data: unknown) => void;
}) {
  const [draft, setDraft] = useState({ section: "people", title: "", owner_role: "hr",
                                       due_days: "0" });
  const move = (index: number, by: number) => {
    const ids = rows.map((r) => r.id);
    const [moved] = ids.splice(index, 1);
    ids.splice(index + by, 0, moved);
    onChange("items/reorder/", { kind, ids });
  };
  const label = kind === "onboarding" ? "Onboarding checklist" : "Offboarding checklist";
  return (
    <Card title={label}>
      <p className="small muted" style={{ marginTop: 0 }}>The People Command Center's standard
        items, as this company keeps them. Days count from the
        {kind === "onboarding" ? " start date" : " last day"} (minus is before).</p>
      <ul aria-label={label} style={{ listStyle: "none", paddingLeft: 0 }}>
        {rows.map((r, i) => (
          <li key={r.id}>
            <RowActions up={i > 0 ? { label: `Move up: ${r.title}`, onClick: () => move(i, -1),
                                      disabled: busy } : null}
              down={i < rows.length - 1 ? { label: `Move down: ${r.title}`,
                                            onClick: () => move(i, 1), disabled: busy } : null}
              remove={{ label: `Remove: ${r.title}`, disabled: busy,
                        onClick: () => onChange(`items/${r.id}/`, { archived: true }) }}>
              <span><Pill>{r.section_label}</Pill> {r.title}
                <span className="small muted"> · {r.owner_role_label}, day {r.due_days}</span></span>
            </RowActions>
          </li>
        ))}
      </ul>
      <form aria-label={`Add to the ${label.toLowerCase()}`} className="row tight"
        style={{ flexWrap: "wrap" }}
        onSubmit={(ev) => { ev.preventDefault();
          onChange("items/", { kind, ...draft, due_days: Number(draft.due_days) || 0 });
          setDraft({ ...draft, title: "" }); }}>
        <Field label="Section">
          <select aria-label="Section" value={draft.section}
            onChange={(ev) => setDraft({ ...draft, section: ev.target.value,
              owner_role: { people: "hr", it: "it", manager: "manager" }[ev.target.value] ?? "hr" })}>
            {SECTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field label="Item">
          <input aria-label="Item" value={draft.title}
            onChange={(ev) => setDraft({ ...draft, title: ev.target.value })} />
        </Field>
        <Field label="Goes to">
          <select aria-label="Goes to" value={draft.owner_role}
            onChange={(ev) => setDraft({ ...draft, owner_role: ev.target.value })}>
            {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field label="Day">
          <input aria-label="Day" type="number" value={draft.due_days} style={{ width: "5rem" }}
            onChange={(ev) => setDraft({ ...draft, due_days: ev.target.value })} />
        </Field>
        <button className="small" type="submit" disabled={!draft.title || busy}>Add</button>
      </form>
    </Card>
  );
}

function FieldList({ target, rows, busy, onChange }: {
  target: "record" | "onboarding" | "offboarding"; rows: { id: string; label: string }[];
  busy: boolean; onChange: (path: string, data: unknown) => void;
}) {
  const [label, setLabel] = useState("");
  const name = { record: "On the record", onboarding: "On onboarding",
                 offboarding: "On offboarding" }[target];
  const move = (index: number, by: number) => {
    const ids = rows.map((r) => r.id);
    const [moved] = ids.splice(index, 1);
    ids.splice(index + by, 0, moved);
    onChange("fields/reorder/", { target, ids });
  };
  return (
    <section aria-label={`Fields ${name.toLowerCase()}`}>
      <h4 style={{ marginBottom: ".25rem" }}>{name}</h4>
      {rows.length === 0 ? <Empty>None yet.</Empty> : (
        <ul style={{ listStyle: "none", paddingLeft: 0 }}>
          {rows.map((r, i) => (
            <li key={r.id}>
              <RowActions up={i > 0 ? { label: `Move up: ${r.label}`, onClick: () => move(i, -1) } : null}
                down={i < rows.length - 1 ? { label: `Move down: ${r.label}`, onClick: () => move(i, 1) } : null}
                remove={{ label: `Remove: ${r.label}`, disabled: busy,
                          onClick: () => onChange(`fields/${r.id}/`, { archived: true }) }}>
                <span>{r.label}</span>
              </RowActions>
            </li>
          ))}
        </ul>
      )}
      <form className="row tight" aria-label={`Add a field ${name.toLowerCase()}`}
        onSubmit={(ev) => { ev.preventDefault(); onChange("fields/", { target, label }); setLabel(""); }}>
        <input aria-label={`New field ${name.toLowerCase()}`} value={label}
          onChange={(ev) => setLabel(ev.target.value)} />
        <button className="small" type="submit" disabled={!label.trim() || busy}>Add</button>
      </form>
    </section>
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
