/** An intake form's settings: its look and address, what owners are offered,
 *  Track's custom fields, the sleeps table, the checklist and the messages.
 *  For the practice owner and the company's managers and above. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Banner, Card, Field, Pill, when } from "../components/ui";
import type { Me } from "../lib/api";
import { intake, type FormSettings } from "../lib/intake";

type S = FormSettings["settings"];
const COLORS: [string, string][] = [["primary", "Buttons and highlights"],
  ["primary_dark", "Hover and links"], ["heading", "Headings"], ["text", "Text"],
  ["background", "Page background"], ["accent", "Notes"], ["error", "Errors"]];
const DEFAULT_COLORS: Record<string, string> = { primary: "#428227", primary_dark: "#356A1F",
  heading: "#36424A", text: "#4A4A4A", background: "#FAF9F5", accent: "#006BA6",
  error: "#B3261E" };
const SECTIONS = [["about", "About you"], ["property", "The property"], ["amenities", "Amenities"],
  ["home", "Home details"]];

export function IntakeSettings({ me: _me }: { me: Me }) {
  const { companyId = "" } = useParams();
  const qc = useQueryClient();
  const { data, error } = useQuery({ queryKey: ["intake-form", companyId],
                                     queryFn: () => intake.form(companyId) });
  const [draft, setDraft] = useState<FormSettings | null>(null);
  const [said, setSaid] = useState("");
  const [problem, setProblem] = useState("");
  useEffect(() => { if (data) setDraft(data); }, [data]);
  if (error) return <div className="page"><Banner kind="warn">{(error as Error).message}</Banner>
    </div>;
  if (!draft) return <div className="page"><p className="muted">Loading…</p></div>;
  const s = draft.settings;
  const setS = (patch: Partial<S>) => setDraft({ ...draft, settings: { ...s, ...patch } });
  const save = async (body: Record<string, unknown>) => {
    setProblem("");
    try {
      const out = await intake.saveForm(companyId, body);
      qc.setQueryData(["intake-form", companyId], out);
      setDraft(out);
      setSaid("Saved.");
      window.setTimeout(() => setSaid(""), 2500);
    } catch (e) {
      setProblem((e as Error).message);
    }
  };
  const amenities = (draft.lists.amenities ?? []) as { id: number; name: string; group: string }[];
  const groups = [...new Set(amenities.map((a) => a.group))].sort();
  const beds = (draft.lists.bed_types ?? []) as { id: number; name: string; isActive: boolean }[];
  const fields = (draft.lists.custom_fields ?? []) as unknown as { reference: string;
    name: string; type: string }[];
  return (
    <div className="page">
      <p className="muted small" style={{ margin: 0 }}><Link to={`/intake?company=${companyId}`}>
        Owner intake</Link></p>
      <div className="spread"><h1 style={{ margin: ".25rem 0" }}>Form settings</h1>
        <span className="small" aria-live="polite">{said}</span></div>
      {problem && <Banner kind="warn">{problem}</Banner>}
      {draft.warning && <Banner kind="warn">{draft.warning}</Banner>}

      <Card title="Look and address">
        <div className="intake-choices">
          <Field label="Company name owners see"><input value={draft.brand_name}
            onChange={(e) => setDraft({ ...draft, brand_name: e.target.value })} /></Field>
          <Field label="Form title"><input value={draft.title}
            onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></Field>
          <Field label="Contact phone (footer)"><input value={draft.contact_phone}
            onChange={(e) => setDraft({ ...draft, contact_phone: e.target.value })} /></Field>
          <Field label="Contact email (footer)"><input value={draft.contact_email}
            onChange={(e) => setDraft({ ...draft, contact_email: e.target.value })} /></Field>
          <Field label="Address slug"><input value={draft.slug}
            onChange={(e) => setDraft({ ...draft, slug: e.target.value })} /></Field>
          <Field label="The form's own domain"><input value={draft.domain}
            placeholder="owners.example-company.com"
            onChange={(e) => setDraft({ ...draft, domain: e.target.value })} /></Field>
        </div>
        <p className="muted small">Links look like <span className="mono">{draft.base}/…</span>.
          A domain also needs adding in Railway and DNS; see the intake forms guide.</p>
        <h4>Colours</h4>
        <div className="intake-colors">
          {COLORS.map(([key, label]) => (
            <label key={key}><input type="color" value={draft.colors[key] ?? DEFAULT_COLORS[key]}
              onChange={(e) => setDraft({ ...draft, colors: { ...draft.colors,
                [key]: e.target.value } })} /> {label}</label>
          ))}
        </div>
        <h4>Logo and tab icon</h4>
        <div className="row wrap" style={{ gap: "1rem" }}>
          {(["logo", "icon"] as const).map((which) => (
            <label key={which} className="small">{which === "logo" ? "Logo" : "Tab icon"}
              {(which === "logo" ? draft.has_logo : draft.has_icon) && <> <Pill kind="ok">set
              </Pill></>}<br />
              <input type="file" accept=".png,.jpg,.jpeg,.svg" onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                try {
                  await intake.uploadImage(companyId, which, file);
                  await qc.invalidateQueries({ queryKey: ["intake-form", companyId] });
                } catch (err) { setProblem((err as Error).message); }
              }} /></label>
          ))}
        </div>
        <button type="button" className="primary" onClick={() => void save({
          brand_name: draft.brand_name, title: draft.title, contact_phone: draft.contact_phone,
          contact_email: draft.contact_email, slug: draft.slug, domain: draft.domain,
          colors: draft.colors })}>Save look and address</button>
      </Card>

      <Card title="Track's lists" actions={<button type="button" className="ghost small"
        onClick={async () => {
          try {
            const out = await intake.refresh(companyId);
            setDraft(out);
            qc.setQueryData(["intake-form", companyId], out);
          } catch (e) { setProblem((e as Error).message); }
        }}>Refresh from Track now</button>}>
        <p className="small" style={{ margin: 0 }}>Choices are read from Track about once an hour.
          Last read {when(draft.lists_status.fetched_at)}.
          {draft.lists_status.error && ` The last try failed: ${draft.lists_status.error}`}</p>
      </Card>

      <Card title="What owners are offered">
        <h4>New units start as</h4>
        <label className="intake-inline"><input type="radio" checked={!s.new_units_bookable}
          onChange={() => setS({ new_units_bookable: false })} /> Not bookable (inactive)</label>
        <label className="intake-inline"><input type="radio" checked={s.new_units_bookable}
          onChange={() => setS({ new_units_bookable: true })} /> Bookable (still inactive)</label>
        <h4>Owners are created</h4>
        <label className="intake-inline"><input type="radio" checked={s.owner_active}
          onChange={() => setS({ owner_active: true })} /> Active</label>
        <label className="intake-inline"><input type="radio" checked={!s.owner_active}
          onChange={() => setS({ owner_active: false })} /> Inactive</label>
        <h4>Common amenities (shown first)</h4>
        {s.common_amenities.map((c, i) => (
          <div key={i} className="intake-common">
            <input value={c.label} aria-label="Label owners see" onChange={(e) => setS({
              common_amenities: s.common_amenities.map((x, j) => (j === i ? { ...x,
                label: e.target.value } : x)) })} />
            <span className="muted small">{c.amenity_ids.map((id) => amenities.find((a) =>
              a.id === id)?.name ?? id).join(", ")}</span>
            <button type="button" className="link" onClick={() => setS({ common_amenities:
              s.common_amenities.filter((_, j) => j !== i) })}>Remove</button>
          </div>
        ))}
        <AddCommon amenities={amenities} onAdd={(label, ids) => setS({ common_amenities: [
          ...s.common_amenities, { key: `c${Date.now()}`, label, amenity_ids: ids }] })} />
        <h4>Amenity groups owners may see</h4>
        <div className="intake-checks">{groups.map((g) => (
          <label key={g}><input type="checkbox" checked={!s.hidden_groups.includes(g)}
            onChange={() => setS({ hidden_groups: s.hidden_groups.includes(g)
              ? s.hidden_groups.filter((x) => x !== g) : [...s.hidden_groups, g] })} /> {g}</label>
        ))}</div>
        <h4>Property types offered</h4>
        <div className="intake-checks">{(draft.lists.lodging_types ?? []).map((t) => (
          <label key={t.id}><input type="checkbox" checked={s.lodging_type_ids.includes(t.id)}
            onChange={() => setS({ lodging_type_ids: s.lodging_type_ids.includes(t.id)
              ? s.lodging_type_ids.filter((x) => x !== t.id) : [...s.lodging_type_ids, t.id] })} />
            {" "}{t.name}</label>
        ))}</div>
        <h4>Code types offered for "Add another code"</h4>
        <div className="intake-checks">{(draft.lists.code_types ?? []).map((t) => (
          <label key={t.id}><input type="checkbox" checked={s.code_type_ids.includes(t.id)}
            onChange={() => setS({ code_type_ids: s.code_type_ids.includes(t.id)
              ? s.code_type_ids.filter((x) => x !== t.id) : [...s.code_type_ids, t.id] })} />
            {" "}{t.name}</label>
        ))}</div>
        <button type="button" className="primary" onClick={() => void save({ settings: {
          new_units_bookable: s.new_units_bookable, owner_active: s.owner_active,
          common_amenities: s.common_amenities, hidden_groups: s.hidden_groups,
          lodging_type_ids: s.lodging_type_ids, code_type_ids: s.code_type_ids } })}>
          Save</button>
      </Card>

      <Card title="Track's unit custom fields">
        <p className="muted small" style={{ marginTop: 0 }}>Off; the owner answers it (with your
          label, help and section); or staff fill it in at review. Fields marked "built in" have
          their own question on the form.</p>
        <table className="table small">
          <thead><tr><th>Field</th><th>Who fills it</th><th>Label for owners</th><th>Help</th>
            <th>Section</th></tr></thead>
          <tbody>
            {fields.map((f) => {
              const row = s.custom_fields[f.reference] ?? { state: "off", label: f.name,
                help: "", section: "home" };
              const set = (patch: Partial<typeof row>) => setS({ custom_fields: {
                ...s.custom_fields, [f.reference]: { ...row, ...patch } } });
              const builtin = draft.builtin_fields[f.reference];
              return (
                <tr key={f.reference}>
                  <td>{f.name}<span className="muted"> · {f.type}</span>
                    {builtin && <span className="muted"> · built in</span>}</td>
                  <td><select value={row.state} onChange={(e) => set({ state: e.target.value })}>
                    <option value="off">Off</option><option value="owner">Owner answers</option>
                    <option value="staff">Staff at review</option></select></td>
                  <td>{!builtin && row.state === "owner" && <input value={row.label}
                    onChange={(e) => set({ label: e.target.value })} />}</td>
                  <td>{!builtin && row.state === "owner" && <input value={row.help}
                    onChange={(e) => set({ help: e.target.value })} />}</td>
                  <td>{!builtin && row.state === "owner" && <select value={row.section}
                    onChange={(e) => set({ section: e.target.value })}>
                    {SECTIONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <button type="button" className="primary" onClick={() => void save({ settings: {
          custom_fields: s.custom_fields } })}>Save custom fields</button>
      </Card>

      <Card title="Sleeps per bed">
        <table className="table small">
          <thead><tr><th>Track's bed type</th><th>Sleeps</th><th>Label owners see</th>
            <th>Sofa-type bed</th><th /></tr></thead>
          <tbody>
            {beds.map((b) => {
              const row = s.sleeps[String(b.id)] ?? { sleeps: 2, label: b.name, confirmed: false,
                other_places: false };
              const set = (patch: Partial<typeof row>) => setS({ sleeps: { ...s.sleeps,
                [String(b.id)]: { ...row, ...patch } } });
              return (
                <tr key={b.id}>
                  <td>{b.name}{!b.isActive && <span className="muted"> · inactive</span>}</td>
                  <td><input type="number" min={0} max={8} style={{ width: "4.5rem" }}
                    value={row.sleeps} onChange={(e) => set({ sleeps: Number(e.target.value),
                      confirmed: true })} /></td>
                  <td><input value={row.label} onChange={(e) => set({ label: e.target.value })} />
                  </td>
                  <td><input type="checkbox" checked={row.other_places} aria-label="Offered for
                    other places people sleep" onChange={() => set({ other_places:
                      !row.other_places })} /></td>
                  <td>{!row.confirmed && <><Pill kind="warn">New in Track</Pill>{" "}
                    <button type="button" className="link" onClick={() => set({ confirmed: true })}>
                      Confirm</button></>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <button type="button" className="primary" onClick={() => void save({ settings: {
          sleeps: s.sleeps } })}>Save sleeps</button>
      </Card>

      <Card title="Onboarding checklist">
        <p className="muted small" style={{ marginTop: 0 }}>Made as tasks when an intake is sent,
          assigned to whoever sent it. Days count from the owner's ready date, or the day it was
          sent when that is blank or past. Keep titles free of names.</p>
        {s.checklist.map((item, i) => (
          <div key={i} className="intake-check-row">
            <input value={item.title} aria-label="Task title" onChange={(e) => setS({ checklist:
              s.checklist.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)) })} />
            <input type="number" min={0} max={365} aria-label="Days after the ready date"
              value={item.offset_days} style={{ width: "4.5rem" }} onChange={(e) => setS({
                checklist: s.checklist.map((x, j) => (j === i ? { ...x, offset_days:
                  Number(e.target.value) } : x)) })} />
            <select value={item.when} aria-label="When" onChange={(e) => setS({ checklist:
              s.checklist.map((x, j) => (j === i ? { ...x, when: e.target.value } : x)) })}>
              {draft.checklist_when.map((w) => <option key={w} value={w}>{w.replace(/_/g, " ")}
              </option>)}
            </select>
            <button type="button" className="link" onClick={() => setS({ checklist:
              s.checklist.filter((_, j) => j !== i) })}>Remove</button>
          </div>
        ))}
        <button type="button" className="ghost small" onClick={() => setS({ checklist: [
          ...s.checklist, { title: "", offset_days: 0, when: "always" }] })}>+ Add a task</button>
        <div style={{ marginTop: ".75rem" }}>
          <button type="button" className="primary" onClick={() => void save({ settings: {
            checklist: s.checklist.filter((x) => x.title.trim()) } })}>Save checklist</button>
        </div>
      </Card>

      <Card title="Messages staff send">
        <p className="muted small" style={{ marginTop: 0 }}>Copied, or opened in your own email.
          {" "}{"{first_name}"}, {"{link}"}, {"{signature}"} and {"{brand}"} are filled in.</p>
        {(["message_invite", "message_reminder"] as const).map((key) => (
          <div key={key} className="intake-message">
            <h4>{key === "message_invite" ? "First invite" : "Reminder"}</h4>
            <Field label="Subject"><input value={s[key].subject} onChange={(e) => setS({
              [key]: { ...s[key], subject: e.target.value } } as Partial<S>)} /></Field>
            <Field label="Message"><textarea rows={9} value={s[key].body} onChange={(e) => setS({
              [key]: { ...s[key], body: e.target.value } } as Partial<S>)} /></Field>
          </div>
        ))}
        <button type="button" className="primary" onClick={() => void save({ settings: {
          message_invite: s.message_invite, message_reminder: s.message_reminder } })}>
          Save messages</button>
      </Card>
    </div>
  );
}

function AddCommon({ amenities, onAdd }: { amenities: { id: number; name: string;
  group: string }[]; onAdd: (label: string, ids: number[]) => void }) {
  const [label, setLabel] = useState("");
  const [id, setId] = useState("");
  return (
    <div className="row wrap" style={{ gap: ".5rem", margin: ".5rem 0" }}>
      <input placeholder="Label owners see" value={label} onChange={(e) => setLabel(e.target.value)} />
      <select value={id} onChange={(e) => setId(e.target.value)} aria-label="Track amenity">
        <option value="">Track amenity…</option>
        {amenities.map((a) => <option key={a.id} value={a.id}>{a.group}: {a.name}</option>)}
      </select>
      <button type="button" className="ghost small" disabled={!label.trim() || !id}
        onClick={() => { onAdd(label.trim(), [Number(id)]); setLabel(""); setId(""); }}>
        Add</button>
    </div>
  );
}

/** The company page's card, for the practice owner, only while this company
 *  has intake forms on. Intake forms are SkyRun's alone (owner, 2026-11-20):
 *  there is no switch in the app; `manage.py intake_forms` turns them on or
 *  off, so nothing about them shows for any other company or practice. */
export function IntakeCard({ companyId }: { companyId: string }) {
  const { data } = useQuery({ queryKey: ["intake-companies"], queryFn: intake.companies });
  if (!data?.companies.some((c) => c.id === companyId)) return null;
  return (
    <Card title="Owner intake forms">
      <p className="small" style={{ marginTop: 0 }}>A white-labelled form new property owners
        fill in on a personal link; the company's managers review it and send it to Track.</p>
      <p className="small"><Link to={`/intake?company=${companyId}`}>Intakes</Link>
        {" · "}<Link to={`/intake/settings/${companyId}`}>Form settings</Link></p>
    </Card>
  );
}
