/** Owner agreements (docs/p15_owner_agreements.md): one line per owner, and a
 *  new owner's agreement. Phone first. For the practice owner and anyone
 *  ticked "Owner agreements" (and countersigners, to countersign). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cloneElement, useId, useState, type ReactElement } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Banner, Card, Empty, Pill, when } from "../components/ui";
import type { Me } from "../lib/api";
import {
  agreements, PERIODS, SHARED_EMAIL, sharesEmail, stage, type AgreementRow, type Block,
  type CoOwnerInput, type Terms,
} from "../lib/agreements";

export function AgreementsScreen({ me: _me }: { me: Me }) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { data: companies } = useQuery({ queryKey: ["agreement-companies"],
                                          queryFn: agreements.companies });
  const list = companies?.companies ?? [];
  const company = params.get("company") || list[0]?.id || "";
  const { data, isLoading } = useQuery({ queryKey: ["agreements", company],
    queryFn: () => agreements.company(company), enabled: !!company });
  if (companies && !list.length) {
    return <div className="page"><h1>Owner agreements</h1>
      <Empty>Owner agreements aren't on for any company you work with.</Empty></div>;
  }
  return (
    <div className="page agreements">
      <div className="spread wrap" style={{ gap: ".5rem" }}>
        <h1 style={{ margin: 0 }}>Owner agreements</h1>
        <div className="row wrap" style={{ gap: ".5rem" }}>
          {data?.is_signer && <Link className="btn ghost small"
            to={`/agreements/authority/${company}`}>Your authorization</Link>}
          {data && (data.may_edit_access || data.may_work) && <Link className="btn ghost small"
            to={`/agreements/settings/${company}`}>Settings</Link>}
          {data?.may_work && <Link className="btn primary small"
            to={`/agreements/new?company=${company}`}>New owner</Link>}
        </div>
      </div>
      {list.length > 1 && (
        <div className="row wrap" style={{ gap: ".5rem", margin: ".75rem 0" }}>
          {list.map((c) => (
            <button key={c.id} type="button" className={c.id === company ? "primary small"
              : "ghost small"} onClick={() => setParams({ company: c.id })}>{c.name}</button>))}
        </div>
      )}
      {data?.program.paused_at && <Banner kind="warn">Owner emails are paused:
        {" "}{data.program.pause_reason} <Link to={`/agreements/settings/${company}`}>
        Settings</Link></Banner>}
      {data?.program.sender === "testing" && <Banner kind="warn">Owner emails come from ENHQ's
        own sender (testing): owners would see Executives Now.</Banner>}
      <Card title="Owners">
        {isLoading ? <p className="muted">Loading…</p> : !data?.agreements.length ? (
          <Empty>No agreements yet.</Empty>
        ) : (
          <ul className="agreement-list">
            {data.agreements.map((a) => (
              <li key={a.id}>
                <button type="button" className="agreement-row"
                  onClick={() => navigate(`/agreements/${a.id}`)}>
                  <span className="agreement-who"><strong>#{a.number} {a.owner_name}</strong>
                    <span className="muted small">{a.property || "No address yet"}</span></span>
                  <StatusLine row={a} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

/** Sent · opened · signed by owner · countersigned · form started · form
 *  submitted · sent to Track. */
export function StatusLine({ row }: { row: AgreementRow }) {
  if (row.cancelled) return <Pill kind="bad">Cancelled</Pill>;
  return (
    <>
      <ol className="status-line" aria-label={`Status: ${stage(row)}`}>
        {row.status.map((s) => (
          <li key={s.key} className={s.at ? "done" : ""} title={s.at ? when(s.at) : "Not yet"}>
            <span aria-hidden="true">{s.at ? "✓" : "·"}</span> {s.label}</li>
        ))}
      </ol>
      {row.turn && <span className="muted small status-turn">{row.turn}</span>}
    </>
  );
}

/** Owners 2 to 4 (owner, 2026-11-24): a name and an email each, a title if
 *  wanted. They sign in this order, after the first owner. */
export function CoOwnersEditor({ rows, onChange }: { rows: CoOwnerInput[];
  onChange: (rows: CoOwnerInput[]) => void }) {
  const set = (i: number, patch: Partial<CoOwnerInput>) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="co-owners">
      {rows.map((r, i) => (
        <fieldset key={i} className="co-owner">
          <legend>Owner {i + 2}</legend>
          <Labeled label={`Owner ${i + 2}: name`}><input value={r.name} autoComplete="off"
            onChange={(e) => set(i, { name: e.target.value })} /></Labeled>
          <Labeled label={`Owner ${i + 2}: email`}><input type="email" inputMode="email"
            value={r.email} onChange={(e) => set(i, { email: e.target.value })} /></Labeled>
          <Labeled label={`Owner ${i + 2}: title (optional)`}><input value={r.title}
            placeholder="For example: Trustee"
            onChange={(e) => set(i, { title: e.target.value })} /></Labeled>
          <button type="button" className="small ghost" onClick={() =>
            onChange(rows.filter((_, j) => j !== i))}>Remove owner {i + 2}</button>
        </fieldset>
      ))}
      {rows.length < 3 && <button type="button" className="small ghost" onClick={() =>
        onChange([...rows, { name: "", email: "", title: "" }])}>+ Add another owner</button>}
      {rows.length > 0 && <p className="muted small">They sign in this order, each on their own
        link, emailed when the owner before them has signed. Only the first owner fills in the
        owner's page.</p>}
    </div>
  );
}

// ------------------------------------------------------------ a new owner

/** A field whose label names its input (for screen readers, and the walk). */
export function Labeled({ label, children }: { label: string;
  children: ReactElement<{ id?: string }> }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {cloneElement(children, { id })}
    </div>
  );
}

export function TermsEditor({ terms, onChange }: { terms: Terms;
  onChange: (t: Terms) => void }) {
  const set = (patch: Partial<Terms>) => onChange({ ...terms, ...patch });
  const addr = terms.property_address ?? {};
  const setAddr = (patch: Record<string, string>) =>
    set({ property_address: { ...addr, ...patch } });
  return (
    <div className="terms-editor">
      <fieldset>
        <legend>Property address</legend>
        <p className="muted small">The owner confirms it, and may correct it.</p>
        <Labeled label="Street"><input value={addr.street ?? ""}
          onChange={(e) => setAddr({ street: e.target.value })} /></Labeled>
        <Labeled label="Unit (optional)"><input value={addr.unit ?? ""}
          onChange={(e) => setAddr({ unit: e.target.value })} /></Labeled>
        <div className="row wrap" style={{ gap: ".5rem" }}>
          <Labeled label="City"><input value={addr.city ?? ""}
            onChange={(e) => setAddr({ city: e.target.value })} /></Labeled>
          <Labeled label="State"><input value={addr.state ?? ""} size={6}
            onChange={(e) => setAddr({ state: e.target.value })} /></Labeled>
          <Labeled label="ZIP"><input value={addr.zip ?? ""} size={8} inputMode="numeric"
            onChange={(e) => setAddr({ zip: e.target.value })} /></Labeled>
        </div>
      </fieldset>
      <fieldset>
        <legend>Commission split (section 15)</legend>
        <div className="row wrap" style={{ gap: ".5rem" }}>
          <Labeled label="Owner %"><input inputMode="decimal" value={terms.owner_percent}
            onChange={(e) => {
              const owner = e.target.value;
              const n = Number(owner);
              set({ owner_percent: owner, manager_percent: Number.isFinite(n) && owner !== ""
                ? String(Math.round((100 - n) * 100) / 100) : terms.manager_percent });
            }} /></Labeled>
          <Labeled label="Manager %"><input inputMode="decimal" value={terms.manager_percent}
            onChange={(e) => {
              const manager = e.target.value;
              const n = Number(manager);
              set({ manager_percent: manager, owner_percent: Number.isFinite(n) && manager !== ""
                ? String(Math.round((100 - n) * 100) / 100) : terms.owner_percent });
            }} /></Labeled>
        </div>
      </fieldset>
      <fieldset>
        <legend>Minimum revenue management fee (section 30)</legend>
        <p className="muted small">Due only in a month when rental revenue falls below the
          threshold. A period with a $0 fee is left out; with every fee $0 the clause isn't in
          the agreement.</p>
        {PERIODS.map((p) => {
          const row = terms.fees?.[p.key] ?? { threshold: "0", fee: "0" };
          const setRow = (patch: Record<string, string>) =>
            set({ fees: { ...terms.fees, [p.key]: { ...row, ...patch } } });
          return (
            <div key={p.key} className="fee-row">
              <span className="fee-period">{p.label}</span>
              <Labeled label="Revenue threshold $"><input inputMode="decimal" value={row.threshold}
                onChange={(e) => setRow({ threshold: e.target.value })} /></Labeled>
              <Labeled label="Fee $"><input inputMode="decimal" value={row.fee}
                onChange={(e) => setRow({ fee: e.target.value })} /></Labeled>
            </div>
          );
        })}
      </fieldset>
      <Labeled label="Additional items (section 30)">
        <textarea rows={3} value={terms.additional_items} placeholder="None"
          onChange={(e) => set({ additional_items: e.target.value })} />
      </Labeled>
    </div>
  );
}

export function AgreementNew({ me: _me }: { me: Me }) {
  const [params] = useSearchParams();
  const company = params.get("company") || "";
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["agreements", company],
    queryFn: () => agreements.company(company), enabled: !!company });
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [others, setOthers] = useState<CoOwnerInput[]>([]);
  const [terms, setTerms] = useState<Terms | null>(null);
  const [preview, setPreview] = useState<Block[] | null>(null);
  const [error, setError] = useState("");
  const current = terms ?? data?.defaults ?? null;
  const create = useMutation({
    mutationFn: async (then: "email" | "link" | "save") => {
      const made = await agreements.create(company, { name, email, phone, terms: current!,
                                                     co_owners: others });
      if (then === "email") await agreements.action(made.id, "send");
      if (then === "link") {
        const out = await agreements.action(made.id, "link");
        await navigator.clipboard?.writeText(out.link ?? "").catch(() => undefined);
      }
      return { made, then };
    },
    onSuccess: ({ made, then }) => {
      void qc.invalidateQueries({ queryKey: ["agreements", company] });
      navigate(`/agreements/${made.id}${then === "link" ? "?copied=1" : then === "email"
        ? "?emailed=1" : ""}`);
    },
    onError: (e) => setError((e as Error).message),
  });
  if (!current) return <div className="page"><p className="muted">Loading…</p></div>;
  const ok = name.trim() && (email.trim() || phone.trim())
    && others.every((o) => o.name.trim() && o.email.trim());
  const shared = sharesEmail([email, ...others.map((o) => o.email)]);
  return (
    <div className="page agreements">
      <p className="muted small" style={{ margin: 0 }}>
        <Link to={`/agreements?company=${company}`}>Owner agreements</Link></p>
      <h1 style={{ margin: ".25rem 0" }}>New owner</h1>
      <Card title="The owner">
        <Labeled label="Name"><input value={name} onChange={(e) => setName(e.target.value)}
          autoComplete="off" /></Labeled>
        <Labeled label="Email"><input type="email" value={email} inputMode="email"
          onChange={(e) => setEmail(e.target.value)} /></Labeled>
        <Labeled label="Phone"><input type="tel" value={phone} inputMode="tel"
          onChange={(e) => setPhone(e.target.value)} /></Labeled>
        <p className="muted small">An email, a phone, or both. With a phone only, copy the link
          and send it yourself: the app never sends text messages.</p>
        <CoOwnersEditor rows={others} onChange={(r) => { setOthers(r); setPreview(null); }} />
        {shared && <Banner kind="info">{SHARED_EMAIL}</Banner>}
      </Card>
      <Card title="The terms">
        <TermsEditor terms={current} onChange={(t) => { setTerms(t); setPreview(null); }} />
      </Card>
      {error && <Banner kind="warn">{error}</Banner>}
      <div className="agreement-actions">
        <button type="button" className="ghost" onClick={async () => {
          setError("");
          try {
            setPreview((await agreements.preview(company, current, name.trim()
              ? { name, co_owners: others } : undefined)).blocks);
          }
          catch (e) { setError((e as Error).message); }
        }}>Preview the agreement</button>
        <button type="button" className="primary" disabled={!ok || !email.trim()
          || create.isPending} onClick={() => create.mutate("email")}>Send by email</button>
        <button type="button" className="ghost" disabled={!ok || create.isPending}
          onClick={() => create.mutate("link")}>Copy the link</button>
      </div>
      {data?.program.sender === "testing" && <p className="muted small">Owner email is on ENHQ's
        own sender (testing): the owner would see Executives Now.</p>}
      {preview && (
        <Card title="Preview: exactly what the owner reads">
          <AgreementBlocks blocks={preview} />
        </Card>
      )}
    </div>
  );
}

/** The agreement's words, as the owner reads them; terms highlighted. */
export function AgreementBlocks({ blocks }: { blocks: Block[] }) {
  return (
    <article className="agreement-doc">
      {blocks.map((b, i) => {
        switch (b.type) {
          case "title": return <p key={i} className="doc-title">{b.text}</p>;
          case "heading": return <h3 key={i}>{b.text}</h3>;
          case "para": return (
            <p key={i} className={`indent-${b.indent}`}>{b.spans.map((s, j) =>
              s.t === "bold" ? <strong key={j}>{s.v}</strong>
                : s.t === "term" ? <mark key={j}>{s.v}</mark> : <span key={j}>{s.v}</span>)}</p>);
          case "list": return (
            <ul key={i}>{b.items.map((item, j) => <li key={j} className={`level-${item.level}`}>
              {item.spans.map((s) => s.v).join("")}</li>)}</ul>);
          case "section_30": return <div key={i}>{b.paras.map((p, j) =>
            <p key={j}><mark>{p}</mark></p>)}</div>;
          case "owner_section": return (
            <div key={i} className="doc-owner">{b.lines.map((line, j) => "heading" in line
              ? <h4 key={j}>{line.heading}</h4>
              : "note" in line ? <p key={j}>{line.note}</p>
              : <p key={j}>{line.fields.map((f) => <span key={f.key} className="doc-field">
                  {f.label} <strong>{f.value || "—"}</strong></span>)}</p>)}</div>);
          case "signatures": return (
            <p key={i} className="muted">Signatures: {b.signer_name}, {b.signer_title}, for
              SkyRun Park City; then {(b.owners ?? []).length > 1 ? "the owners, in order: "
                : "the owner"}{(b.owners ?? []).length > 1
                ? (b.owners ?? []).map((o) => o.name).join("; ") : ""}.</p>);
          case "page_break": return <hr key={i} />;
        }
        return null;
      })}
    </article>
  );
}
