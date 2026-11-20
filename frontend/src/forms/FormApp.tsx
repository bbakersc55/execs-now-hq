/** The owner's form behind a personal link: one section per screen, phone
 *  first, saved as you go. White label: only the form's own brand appears. */
import {
  useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode,
} from "react";
import { FormError, ownerApi, type OwnerPage } from "./api";
import { Pending, PendingContext } from "./pending";
import { INTROS, SECTIONS, summarize } from "./sections";
import type { Answers, Brand, Ctx, FileRow, Secrets, Section } from "./types";
import { Note } from "./ui";

type Phase = "loading" | "open" | "submitted" | "expired" | "gone" | "error";
type Saving = "idle" | "saving" | "saved" | "retry";

export function brandStyle(brand: Brand): CSSProperties {
  const c = brand.colors;
  return {
    ["--ix-primary" as string]: c.primary, ["--ix-primary-dark" as string]: c.primary_dark,
    ["--ix-heading" as string]: c.heading, ["--ix-text" as string]: c.text,
    ["--ix-bg" as string]: c.background, ["--ix-accent" as string]: c.accent,
    ["--ix-error" as string]: c.error,
  };
}

export function Footer({ brand }: { brand: Brand }) {
  if (!brand.contact_phone && !brand.contact_email) return null;
  return (
    <footer className="ix-footer">
      {brand.contact_phone && <a href={`tel:${brand.contact_phone.replace(/[^\d+]/g, "")}`}>
        {brand.contact_phone}</a>}
      {brand.contact_phone && brand.contact_email && <span aria-hidden="true"> · </span>}
      {brand.contact_email && <a href={`mailto:${brand.contact_email}`}>{brand.contact_email}</a>}
    </footer>
  );
}

export function Header({ brand }: { brand: Brand }) {
  return (
    <header className="ix-header">
      {brand.logo ? <img src={brand.logo} alt={brand.brand_name} className="ix-logo" />
        : <span className="ix-wordmark">{brand.brand_name}</span>}
    </header>
  );
}

function Message({ brand, title, children }: { brand: Brand; title: string;
  children: ReactNode }) {
  return (
    <div className="ix-root" style={brandStyle(brand)}>
      <Header brand={brand} />
      <main className="ix-main ix-message">
        <h1 className="ix-title">{title}</h1>
        {children}
      </main>
      <Footer brand={brand} />
    </div>
  );
}

export function FormApp({ brand, token }: { brand: Brand; token: string | null }) {
  const api = useMemo(() => ownerApi(token ?? ""), [token]);
  const [phase, setPhase] = useState<Phase>(token ? "loading" : "gone");
  const [page, setPage] = useState<OwnerPage | null>(null);
  const [answers, setAnswers] = useState<Answers>({});
  const [secrets, setSecrets] = useState<Secrets>({ tax_id: null, wifi_password: false,
                                                   codes: {} });
  const [files, setFiles] = useState<FileRow[]>([]);
  const [saving, setSaving] = useState<Saving>("idle");
  const [stepKey, setStepKey] = useState<string>(() =>
    (typeof window !== "undefined" && window.location.hash.slice(1)) || "welcome");
  const [submitError, setSubmitError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef<Map<Section, unknown>>(new Map());
  const timer = useRef<number | undefined>(undefined);
  const chain = useRef<Promise<boolean>>(Promise.resolve(true));
  const heading = useRef<HTMLHeadingElement>(null);
  // Sensitive values typed but not saved yet (each SecretField adds itself).
  const unsaved = useMemo(() => new Pending(), []);
  const [moveError, setMoveError] = useState("");

  useEffect(() => {
    if (!token) return;
    api.load().then((data) => {
      setPage(data);
      setAnswers(data.answers ?? {});
      setSecrets(data.secrets ?? { tax_id: null, wifi_password: false, codes: {} });
      setFiles(data.files ?? []);
      setPhase(data.state);
    }).catch((e: unknown) => {
      const status = e instanceof FormError ? e.status : 0;
      setPhase(status === 410 ? "expired" : status === 404 ? "gone" : "error");
    });
  }, [api, token]);

  /** Saves the answers waiting, after any save already on its way, so a
   *  Submit never overtakes one; false if they couldn't be saved. */
  const flush = useCallback((): Promise<boolean> => {
    chain.current = chain.current.then(async () => {
      const batch = [...pending.current.entries()];
      pending.current.clear();
      if (!batch.length) return true;
      setSaving("saving");
      try {
        for (const [section, value] of batch) await api.saveSection(section, value);
        setSaving("saved");
        return true;
      } catch {
        for (const [section, value] of batch)
          if (!pending.current.has(section)) pending.current.set(section, value);
        setSaving("retry");
        window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => void flush(), 4000);
        return false;
      }
    });
    return chain.current;
  }, [api]);

  /** Everything typed, saved: the answers and any sensitive value. Continue,
   *  Back, Edit and Submit wait for it and stay put if it fails. */
  const saveAll = useCallback(async (): Promise<boolean> => {
    setMoveError("");
    const [secretsOk, answersOk] = await Promise.all([unsaved.flush(), flush()]);
    if (secretsOk && answersOk) return true;
    setMoveError(secretsOk ? "Your answers aren't saved yet. Check your connection, then try "
      + "again." : "Something you typed isn't saved yet. See the field marked above, then try "
      + "again.");
    window.setTimeout(() => document.querySelector<HTMLElement>(
      '.ix-main [aria-invalid="true"]')?.focus(), 0);
    return false;
  }, [flush, unsaved]);

  const update = useCallback(<K extends Section>(section: K, value: Answers[K]) => {
    setAnswers((a) => ({ ...a, [section]: value }));
    pending.current.set(section, value);
    setSaving("saving");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void flush(), 700);
  }, [flush]);

  useEffect(() => {
    const leave = (e: BeforeUnloadEvent) => {
      if (pending.current.size || unsaved.dirty()) { e.preventDefault(); void saveAll(); }
    };
    window.addEventListener("beforeunload", leave);
    return () => window.removeEventListener("beforeunload", leave);
  }, [saveAll, unsaved]);

  const steps = page?.form?.sections ?? [];
  const index = Math.max(0, steps.findIndex((s) => s.key === stepKey));
  const step = steps[index];
  const go = async (key: string) => {
    if (!(await saveAll())) return;
    setStepKey(key);
    window.history.replaceState(null, "", `#${key}`);
    window.scrollTo({ top: 0 });
    window.setTimeout(() => heading.current?.focus(), 0);
  };

  if (phase === "loading") {
    return <Message brand={brand} title={brand.title}><p aria-live="polite">Loading…</p></Message>;
  }
  if (phase === "expired") {
    return (
      <Message brand={brand} title="This link has expired">
        <p>For your security, links stop working after 30 days without use. Please ask
          {" "}{brand.brand_name} for a new one; everything you entered is still saved.</p>
      </Message>
    );
  }
  if (phase === "gone" || phase === "error" || !page) {
    return (
      <Message brand={brand} title={phase === "error" ? "Something went wrong"
        : "This link isn't valid"}>
        <p>{phase === "error" ? "Please try again in a minute." : "Please check the link you "
          + `were sent, or get in touch with ${brand.brand_name}.`}</p>
      </Message>
    );
  }
  const first = answers.about?.first_name || page.first_name;
  if (phase === "submitted") {
    return (
      <Message brand={brand} title={`Thank you${first ? `, ${first}` : ""}!`}>
        <p className="ix-lead">We have everything we need to get started.</p>
        <h2 className="ix-subtitle">What happens next</h2>
        <ol className="ix-next">
          <li>Our team reviews your answers and sets your home up.</li>
          <li>You'll get an invitation to your owner portal. That's where you add your bank
            details and, if you chose it, your Social Security number.</li>
          <li>We'll be in touch about photos, a walkthrough and your listing going live.</li>
        </ol>
        <div className="ix-another">
          <p>Have another property for us?</p>
          <button type="button" className="ix-btn ix-btn-primary" disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                const link = await api.another();
                window.location.assign(link);
              } catch (e) {
                setSubmitError((e as Error).message);
                setBusy(false);
              }
            }}>Add another property</button>
          <p className="ix-hint">Your details are carried over, so it's just the property.</p>
          {submitError && <p className="ix-error" role="alert">{submitError}</p>}
        </div>
      </Message>
    );
  }

  const form = page.form!;
  const ctx: Ctx = { form, answers, update, secrets, setSecrets, files, setFiles, api,
                     brand: brand.brand_name, mode: "owner" };
  const Body = SECTIONS[step.key];
  const last = index === steps.length - 1;
  const counted = steps.filter((s) => s.key !== "welcome");
  const position = counted.findIndex((s) => s.key === step.key) + 1;

  return (
    <PendingContext.Provider value={unsaved}>
    <div className="ix-root" style={brandStyle(brand)}>
      <Header brand={brand} />
      {step.key !== "welcome" && (
        <div className="ix-progress" aria-label={`Step ${position} of ${counted.length}`}>
          <div className="ix-progress-bar"><span style={{ width:
            `${Math.round((position / counted.length) * 100)}%` }} /></div>
          <p className="ix-progress-text">Step {position} of {counted.length}
            <span className={`ix-saved ix-${saving}`} aria-live="polite">
              {saving === "saving" ? "Saving…" : saving === "saved" ? "Saved"
                : saving === "retry" ? "Not saved yet, trying again…" : ""}</span>
          </p>
        </div>
      )}
      <main className="ix-main">
        <h1 className="ix-title" tabIndex={-1} ref={heading}>
          {step.key === "welcome" ? `Welcome${first ? `, ${first}` : ""}!` : step.title}</h1>
        {step.key === "welcome" && (
          <>
            <p className="ix-lead">Let's get your home set up with {brand.brand_name}. This takes
              about 15 to 20 minutes.</p>
            <h2 className="ix-subtitle">Have these handy</h2>
            <ul className="ix-handy">
              <li>Your mailing address and the property's details</li>
              <li>Bedrooms, beds and bathrooms</li>
              <li>Wi-Fi, door and alarm codes</li>
              <li>Your HOA's contact details, if you have one</li>
              <li>Your insurance declarations page, if you have it</li>
            </ul>
            <Note>Your answers save as you go. You can stop at any time and come back with the
              same link.</Note>
            <Note tone="safe">This form never asks for your Social Security number or your bank
              details. You'll add those yourself, in your owner portal, later.</Note>
          </>
        )}
        {INTROS[step.key] && <p className="ix-lead">{INTROS[step.key]}</p>}
        {Body && <div className="ix-section"><Body ctx={ctx} /></div>}
        {step.key === "review" && (
          <>
            <p className="ix-lead">Check everything over. Tap Edit to change anything.</p>
            {steps.filter((s) => SECTIONS[s.key]).map((s) => (
              <section key={s.key} className="ix-review" aria-label={s.title}>
                <header className="ix-block-head">
                  <h2>{s.title}</h2>
                  <button type="button" className="ix-link" onClick={() => void go(s.key)}>
                    Edit<span className="ix-sr"> {s.title}</span></button>
                </header>
                <ul>{summarize(ctx, s.key).map((line, i) => <li key={i}>{line}</li>)}
                  {!summarize(ctx, s.key).length && <li className="ix-muted">Nothing yet</li>}</ul>
              </section>
            ))}
            {submitError && <p className="ix-error" role="alert">{submitError}</p>}
          </>
        )}
        {moveError && <p className="ix-error ix-nav-error" role="alert">{moveError}</p>}
      </main>
      <nav className="ix-nav" aria-label="Form steps">
        {index > 0 ? <button type="button" className="ix-btn ix-btn-ghost"
          onClick={() => void go(steps[index - 1].key)}>Back</button> : <span />}
        {!last ? (
          <button type="button" className="ix-btn ix-btn-primary"
            onClick={() => void go(steps[index + 1].key)}>
            {step.key === "welcome" ? "Let's start" : "Continue"}</button>
        ) : (
          <button type="button" className="ix-btn ix-btn-primary" disabled={busy}
            onClick={async () => {
              setBusy(true);
              setSubmitError("");
              try {
                if (!(await saveAll())) return;
                await api.submit();
                setPhase("submitted");
                window.scrollTo({ top: 0 });
              } catch (e) {
                setSubmitError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}>{busy ? "Sending…" : "Submit"}</button>
        )}
      </nav>
      <Footer brand={brand} />
    </div>
    </PendingContext.Provider>
  );
}
