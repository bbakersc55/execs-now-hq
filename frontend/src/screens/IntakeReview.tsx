/** One owner intake: the review screen (docs/p14_intake_forms.md). Every answer
 *  editable (live on the welcome call), the staff-only choices, the warnings,
 *  what will be sent, and Send to Track with each step's result. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Banner, Card, Pill, when } from "../components/ui";
import "../forms/forms.css";
import { INTROS, SECTIONS, summarize } from "../forms/sections";
import type { Answers, Ctx, FileRow, Secrets, Section } from "../forms/types";
import type { Me } from "../lib/api";
import { intake, type Review, staffFormApi, type Staff, STATUS_KIND } from "../lib/intake";

const BATH_TYPES = [
  { value: "full_bathroom", label: "Full" },
  { value: "three_quarter_bathroom", label: "Three-quarter" },
  { value: "half_bathroom", label: "Half" },
];

function useCopy(): [string, (text: string, what: string) => Promise<void>] {
  const [said, setSaid] = useState("");
  return [said, async (text, what) => {
    try {
      await navigator.clipboard.writeText(text);
      setSaid(`${what} copied.`);
    } catch {
      setSaid(`Couldn't copy: select it and copy by hand.`);
    }
    window.setTimeout(() => setSaid(""), 3000);
  }];
}

export function IntakeReview({ me }: { me: Me }) {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const { data, error, refetch } = useQuery({ queryKey: ["intake", id],
                                              queryFn: () => intake.review(id) });
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");
  const set = (r: Review) => qc.setQueryData(["intake", id], r);
  const act = async (label: string, fn: () => Promise<Review | unknown>) => {
    setBusy(label);
    setProblem("");
    try {
      const r = await fn();
      if (r && typeof r === "object" && "answers" in (r as object)) set(r as Review);
      else await refetch();
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  if (error) return <div className="page"><Banner kind="warn">{(error as Error).message}</Banner>
    </div>;
  if (!data) return <div className="page"><p className="muted">Loading…</p></div>;
  const r = data;
  return (
    <div className="page intake-review">
      <p className="muted small" style={{ margin: 0 }}>
        <Link to={`/intake?company=${r.form.company_id}`}>Owner intake</Link> · {r.form.company}</p>
      <div className="spread">
        <h1 style={{ margin: ".25rem 0" }}>Intake #{r.number}{r.owner ? `: ${r.owner}` : ""}</h1>
        <Pill kind={STATUS_KIND[r.status] === "danger" ? "bad" : STATUS_KIND[r.status] ?? ""}>
          {r.status_label}</Pill>
      </div>
      {problem && <Banner kind="warn">{problem}</Banner>}
      {r.locked && (
        <Banner>Sent to Track {when(r.sent_at)}. This is now a locked record: later changes are
          made in Track.</Banner>
      )}
      <div className="intake-grid">
        <div className="intake-main">
          {!r.locked && r.status !== "discarded" && <LinkCard r={r} act={act} busy={busy} />}
          <AnswersCard r={r} />
          <SecretsCard r={r} />
          {r.files.length > 0 && (
            <Card title="Documents">
              <ul>{r.files.map((f) => <li key={f.id}><a href={`/api/intake/submissions/${r.id}/files/${f.id}`}
                target="_blank" rel="noreferrer">{f.name}</a>
                <span className="muted"> · {Math.round(f.size / 1024)} KB</span></li>)}</ul>
              {r.locked && <p className="muted small">Kept here in ENHQ. The checklist has a task to
                upload it to Track.</p>}
            </Card>
          )}
          <Card title="Activity">
            <ul className="intake-events">
              {r.events.slice().reverse().map((e, i) => (
                <li key={i}><span className="when">{when(e.at)}</span> {e.detail || e.label}
                  <span className="muted"> · {e.who}</span></li>
              ))}
            </ul>
          </Card>
        </div>
        <div className="intake-side">
          {!r.locked && r.status !== "discarded" && (
            <>
              <StaffCard r={r} onSaved={set} />
              <CheckCard r={r} act={act} busy={busy} onSaved={set} />
            </>
          )}
          <SendCard r={r} me={me} onDone={() => void refetch()} />
          {r.owner_dates.length > 0 && <DatesCard r={r} act={act} busy={busy} />}
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------ the link

function LinkCard({ r, act, busy }: { r: Review; busy: string;
  act: (label: string, fn: () => Promise<unknown>) => Promise<void> }) {
  const [said, copy] = useCopy();
  const [confirm, setConfirm] = useState(false);
  const run = async (action: "link" | "message" | "email", reminder: boolean) => {
    const out = await intake.link(r.id, action, reminder);
    if (action === "link") await copy(out.link, "Link");
    if (action === "message") await copy(`${out.subject}\n\n${out.body}`, "Message");
    if (action === "email") window.location.href = out.mailto;
  };
  const mayRemind = r.status === "draft" || r.status === "in_progress";
  return (
    <Card title="The owner's link">
      <p className="mono small intake-link">{r.link}</p>
      {!r.link_open && <Banner kind="warn">This link has expired (30 days without use).
        Reopen it for another 30 days.</Banner>}
      {r.form.domain === "" && <p className="muted small">Owners see this address. Set the
        form's own domain in the form settings so it doesn't show getexecutivesnow.com.</p>}
      <div className="row wrap" style={{ gap: ".5rem" }}>
        <button type="button" className="primary small" onClick={() => void run("link", false)}>
          Copy link</button>
        <button type="button" className="ghost small" onClick={() => void run("message", false)}>
          Copy message</button>
        <button type="button" className="ghost small" onClick={() => void run("email", false)}>
          Open in my email</button>
        {!r.link_open && <button type="button" className="ghost small" disabled={!!busy}
          onClick={() => void act("reopen", () => intake.reopen(r.id))}>Reopen link</button>}
      </div>
      {mayRemind && (
        <div className="row wrap" style={{ gap: ".5rem", marginTop: ".6rem" }}>
          <span className="muted small">Send a reminder:</span>
          <button type="button" className="ghost small" onClick={() => void run("message", true)}>
            Copy reminder</button>
          <button type="button" className="ghost small" onClick={() => void run("email", true)}>
            Open reminder in my email</button>
        </div>
      )}
      <p className="small" aria-live="polite" style={{ minHeight: "1.2em" }}>{said}</p>
      {!confirm ? (
        <button type="button" className="link danger" onClick={() => setConfirm(true)}>
          Discard this intake</button>
      ) : (
        <p className="small">Discard it? The link stops working and its sensitive values are
          deleted at once. <button type="button" className="danger small" disabled={!!busy}
            onClick={() => void act("discard", () => intake.discard(r.id))}>Yes, discard
          </button> <button type="button" className="link" onClick={() => setConfirm(false)}>
            Keep it</button></p>
      )}
    </Card>
  );
}

// ------------------------------------------------------------ the answers

function AnswersCard({ r }: { r: Review }) {
  const qc = useQueryClient();
  const api = useMemo(() => staffFormApi(r.id), [r.id]);
  const [answers, setAnswers] = useState<Answers>(r.answers);
  const [secrets, setSecrets] = useState<Secrets>(r.secrets);
  const [files, setFiles] = useState<FileRow[]>(r.files);
  const [state, setState] = useState("");
  useEffect(() => { setAnswers(r.answers); setSecrets(r.secrets); setFiles(r.files); },
            [r.answers, r.secrets, r.files]);
  const [timer, setTimer] = useState<number | undefined>(undefined);
  const update = <K extends Section>(section: K, value: Answers[K]) => {
    setAnswers((a) => ({ ...a, [section]: value }));
    setState("Saving…");
    window.clearTimeout(timer);
    setTimer(window.setTimeout(async () => {
      try {
        await api.saveSection(section, value);
        setState("Saved");
        void qc.invalidateQueries({ queryKey: ["intake", r.id] });
      } catch (e) {
        setState((e as Error).message);
      }
    }, 800));
  };
  const ctx: Ctx = { form: r.owner_form, answers, update, secrets, setSecrets, files, setFiles,
                     api, brand: r.form.brand_name, mode: "staff" };
  const keys = r.owner_form.sections.filter((s) => SECTIONS[s.key]);
  return (
    <Card title="The owner's answers" actions={<span className="muted small"
      aria-live="polite">{state}</span>}>
      {!r.locked && <p className="muted small" style={{ marginTop: 0 }}>Every answer can be
        changed here, for instance live on the welcome call. Changes save as you go.</p>}
      <div className="ix-root ix-embedded">
        {keys.map((s) => {
          const Body = SECTIONS[s.key];
          return (
            <details key={s.key} className="ix-more intake-section">
              <summary><strong>{s.title}</strong>
                <span className="muted small"> · {summarize(ctx, s.key).slice(0, 2).join(" · ")
                  || "Nothing yet"}</span></summary>
              {r.locked ? (
                <ul>{summarize(ctx, s.key).map((l, i) => <li key={i}>{l}</li>)}</ul>
              ) : (
                <div className="ix-section">
                  {INTROS[s.key] && <p className="ix-hint">{INTROS[s.key]}</p>}
                  <Body ctx={ctx} />
                </div>
              )}
            </details>
          );
        })}
      </div>
    </Card>
  );
}

function SecretsCard({ r }: { r: Review }) {
  const [shown, setShown] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const names: { name: string; label: string; held: boolean; hint?: string }[] = [
    { name: "tax_id", label: "Business Tax ID", held: !!r.secrets.tax_id,
      hint: r.secrets.tax_id ? `ending ${r.secrets.tax_id.last4}` : undefined },
    { name: "wifi_password", label: "Wi-Fi password", held: r.secrets.wifi_password },
    ...r.derived.codes.map((c) => ({ name: `code:${c.slot}`, label: c.label,
                                     held: !!r.secrets.codes[c.slot] })),
  ].filter((x) => x.held);
  if (!names.length) return null;
  return (
    <Card title="Sensitive values">
      <p className="muted small" style={{ marginTop: 0 }}>Encrypted, and deleted from ENHQ the
        moment Track confirms it has them. Each reveal is recorded with who and when.</p>
      <ul className="intake-secrets">
        {names.map((n) => (
          <li key={n.name}>
            <span>{n.label}{n.hint ? ` (${n.hint})` : ""}</span>
            {shown[n.name] ? <code>{shown[n.name]}</code> : (
              <button type="button" className="ghost small" onClick={async () => {
                try {
                  const out = await intake.reveal(r.id, n.name);
                  setShown((s) => ({ ...s, [n.name]: out.value }));
                } catch (e) { setError((e as Error).message); }
              }}>Reveal</button>
            )}
          </li>
        ))}
      </ul>
      {error && <Banner kind="warn">{error}</Banner>}
    </Card>
  );
}

// ------------------------------------------------------------ staff choices

function StaffCard({ r, onSaved }: { r: Review; onSaved: (r: Review) => void }) {
  const s = r.staff;
  const [error, setError] = useState("");
  const save = async (changes: Partial<Staff>) => {
    setError("");
    try { onSaved(await intake.staff(r.id, changes)); } catch (e) { setError((e as Error).message); }
  };
  const nodes = r.lists.nodes ?? [];
  const agreement = r.staff_fields.find((f) => f.reference ===
    "pms_units_management_agreement_type");
  const keywords = r.staff_fields.find((f) => f.reference ===
    "pms_units_trigger_automation_keywords");
  const chosenKeywords = s.keywords ?? r.derived.keyword_presets;
  const baths = r.derived.rooms.filter((x) => x.roomType.endsWith("bathroom"));
  const others = r.staff_fields.filter((f) => !["pms_units_management_agreement_type",
    "pms_units_trigger_automation_keywords", "pms_units_contract_effective_date"]
    .includes(f.reference));
  return (
    <Card title="Staff choices">
      <div className="intake-choices">
        <label>Area (Track's node) <select value={s.node_id ?? ""}
          onChange={(e) => void save({ node_id: e.target.value ? Number(e.target.value) : null })}>
          <option value="">Pick the area</option>
          {nodes.map((n) => <option key={n.id} value={n.id}>{n.name}
            {n.typeName ? ` (${n.typeName})` : ""}</option>)}
        </select></label>
        <label>Contract <select value={s.contract_id ?? ""}
          onChange={(e) => void save({ contract_id: e.target.value ? Number(e.target.value)
            : null })}>
          <option value="">Pick the contract</option>
          {(r.lists.contracts ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select></label>
        {agreement && <label>Management agreement <select value={s.management_agreement}
          onChange={(e) => void save({ management_agreement: e.target.value })}>
          {agreement.values.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
        </select></label>}
        <label>Start date <input type="date" value={s.start_date ?? ""}
          onChange={(e) => void save({ start_date: e.target.value })} /></label>
        <label>Contract effective date <input type="date" value={s.contract_effective_date ?? ""}
          onChange={(e) => void save({ contract_effective_date: e.target.value })} /></label>
        <label>Unit type <select value={s.unit_type_id ?? ""}
          onChange={(e) => void save({ unit_type_id: e.target.value ? Number(e.target.value)
            : null })}>
          <option value="">None</option>
          {(r.lists.unit_types ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}
            {t.id === r.derived.unit_type_suggested ? " (from the bedrooms)" : ""}</option>)}
        </select></label>
        <label>Unit name <input defaultValue={s.unit_name}
          onBlur={(e) => e.target.value !== s.unit_name && void save({ unit_name: e.target.value })} />
        </label>
        <label>Short name <input defaultValue={s.short_name}
          onBlur={(e) => e.target.value !== s.short_name && void save({ short_name:
            e.target.value })} /></label>
        <label>Total sleeps <input type="number" min={0} placeholder={String(r.derived
          .sleeps_worked_out)} defaultValue={s.sleeps_total ?? ""}
          onBlur={(e) => void save({ sleeps_total: e.target.value === "" ? null
            : Number(e.target.value) })} />
          <span className="muted small">Worked out from the beds: {r.derived.sleeps_worked_out}
          </span></label>
      </div>
      {baths.length > 0 && (
        <>
          <h4>Bathroom types</h4>
          {baths.map((b) => {
            const i = b.key.split("-")[1];
            return (
              <label key={b.key} className="intake-inline">{b.name}: worked out as{" "}
                {BATH_TYPES.find((t) => t.value === b.worked_out)?.label}
                <select value={s.bath_types?.[i] ?? ""} onChange={(e) => void save({
                  bath_types: { ...(s.bath_types ?? {}), [i]: e.target.value } })}>
                  <option value="">Keep it</option>
                  {BATH_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select></label>
            );
          })}
        </>
      )}
      {s.owner_mode !== "existing" && r.people.length > 1 && (
        <>
          <h4>Owners' shares</h4>
          {r.people.slice(1).map((p, i) => (
            <label key={i} className="intake-inline">{p.first} {p.last}{p.portal
              ? " (portal access wanted)" : ""}
              <input type="number" min={0} max={100} style={{ width: "6rem" }}
                defaultValue={s.shares?.[String(i + 1)] ?? ""} placeholder="%"
                onBlur={(e) => void save({ shares: { ...(s.shares ?? {}),
                  [String(i + 1)]: e.target.value === "" ? (undefined as unknown as number)
                    : Number(e.target.value) } })} /> %</label>
          ))}
        </>
      )}
      <h4>Amenities from the owner's answers</h4>
      {r.derived.derived_amenities.length === 0 ? <p className="muted small">None.</p> : (
        <ul className="intake-derived">
          {r.derived.derived_amenities.map((a) => (
            <li key={a.id}>
              <label><input type="checkbox" checked={a.ticked && !a.provided_by_area}
                disabled={a.provided_by_area} onChange={() => {
                  const untick = new Set(s.untick ?? []);
                  if (untick.has(a.id)) untick.delete(a.id); else untick.add(a.id);
                  void save({ untick: [...untick] });
                }} /> {a.name}</label>
              <span className="muted small"> · from the owner's answers: {a.why}
                {a.provided_by_area ? " · the area already provides it" : ""}</span>
            </li>
          ))}
        </ul>
      )}
      {keywords && (
        <>
          <h4>Trigger / automation keywords</h4>
          {keywords.values.map((v) => (
            <label key={v.value} className="intake-inline">
              <input type="checkbox" checked={chosenKeywords.includes(v.value)} onChange={() => {
                const next = chosenKeywords.includes(v.value)
                  ? chosenKeywords.filter((x) => x !== v.value) : [...chosenKeywords, v.value];
                void save({ keywords: next });
              }} /> {v.label}</label>
          ))}
        </>
      )}
      {others.map((f) => (
        <label key={f.reference} className="intake-inline">{f.name}
          <input defaultValue={String(s.custom?.[f.reference] ?? "")}
            onBlur={(e) => void save({ custom: { ...(s.custom ?? {}),
              [f.reference]: e.target.value } })} /></label>
      ))}
      {error && <Banner kind="warn">{error}</Banner>}
    </Card>
  );
}

function CheckCard({ r, act, busy, onSaved }: { r: Review; busy: string;
  act: (label: string, fn: () => Promise<unknown>) => Promise<void>;
  onSaved: (r: Review) => void }) {
  const c = r.check;
  const s = r.staff;
  const save = async (changes: Partial<Staff>) => onSaved(await intake.staff(r.id, changes));
  return (
    <Card title="Look in Track" actions={<button type="button" className="ghost small"
      disabled={!!busy} onClick={() => void act("check", () => intake.check(r.id))}>
      {busy === "check" ? "Looking…" : r.checked_at ? "Look again" : "Look now"}</button>}>
      {!r.checked_at && <p className="muted small" style={{ marginTop: 0 }}>Checks Track for an
        owner or contact with the same email, and a unit at the same address.</p>}
      {c.error && <Banner kind="warn">{c.error}</Banner>}
      {(c.owners ?? []).map((o) => (
        <Banner key={o.id} kind="warn">An owner in Track has this email: {o.name} (#{o.id}).{" "}
          {s.owner_mode === "existing" && s.existing_owner_id === o.id ? (
            <>The unit will be attached to this owner. <button type="button" className="link"
              onClick={() => void save({ owner_mode: "new", existing_owner_id: null })}>
              Make a new owner instead</button></>
          ) : (
            <button type="button" className="link" onClick={() => void save({
              owner_mode: "existing", existing_owner_id: o.id })}>Attach the unit to this owner
              instead</button>
          )}</Banner>
      ))}
      {s.owner_mode !== "existing" && Object.entries(c.contacts ?? {}).map(([i, found]) =>
        found.map((x) => (
          <Banner key={`${i}-${x.id}`} kind="warn">A contact in Track has the email of
            {i === "0" ? " the owner" : ` additional owner ${i}`}: {x.name} (#{x.id}).{" "}
            {s.reuse_contacts?.[i] === x.id ? "It will be reused." : (
              <button type="button" className="link" onClick={() => void save({ reuse_contacts:
                { ...(s.reuse_contacts ?? {}), [i]: x.id } })}>Reuse it instead of a new one
              </button>)}</Banner>
        )))}
      {(c.units ?? []).map((u) => (
        <Banner key={u.id} kind="warn">A unit in Track already has this street address:
          {" "}{u.name} (#{u.id}{u.isActive ? ", active" : ", inactive"}).</Banner>
      ))}
      {s.owner_mode === "existing" && (
        <>
          <p className="small">The existing owner is left untouched: only the unit and the
            owner's link to it are written. New additional owners become a checklist task.</p>
          {(c.differences ?? []).length > 0 && (
            <table className="table small">
              <thead><tr><th>Answer</th><th>In the intake</th><th>In Track</th></tr></thead>
              <tbody>{(c.differences ?? []).map((d) => (
                <tr key={d.field}><td>{d.field}</td><td>{d.intake}</td><td>{d.track}</td></tr>
              ))}</tbody>
            </table>
          )}
        </>
      )}
      {r.checked_at && !c.error && !(c.owners ?? []).length && !(c.units ?? []).length
        && !Object.keys(c.contacts ?? {}).length && <p className="small">Nothing in Track
          matches. Looked {when(r.checked_at)}.</p>}
    </Card>
  );
}

// ------------------------------------------------------------ sending

const STEP_MARK: Record<string, string> = { done: "✓", skipped: "✓", failed: "✕",
                                            running: "…", waiting: "·" };

function SendCard({ r, onDone }: { r: Review; me: Me; onDone: () => void }) {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const live = r.run && (r.run.state === "queued" || r.run.state === "running");
  const { data: polled } = useQuery({
    queryKey: ["intake-run", r.id], queryFn: () => intake.run(r.id),
    enabled: !!live || sending, refetchInterval: 1500,
  });
  const run = polled?.run ?? r.run;
  useEffect(() => {
    if (polled?.run && !["queued", "running"].includes(polled.run.state)) {
      setSending(false);
      onDone();
    }
  }, [polled, onDone]);
  const send = async () => {
    setError("");
    setSending(true);
    try { await intake.send(r.id); } catch (e) { setError((e as Error).message); setSending(false); }
  };
  return (
    <Card title={r.locked ? "Sent to Track" : "What will be sent"} tone="current">
      {!r.locked && (
        <>
          <ul className="intake-plan">{r.plan.summary.map((l, i) => <li key={i}>{l}</li>)}</ul>
          {r.plan.problems.map((p, i) => <Banner key={i} kind="warn">{p}</Banner>)}
          {r.plan.warnings.map((w, i) => <p key={i} className="small muted">Note: {w}</p>)}
        </>
      )}
      {run && (
        <ol className="intake-steps" aria-live="polite">
          {run.steps.map((s) => (
            <li key={s.key} className={`step-${s.state}`}>
              <span className="mark">{STEP_MARK[s.state] ?? "·"}</span> {s.label}
              {s.detail && <span className="muted small"> · {s.detail}</span>}
            </li>
          ))}
        </ol>
      )}
      {run?.state === "failed" && <Banner kind="warn">The send stopped: {run.error} What was
        done is kept in Track and here; "Try the rest again" continues without making
        duplicates.</Banner>}
      {error && <Banner kind="warn">{error}</Banner>}
      {!r.locked && (
        <button type="button" className="primary" disabled={!r.may_send || sending || !!live}
          onClick={() => void send()}>
          {sending || live ? "Sending…" : run?.state === "failed" ? "Try the rest again"
            : "Send to Track"}</button>
      )}
    </Card>
  );
}

function DatesCard({ r, act, busy }: { r: Review; busy: string;
  act: (label: string, fn: () => Promise<unknown>) => Promise<void> }) {
  const [said, setSaid] = useState("");
  return (
    <Card title="The owner's own dates">
      <p className="muted small" style={{ marginTop: 0 }}>Held here until the unit is bookable in
        Track, then blocked as Owner Reservation. Checked every hour.</p>
      <ul className="intake-dates">
        {r.owner_dates.map((d) => (
          <li key={d.id}>{d.start} to {d.end}: <Pill kind={d.state === "placed" ? "ok"
            : d.state === "held" ? "warn" : d.state === "refused" ? "bad" : ""}>{d.state_label}
          </Pill>{d.message && <span className="muted small"> {d.message}</span>}
            {d.state === "held" && <button type="button" className="link" disabled={!!busy}
              onClick={() => void act("cancel", () => intake.cancelDate(r.id, d.id))}>Cancel
            </button>}</li>
        ))}
      </ul>
      {r.owner_dates.some((d) => d.state === "held") && (
        <button type="button" className="primary small" disabled={!!busy} onClick={() =>
          void act("place", async () => {
            const out = await intake.placeDates(r.id);
            setSaid(out.result.text);
          })}>Place owner dates now</button>
      )}
      <p className="small" aria-live="polite">{said}</p>
    </Card>
  );
}
