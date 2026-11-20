/** The owner form's own building blocks: big touch targets, a label on every
 *  field, errors in words beside the field, usable by keyboard. */
import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useSaver } from "./pending";
import type { Option, Range } from "./types";

export function Field({ label, hint, error, htmlFor, children }: {
  label: string; hint?: string; error?: string; htmlFor?: string; children: ReactNode;
}) {
  return (
    <div className={`ix-field${error ? " ix-has-error" : ""}`}>
      <label className="ix-label" htmlFor={htmlFor}>{label}</label>
      {hint && <p className="ix-hint">{hint}</p>}
      {children}
      {error && <p className="ix-error" role="alert">{error}</p>}
    </div>
  );
}

export function Text({ label, value, onChange, hint, error, type = "text", autoComplete,
  inputMode, placeholder }: {
  label: string; value: string | undefined; onChange: (v: string) => void; hint?: string;
  error?: string; type?: string; autoComplete?: string;
  inputMode?: "text" | "tel" | "email" | "numeric"; placeholder?: string;
}) {
  const id = useId();
  return (
    <Field label={label} hint={hint} error={error} htmlFor={id}>
      <input id={id} className="ix-input" type={type} value={value ?? ""}
        autoComplete={autoComplete} inputMode={inputMode} placeholder={placeholder}
        aria-invalid={error ? true : undefined}
        onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

export function Area({ label, value, onChange, hint, rows = 3 }: {
  label: string; value: string | undefined; onChange: (v: string) => void; hint?: string;
  rows?: number;
}) {
  const id = useId();
  return (
    <Field label={label} hint={hint} htmlFor={id}>
      <textarea id={id} className="ix-input ix-area" rows={rows} value={value ?? ""}
        onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

export function Select({ label, value, onChange, options, hint, empty = "Choose one" }: {
  label: string; value: string | number | null | undefined;
  onChange: (v: string) => void; options: Option[]; hint?: string; empty?: string;
}) {
  const id = useId();
  return (
    <Field label={label} hint={hint} htmlFor={id}>
      <select id={id} className="ix-input ix-select" value={value == null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value)}>
        <option value="">{empty}</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </Field>
  );
}

/** One answer from a few, as big cards. */
export function Choice({ label, options, value, onChange, hint, columns }: {
  label: string; options: Option[]; value: string | undefined;
  onChange: (v: string) => void; hint?: string; columns?: number;
}) {
  const name = useId();
  return (
    <fieldset className="ix-fieldset">
      <legend className="ix-label">{label}</legend>
      {hint && <p className="ix-hint">{hint}</p>}
      <div className={`ix-cards${columns ? " ix-cols" : ""}`}
        style={columns ? ({ "--ix-cols": columns } as CSSProperties) : undefined}>
        {options.map((o) => (
          <label key={o.value} className={`ix-card${value === o.value ? " ix-on" : ""}`}>
            <input type="radio" name={name} value={o.value} checked={value === o.value}
              onChange={() => onChange(o.value)} />
            <span>{o.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** Any number of answers, as big cards. */
export function Checks({ label, options, values, onChange, hint }: {
  label: string; options: Option[]; values: string[] | undefined;
  onChange: (v: string[]) => void; hint?: string;
}) {
  const chosen = new Set(values ?? []);
  return (
    <fieldset className="ix-fieldset">
      <legend className="ix-label">{label}</legend>
      {hint && <p className="ix-hint">{hint}</p>}
      <div className="ix-cards">
        {options.map((o) => (
          <label key={o.value} className={`ix-card ix-check${chosen.has(o.value) ? " ix-on" : ""}`}>
            <input type="checkbox" checked={chosen.has(o.value)} onChange={() => {
              const next = new Set(chosen);
              if (next.has(o.value)) next.delete(o.value); else next.add(o.value);
              onChange(options.map((x) => x.value).filter((v) => next.has(v)));
            }} />
            <span>{o.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function YesNo({ label, value, onChange, unsure, hint }: {
  label: string; value: string | undefined; onChange: (v: string) => void;
  unsure?: boolean; hint?: string;
}) {
  const options: Option[] = [{ value: "yes", label: "Yes" }, { value: "no", label: "No" }];
  if (unsure) options.push({ value: "unsure", label: "Not sure" });
  return <Choice label={label} options={options} value={value} onChange={onChange} hint={hint}
    columns={options.length} />;
}

export function Stepper({ label, value, onChange, min = 0, max = 20 }: {
  label: string; value: number; onChange: (v: number) => void; min?: number; max?: number;
}) {
  return (
    <div className="ix-stepper" role="group" aria-label={label}>
      <button type="button" className="ix-step" aria-label={`One fewer: ${label}`}
        disabled={value <= min} onClick={() => onChange(Math.max(min, value - 1))}>−</button>
      <output className="ix-count" aria-live="polite">{value}</output>
      <button type="button" className="ix-step" aria-label={`One more: ${label}`}
        disabled={value >= max} onClick={() => onChange(Math.min(max, value + 1))}>+</button>
    </div>
  );
}

export function Note({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "safe" }) {
  return <div className={`ix-note ix-note-${tone}`}>{children}</div>;
}

export function Ranges({ label, ranges, onChange, addLabel }: {
  label: string; ranges: Range[] | undefined; onChange: (r: Range[]) => void; addLabel: string;
}) {
  const rows = ranges ?? [];
  return (
    <fieldset className="ix-fieldset">
      <legend className="ix-label">{label}</legend>
      {rows.map((r, i) => (
        <div key={i} className="ix-range">
          <DateBox label="From" value={r.start}
            onChange={(v) => onChange(rows.map((x, j) => (j === i ? { ...x, start: v } : x)))} />
          <DateBox label="To" value={r.end}
            onChange={(v) => onChange(rows.map((x, j) => (j === i ? { ...x, end: v } : x)))} />
          <button type="button" className="ix-link ix-remove"
            onClick={() => onChange(rows.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      <button type="button" className="ix-btn ix-btn-ghost"
        onClick={() => onChange([...rows, { start: "", end: "" }])}>+ {addLabel}</button>
    </fieldset>
  );
}

function DateBox({ label, value, onChange }: {
  label: string; value: string; onChange: (v: string) => void;
}) {
  const id = useId();
  return (
    <div className="ix-date">
      <label htmlFor={id} className="ix-small-label">{label}</label>
      <input id={id} type="date" className="ix-input" value={value}
        onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

/** A value kept apart and encrypted: once saved it is never shown again here.
 *  The tax id shows its last four; a code or a password shows nothing.
 *
 *  It saves like every other answer (owner, 2026-11-20): a moment after the
 *  last key and at once on leaving the field, with "Saved securely" shown;
 *  there is no Save button to miss. Continue, Submit and Send save anything
 *  still waiting first (`pending.ts`). An error waits until the field is left
 *  or saved by one of those, so a half-typed Tax ID isn't scolded. */
export function SecretField({ label, hint, saved, last4, onSave, onClear, inputMode, name }: {
  label: string; hint?: string; saved: boolean; last4?: string;
  onSave: (v: string) => Promise<void>; onClear: () => Promise<void>;
  inputMode?: "text" | "numeric";
  /** "code:door", "tax_id"…: lets the review screen find the field. */
  name?: string;
}) {
  const id = useId();
  const [editing, setEditing] = useState(!saved);
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState<"" | "saving" | "saved" | "unsaved">("");
  const input = useRef<HTMLInputElement>(null);
  const typed = useRef("");                       // what is in the box
  const stored = useRef<string | null>(null);     // what this edit saved last
  const chain = useRef<Promise<boolean>>(Promise.resolve(true));
  const timer = useRef<number | undefined>(undefined);
  const focused = useRef(false);
  const savedNow = useRef(saved);
  savedNow.current = saved;
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const collapse = () => {
    typed.current = "";
    stored.current = null;
    setValue("");
    setStatus("");
    setEditing(false);
  };
  /** Save what is typed, after any save already on its way. `loud`: say why
   *  it failed (on leaving the field, or for Continue, Submit and Send). */
  const save = (loud: boolean): Promise<boolean> => {
    window.clearTimeout(timer.current);
    chain.current = chain.current.then(async () => {
      const v = typed.current;
      if (v === (stored.current ?? "")) return true;
      setStatus("saving");
      try {
        if (v.trim()) {
          await onSave(v);
          stored.current = v;
        } else {
          // Emptied after it saved: what it saved goes too.
          await onClear();
          stored.current = null;
        }
        setError("");
        setStatus(v.trim() ? "saved" : "");
        return true;
      } catch (e) {
        setStatus("unsaved");
        if (loud) setError((e as Error).message);
        return false;
      }
    });
    return chain.current;
  };
  useSaver({ flush: () => save(true), dirty: () => typed.current !== (stored.current ?? "") });

  if (saved && !editing) {
    return (
      <Field label={label} hint={hint} error={error}>
        <div className="ix-secret-saved">
          <span className="ix-lock" aria-hidden="true">●</span>
          <span>{last4 ? `Saved securely, ending ${last4}` : "Saved securely"}</span>
          <button type="button" className="ix-link" onClick={() => {
            setEditing(true);
            window.setTimeout(() => input.current?.focus(), 0);
          }}>Change<span className="ix-sr"> {label}</span></button>
          <button type="button" className="ix-link" onClick={async () => {
            try { setError(""); await onClear(); } catch (e) { setError((e as Error).message); }
          }}>Remove<span className="ix-sr"> {label}</span></button>
        </div>
      </Field>
    );
  }
  return (
    <Field label={label} hint={saved ? "Type the new one. Leave it empty to keep the saved "
      + "one." : hint} error={error} htmlFor={id}>
      <input id={id} ref={input} className="ix-input" type="text" autoComplete="off"
        spellCheck={false} inputMode={inputMode} value={value} data-secret={name}
        aria-invalid={error ? true : undefined}
        aria-describedby={`${id}-status`}
        onFocus={() => { focused.current = true; }}
        onChange={(e) => {
          typed.current = e.target.value;
          setValue(e.target.value);
          setStatus("");
          window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => void save(false), 700);
        }}
        onBlur={() => {
          focused.current = false;
          void save(true).then((ok) => {
            if (ok && !focused.current && (stored.current !== null
              || (savedNow.current && !typed.current))) collapse();
          });
        }} />
      <p id={`${id}-status`} className={`ix-secret-status ix-${status || "idle"}`}
        aria-live="polite">
        {status === "saving" ? "Saving…" : status === "saved" ? "Saved securely"
          : status === "unsaved" ? "Not saved yet" : ""}</p>
    </Field>
  );
}
