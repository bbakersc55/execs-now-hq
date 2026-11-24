/** The owner's rental management agreement behind a personal link: welcome,
 *  the agreement in full, the owner's section, consent and signature, then
 *  onboarding now or later. Phone first, the intake form's look, white label:
 *  only the company's own brand appears. */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { FormError } from "./api";
import { agreementApi, type AgreementPage, type Block, type Details } from "./agreementApi";
import { brandStyle, Footer, Header } from "./FormApp";
import { SignaturePad } from "./SignaturePad";
import type { Brand } from "./types";
import { Choice, Note, Text } from "./ui";

type Phase = "loading" | "ready" | "gone" | "error";
type Step = "welcome" | "agreement" | "details" | "sign";
const STEPS: { key: Step; title: string }[] = [
  { key: "welcome", title: "Welcome" },
  { key: "agreement", title: "Your agreement" },
  { key: "details", title: "Your details" },
  { key: "sign", title: "Sign" },
];

export function AgreementApp({ brand, token }: { brand: Brand; token: string | null }) {
  const api = useMemo(() => agreementApi(token ?? ""), [token]);
  const [phase, setPhase] = useState<Phase>(token ? "loading" : "gone");
  const [page, setPage] = useState<AgreementPage | null>(null);
  const [details, setDetails] = useState<Details>({});
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [missing, setMissing] = useState<string[]>([]);
  const [step, setStep] = useState<Step>("welcome");
  const [saving, setSaving] = useState<"" | "saving" | "saved" | "retry">("");
  const timer = useRef<number | undefined>(undefined);
  const pending = useRef<Details | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);

  const apply = useCallback((data: AgreementPage) => {
    setPage(data);
    setDetails(data.details ?? {});
    setBlocks(data.blocks);
    setMissing(data.missing);
  }, []);

  useEffect(() => {
    if (!token) return;
    api.load().then((data) => { apply(data); setPhase("ready"); }).catch((e: unknown) => {
      const status = e instanceof FormError ? e.status : 0;
      setPhase(status === 404 ? "gone" : "error");
    });
  }, [api, apply, token]);

  const flush = useCallback(async (): Promise<boolean> => {
    window.clearTimeout(timer.current);
    const value = pending.current;
    if (!value) return true;
    pending.current = null;
    setSaving("saving");
    try {
      const out = await api.saveDetails(value);
      setMissing(out.missing);
      setBlocks(out.blocks);
      setSaving("saved");
      return true;
    } catch {
      pending.current = pending.current ?? value;
      setSaving("retry");
      return false;
    }
  }, [api]);

  const update = (next: Details) => {
    setDetails(next);
    pending.current = next;
    setSaving("");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void flush(), 700);
  };

  const go = async (next: Step) => {
    await flush();
    setStep(next);
    window.scrollTo({ top: 0 });
    window.setTimeout(() => heading.current?.focus(), 0);
  };

  if (phase === "loading") {
    return <Frame brand={brand}><p className="ix-lead">Loading your agreement…</p></Frame>;
  }
  if (phase === "gone" || !page) {
    return (
      <Frame brand={brand} title={phase === "error" ? "Something went wrong" : "This link isn't valid"}>
        <p className="ix-lead">{phase === "error" ? "Please try again in a moment."
          : "Please check the link you were sent, or get in touch with us."}</p>
      </Frame>
    );
  }
  if (page.state !== "open") {
    return <AfterSigning brand={brand} page={page} api={api} onChange={apply} />;
  }

  const index = STEPS.findIndex((s) => s.key === step);
  return (
    <div className="ix-root" style={brandStyle(brand)}>
      <Header brand={brand} />
      {step !== "welcome" && (
        <div className="ix-progress" aria-label={`Step ${index} of ${STEPS.length - 1}`}>
          <div className="ix-progress-bar"><span style={{ width:
            `${Math.round((index / (STEPS.length - 1)) * 100)}%` }} /></div>
          <p className="ix-progress-text">Step {index} of {STEPS.length - 1}
            <span className={`ix-saved ix-${saving || "idle"}`} aria-live="polite">
              {saving === "saving" ? "Saving…" : saving === "saved" ? "Saved"
                : saving === "retry" ? "Not saved yet, trying again…" : ""}</span>
          </p>
        </div>
      )}
      <main className="ix-main">
        <h1 className="ix-title" tabIndex={-1} ref={heading}>
          {step === "welcome" ? `Welcome${page.first_name ? `, ${page.first_name}` : ""}!`
            : STEPS[index].title}</h1>
        {step === "welcome" && <Welcome page={page} />}
        {step === "agreement" && <AgreementText page={page} blocks={blocks} />}
        {step === "details" && <DetailsForm page={page} details={details} update={update} />}
        {step === "sign" && <SignStep page={page} missing={missing} api={api} flush={flush}
          onSigned={(data) => { apply(data); window.scrollTo({ top: 0 }); }}
          back={() => void go("details")} />}
      </main>
      {step !== "sign" && (
        <nav className="ix-nav" aria-label="Agreement steps">
          {index > 0 ? <button type="button" className="ix-btn ix-btn-ghost"
            onClick={() => void go(STEPS[index - 1].key)}>Back</button> : <span />}
          <button type="button" className="ix-btn ix-btn-primary"
            onClick={() => void go(STEPS[index + 1].key)}>
            {step === "welcome" ? "Read the agreement" : step === "agreement"
              ? "Fill in your details" : "Continue to sign"}</button>
        </nav>
      )}
      <Footer brand={brand} />
    </div>
  );
}

function Frame({ brand, title, children }: { brand: Brand; title?: string;
  children: ReactNode }) {
  return (
    <div className="ix-root" style={brandStyle(brand)}>
      <Header brand={brand} />
      <main className="ix-main ix-message">
        {title && <h1 className="ix-title">{title}</h1>}
        {children}
      </main>
      <Footer brand={brand} />
    </div>
  );
}

function Welcome({ page }: { page: AgreementPage }) {
  return (
    <>
      <p className="ix-lead">Thank you for trusting your property to the care of the
        {" "}{page.brand_name} team, and congratulations on your decision to rent it.</p>
      <h2 className="ix-subtitle">Your next steps</h2>
      <ol className="ix-next">
        <li><strong>Read and sign your rental management agreement.</strong> It takes about ten
          minutes.</li>
        <li>{page.brand_name} countersigns it, and we email you the final copy.</li>
        <li>Tell us about your property in our onboarding form: right after you sign, or later
          from the link we email you.</li>
      </ol>
      <Note>Your details save as you go. You can stop at any time and come back with the same
        link.</Note>
      <Note tone="safe">This agreement never asks for your Social Security number or your bank
        details. You'll add those yourself, in your owner portal, later.</Note>
    </>
  );
}

function Terms({ page }: { page: AgreementPage }) {
  const t = page.terms;
  return (
    <section className="ix-terms" aria-label="Your terms">
      <h2 className="ix-subtitle" style={{ marginTop: 0 }}>Your terms</h2>
      <dl>
        <dt>Property</dt><dd>{t.property_address || "You'll confirm it in your details"}</dd>
        <dt>Commission split (section 15)</dt>
        <dd>You receive <strong>{t.owner_percent}%</strong> of rental revenue;
          {" "}{page.brand_name} receives <strong>{t.manager_percent}%</strong>.</dd>
        <dt>Additional items (section 30)</dt>
        <dd>{t.section_30.map((p, i) => <p key={i} style={{ margin: "0 0 6px" }}>{p}</p>)}</dd>
      </dl>
    </section>
  );
}

export function AgreementText({ page, blocks }: { page: AgreementPage; blocks: Block[] }) {
  return (
    <>
      <p className="ix-lead">Here is your agreement in full. The parts set for you are
        {" "}<mark className="ix-term">highlighted</mark>.</p>
      <Terms page={page} />
      <article className="ix-doc" aria-label={page.title}>
        {blocks.map((b, i) => <DocBlock key={i} block={b} page={page} />)}
      </article>
    </>
  );
}

function DocBlock({ block, page }: { block: Block; page: AgreementPage }) {
  switch (block.type) {
    case "title":
      return <p className="ix-doc-title">{block.text}</p>;
    case "heading":
      return <h3 className="ix-doc-heading">{block.text}</h3>;
    case "para":
      return (
        <p className={`ix-doc-p ix-indent-${block.indent}`}>
          {block.spans.map((s, i) => s.t === "bold" ? <strong key={i}>{s.v}</strong>
            : s.t === "term" ? <mark key={i} className="ix-term">{s.v}</mark>
            : <span key={i}>{s.v}</span>)}
        </p>
      );
    case "list":
      return (
        <ul className="ix-doc-list">
          {block.items.map((item, i) => (
            <li key={i} className={`ix-level-${item.level}`}>
              {item.spans.map((s) => s.v).join("")}</li>
          ))}
        </ul>
      );
    case "section_30":
      return <div className="ix-doc-s30">{block.paras.map((p, i) =>
        <p key={i}><mark className="ix-term">{p}</mark></p>)}</div>;
    case "owner_section":
      return (
        <div className="ix-doc-owner" aria-label="The owner's section">
          {block.lines.map((line, i) => "note" in line ? <p key={i}>{line.note}</p> : (
            <p key={i}>{line.fields.map((f) => (
              <span key={f.key} className="ix-doc-field">{f.label}{" "}
                <span className="ix-doc-value">{f.value || "—"}</span></span>
            ))}</p>
          ))}
        </div>
      );
    case "signatures":
      return (
        <div className="ix-doc-sigs">
          <p>THE PARTIES HERETO HAVE EXECUTED THIS AGREEMENT.</p>
          <p><strong>MANAGER</strong>, SKYRUN PARK CITY: {block.signer_name},
            {" "}{block.signer_title}. Signs after you.</p>
          <p>By signing below, you are indicating that you own all or part of the unit. You are
            also indicating that ANY AND ALL additional owners have signed below.</p>
          <p><strong>OWNER</strong>: you sign on the last step.
            {" "}(ALL owners of condo must sign)</p>
          <p className="ix-hint">{page.title}, #{page.number}</p>
        </div>
      );
    case "page_break":
      return <hr className="ix-doc-break" aria-hidden="true" />;
  }
}

function DetailsForm({ page, details, update }: { page: AgreementPage; details: Details;
  update: (next: Details) => void }) {
  const d = details;
  const set = (patch: Partial<Details>) => update({ ...d, ...patch });
  const mailing = d.mailing ?? {};
  const emergency = d.emergency ?? {};
  const staff = page.staff_address ?? {};
  const staffLine = [[staff.street, staff.unit].filter(Boolean).join(", "), staff.city,
    [staff.state, staff.zip].filter(Boolean).join(" ")].filter(Boolean).join(", ");
  const [correcting, setCorrecting] = useState(!staffLine || !!d.property_address?.street);
  const address = d.property_address ?? {};
  return (
    <div className="ix-section">
      <p className="ix-lead">This is the owner's section of the agreement. Everything here
        appears in your agreement as you enter it.</p>
      <Choice label="Who owns the property?" value={d.owner_type ?? "person"}
        onChange={(v) => set({ owner_type: v as "person" | "entity" })}
        options={[{ value: "person", label: "I do (a person)" },
                  { value: "entity", label: "A company or trust" }]} />
      {d.owner_type === "entity" && (
        <>
          <Text label="Owner of record (the company or trust's name)" value={d.entity_name}
            onChange={(v) => set({ entity_name: v })} autoComplete="organization" />
          <Text label="Your title" hint="For example: Manager, Trustee"
            value={d.signer_title} onChange={(v) => set({ signer_title: v })} />
        </>
      )}
      <div className="ix-grid2">
        <Text label={d.owner_type === "entity" ? "Your first name (the signer)" : "First name"}
          value={d.first_name} onChange={(v) => set({ first_name: v })}
          autoComplete="given-name" />
        <Text label={d.owner_type === "entity" ? "Your last name" : "Last name"}
          value={d.last_name} onChange={(v) => set({ last_name: v })}
          autoComplete="family-name" />
      </div>
      <Text label="Phone" type="tel" inputMode="tel" value={d.phone}
        onChange={(v) => set({ phone: v })} autoComplete="tel" />
      <Text label="Email address" type="email" inputMode="email" value={d.email}
        hint="Your signed agreement is emailed here."
        onChange={(v) => set({ email: v })} autoComplete="email" />
      <fieldset className="ix-fieldset">
        <legend className="ix-label">Mailing address</legend>
        <Text label="Street" value={mailing.street}
          onChange={(v) => set({ mailing: { ...mailing, street: v } })}
          autoComplete="address-line1" />
        <Text label="Apartment, suite (optional)" value={mailing.street2}
          onChange={(v) => set({ mailing: { ...mailing, street2: v } })}
          autoComplete="address-line2" />
        <div className="ix-grid3">
          <Text label="City" value={mailing.city}
            onChange={(v) => set({ mailing: { ...mailing, city: v } })}
            autoComplete="address-level2" />
          <Text label="State" value={mailing.state}
            onChange={(v) => set({ mailing: { ...mailing, state: v } })}
            autoComplete="address-level1" />
          <Text label="ZIP" value={mailing.zip} inputMode="numeric"
            onChange={(v) => set({ mailing: { ...mailing, zip: v } })}
            autoComplete="postal-code" />
        </div>
      </fieldset>
      <Text label="Business phone (optional)" type="tel" inputMode="tel"
        value={d.business_phone} onChange={(v) => set({ business_phone: v })} />
      <fieldset className="ix-fieldset">
        <legend className="ix-label">The property</legend>
        {staffLine && !correcting ? (
          <div className="ix-confirm">
            <p style={{ margin: 0 }}><strong>{staffLine}</strong></p>
            <p className="ix-hint">Is this the property's address?</p>
            <button type="button" className="ix-link" onClick={() => {
              setCorrecting(true);
              set({ property_address: { ...staff } });
            }}>Correct it</button>
          </div>
        ) : (
          <>
            {staffLine && <p className="ix-hint">We had: {staffLine}. Your correction goes in
              the agreement, and we'll see that you changed it.</p>}
            <Text label="Property street" value={address.street}
              onChange={(v) => set({ property_address: { ...address, street: v } })} />
            <Text label="Property unit (optional)" value={address.unit}
              onChange={(v) => set({ property_address: { ...address, unit: v } })} />
            <div className="ix-grid3">
              <Text label="Property city" value={address.city}
                onChange={(v) => set({ property_address: { ...address, city: v } })} />
              <Text label="Property state" value={address.state}
                onChange={(v) => set({ property_address: { ...address, state: v } })} />
              <Text label="Property ZIP" value={address.zip} inputMode="numeric"
                onChange={(v) => set({ property_address: { ...address, zip: v } })} />
            </div>
          </>
        )}
        <div className="ix-grid3">
          <Text label="Bedrooms" inputMode="numeric" value={String(d.bedrooms ?? "")}
            onChange={(v) => set({ bedrooms: v })} />
          <Text label="Bathrooms" inputMode="text" hint="Halves are fine: 2.5"
            value={String(d.bathrooms ?? "")} onChange={(v) => set({ bathrooms: v })} />
          <Text label="Square footage" inputMode="numeric" value={String(d.square_feet ?? "")}
            onChange={(v) => set({ square_feet: v })} />
        </div>
      </fieldset>
      <fieldset className="ix-fieldset">
        <legend className="ix-label">Emergency contact</legend>
        <p className="ix-hint">If only one owner, please list another person we could contact in
          case of an emergency.</p>
        <Text label="Their name" value={emergency.name}
          onChange={(v) => set({ emergency: { ...emergency, name: v } })} />
        <Text label="Their phone" type="tel" inputMode="tel" value={emergency.phone}
          onChange={(v) => set({ emergency: { ...emergency, phone: v } })} />
        <Text label="Their address (optional)" value={emergency.address}
          onChange={(v) => set({ emergency: { ...emergency, address: v } })} />
      </fieldset>
    </div>
  );
}

function SignStep({ page, missing, api, flush, onSigned, back }: {
  page: AgreementPage; missing: string[]; api: ReturnType<typeof agreementApi>;
  flush: () => Promise<boolean>; onSigned: (data: AgreementPage) => void; back: () => void;
}) {
  const [method, setMethod] = useState<"typed" | "drawn">("typed");
  const [typed, setTyped] = useState("");
  const [drawn, setDrawn] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const ready = agreed && (method === "typed" ? typed.trim().length > 0 : drawn.length > 0)
    && !missing.length;
  return (
    <div className="ix-section">
      {missing.length > 0 ? (
        <div className="ix-note ix-note-info">
          <p style={{ margin: "0 0 8px" }}>Before you sign, please add:</p>
          <ul style={{ margin: 0 }}>{missing.map((m) => <li key={m}>{m}</li>)}</ul>
          <button type="button" className="ix-link" onClick={back}>Back to your details</button>
        </div>
      ) : (
        <p className="ix-lead">You're signing the {page.title} with {page.brand_name}, as shown
          on the previous steps.</p>
      )}
      <div className="ix-sig">
        <div className="ix-sig-tabs" role="group" aria-label="How to sign">
          {(["typed", "drawn"] as const).map((m) => (
            <button key={m} type="button" aria-pressed={method === m}
              className={`ix-btn ix-btn-small ${method === m ? "ix-btn-primary" : "ix-btn-ghost"}`}
              onClick={() => setMethod(m)}>{m === "typed" ? "Type it" : "Draw it"}</button>
          ))}
        </div>
        {method === "typed" ? (
          <>
            <Text label="Your name, as your signature" value={typed} onChange={setTyped}
              autoComplete="name" />
            <div className="ix-sig-typed" aria-label="Your signature as it will appear">
              {typed || " "}</div>
          </>
        ) : <SignaturePad drawn={drawn} onDrawn={setDrawn} />}
        <label className="ix-sig-consent">
          <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)}
            aria-label="I agree to sign electronically" />
          <span>{page.consent}</span>
        </label>
      </div>
      {error && <p className="ix-error" role="alert">{error}</p>}
      <div className="ix-sign-actions">
        <button type="button" className="ix-btn ix-btn-ghost" onClick={back}>Back</button>
        <button type="button" className="ix-btn ix-btn-primary" disabled={!ready || busy}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              if (!(await flush())) throw new Error("Your details aren't saved yet. Try again.");
              onSigned(await api.sign({ method, typed, drawn, agreed }));
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}>{busy ? "Signing…" : "Sign the agreement"}</button>
      </div>
    </div>
  );
}

function AfterSigning({ brand, page, api, onChange }: { brand: Brand; page: AgreementPage;
  api: ReturnType<typeof agreementApi>; onChange: (p: AgreementPage) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [choice, setChoice] = useState(page.onboarding_choice);
  const email = page.details.email;
  const complete = page.state === "complete";
  const choose = async (c: "now" | "later") => {
    setBusy(true);
    setError("");
    try {
      const out = await api.onboarding(c);
      if (c === "now") {
        window.location.assign(out.link);
        return;
      }
      setChoice("later");
      onChange({ ...page, onboarding_choice: "later" });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Frame brand={brand} title={complete ? "Your agreement is complete" : "Thank you for signing!"}>
      {complete ? (
        <p className="ix-lead">Your rental management agreement is signed by you and by
          {" "}{page.brand_name}. The final copy was emailed to you.</p>
      ) : (
        <p className="ix-lead">Your copy{email ? <> was emailed to <strong>{email}</strong></> : ""}.
          It shows as awaiting {page.brand_name}'s signature until we countersign it, and we'll
          email you the final copy then.</p>
      )}
      {page.has_pdf && <p><a href={api.pdf} target="_blank" rel="noreferrer">Open your copy
        (PDF)</a></p>}
      <h2 className="ix-subtitle">Next: tell us about your property</h2>
      {choice === "later" ? (
        <>
          <Note>We've emailed you the link to our onboarding form. Most of what you told us is
            already filled in.</Note>
          <button type="button" className="ix-btn ix-btn-primary ix-btn-big" disabled={busy}
            onClick={() => void choose("now")}>Start it now instead</button>
        </>
      ) : (
        <>
          <p>Our onboarding form asks about your bedrooms, amenities and how guests get in. What
            you've told us so far is already filled in.</p>
          <div className="ix-choice-buttons">
            <button type="button" className="ix-btn ix-btn-primary ix-btn-big" disabled={busy}
              onClick={() => void choose("now")}>Complete onboarding now</button>
            <button type="button" className="ix-btn ix-btn-ghost ix-btn-big" disabled={busy}
              onClick={() => void choose("later")}>Later: email me the link</button>
          </div>
        </>
      )}
      {error && <p className="ix-error" role="alert">{error}</p>}
    </Frame>
  );
}
