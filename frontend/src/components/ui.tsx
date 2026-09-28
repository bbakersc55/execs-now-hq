import { ReactNode, useEffect, useRef, useState } from "react";

export function Card({ title, children, actions, tone }: {
  // A node, not only a string: a card's heading is sometimes the control that
  // acts on it — the live session's section headers start that section's clock.
  title?: ReactNode; children: ReactNode; actions?: ReactNode;
  /** "current" lifts the one card being worked in. Elevation is spent where it
   *  means something rather than stamped on every block. */
  tone?: "current";
}) {
  return (
    <section className={tone ? `card ${tone}` : "card"}>
      {(title || actions) && (
        <div className="spread" style={{ marginBottom: ".75rem" }}>
          {title && <h3 style={{ margin: 0 }}>{title}</h3>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Banner({ kind = "info", children }: { kind?: string; children: ReactNode }) {
  return <div className={`banner ${kind}`}>{children}</div>;
}

export function Pill({ kind = "", children }: { kind?: string; children: ReactNode }) {
  return <span className={`pill ${kind}`}>{children}</span>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="muted small" style={{ padding: ".5rem 0" }}>{children}</p>;
}

/** One line naming where a contact stands in every pipeline they are in. */
export function positionsLabel(
  positions: { pipeline_name: string; stage_label: string }[] | undefined,
) {
  if (!positions || positions.length === 0) return "no pipeline";
  return positions.map((p) => `${p.pipeline_name}: ${p.stage_label}`).join(" · ");
}

export function when(value: string | null | undefined) {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

/**
 * How long is left, in the words a person reads at a glance: "in 6 hours".
 *
 * An absolute timestamp is read past. On 2026-09-18 two weekly digests expired
 * unapproved because "expires 9/18, 8:00 AM if not" did not register as *this
 * morning*. The absolute time still shows beside it; this is what carries.
 *
 * Rounding is down, never up, so it never promises time that is not there.
 */
export function countdown(value: string | null | undefined, now: number = Date.now()) {
  if (!value) return "—";
  const left = Date.parse(value) - now;
  if (Number.isNaN(left)) return "—";
  if (left <= 0) return "now";
  const minutes = Math.floor(left / 60_000);
  if (minutes < 1) return "in under a minute";
  if (minutes < 60) return `in ${minutes} minute${minutes === 1 ? "" : "s"}`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `in ${hours} hour${hours === 1 ? "" : "s"}`;
  return `in ${Math.floor(hours / 24)} days`;
}

/**
 * A confirmation that says so and then gets out of the way: "Saved" beside the
 * thing that was saved, for a few seconds. An edit that keeps you where you
 * are needs to tell you it landed; a banner that stays would be read as news.
 */
export function useFlash(ms = 2500): [string, (text: string) => void] {
  const [text, setText] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const flash = (next: string) => {
    clearTimeout(timer.current);
    setText(next);
    timer.current = setTimeout(() => setText(""), ms);
  };
  return [text, flash];
}

/** Where a `useFlash` confirmation shows, inline. Announced, not focused. */
export function Flash({ text }: { text: string }) {
  return <span className="flash" role="status">{text}</span>;
}

const toastListeners = new Set<(text: string) => void>();

/**
 * The same confirmation for a screen you have just been returned to — after
 * the task sheet closes, say. Global rather than carried in the URL's state,
 * because "returned to" is often a Back to wherever you came from, and Back
 * cannot carry anything with it.
 */
export function toast(text: string) {
  toastListeners.forEach((listener) => listener(text));
}

/** Where `toast()` shows. Mounted once, in the app shell. */
export function ToastHost() {
  const [text, flash] = useFlash();
  useEffect(() => {
    toastListeners.add(flash);
    return () => { toastListeners.delete(flash); };
  });
  if (!text) return null;
  return <div className="toast" role="status">{text}</div>;
}
