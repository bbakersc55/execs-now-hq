import { ReactNode, useEffect, useState } from "react";
import { X } from "lucide-react";
import { Link } from "react-router-dom";

/**
 * The pieces every screen is built from, per `docs/design_brief.md` Tier 1.
 *
 * They exist so the rules in the brief are kept in one place rather than
 * remembered on each screen: **one primary action per screen**, at the top
 * right of the page header; a breadcrumb only on a detail page; elevation only
 * on the thing in focus.
 */

/** Initials, and a tint derived from the name so the same person is the same
 *  colour everywhere. No photographs exist in Beta and none are invented. */
export function Avatar({ name, size }: { name?: string | null; size?: "lg" }) {
  const initials = (name ?? "").split(/\s+/).filter(Boolean).slice(0, 2)
    .map((part) => part[0]!.toUpperCase()).join("");
  const hue = [...(name ?? "")].reduce((total, ch) => total + ch.charCodeAt(0), 0) % 360;
  return (
    <span className={`avatar${size === "lg" ? " lg" : ""}${initials ? "" : " none"}`}
      title={name || "unassigned"} aria-hidden={!name}
      style={initials ? { background: `hsl(${hue} 42% 32%)` } : undefined}>
      {initials || "—"}
    </span>
  );
}

export function PageHead({ title, sub, crumbs, action }: {
  title: ReactNode; sub?: ReactNode;
  /** Detail pages only — the brief puts it above the title. */
  crumbs?: { to: string; label: string }[];
  /** The screen's single primary action. */
  action?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div className="titles">
        {crumbs && crumbs.length > 0 && (
          <nav className="crumbs" aria-label="Breadcrumb">
            {crumbs.map((crumb, index) => (
              <span key={crumb.to} className="inline">
                {index > 0 && <span aria-hidden="true">/</span>}
                <Link to={crumb.to}>{crumb.label}</Link>
              </span>
            ))}
          </nav>
        )}
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      {action}
    </header>
  );
}

/** One active filter. The `×` clears that filter and nothing else. */
export function Chip({ label, onClear }: { label: ReactNode; onClear?: () => void }) {
  return (
    <span className="chip">
      {label}
      {onClear && (
        <button type="button" aria-label={`Clear filter ${typeof label === "string" ? label : ""}`}
          onClick={onClear}><X size={14} /></button>
      )}
    </span>
  );
}

export function FilterBar({ children, onClearAll }: {
  children: ReactNode; onClearAll?: () => void;
}) {
  return (
    <div className="filters">
      {children}
      {onClearAll && (
        <button className="link small" onClick={onClearAll}>Clear all</button>
      )}
    </div>
  );
}

/**
 * The focused panel the brief asks for: a right-side sheet, elevated, closed by
 * Escape or the button, with the page behind it left where it was.
 */
export function Sheet({ title, onClose, children }: {
  title: ReactNode; onClose: () => void; children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="sheet-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="sheet" role="dialog" aria-modal="true" aria-label="Task">
        <div className="sheet-head">
          <div style={{ minWidth: 0 }}>{title}</div>
          <button className="icon-button" aria-label="Close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        {children}
      </aside>
    </>
  );
}

/** Remembered per person in this browser — the app has no per-user settings
 *  table, and FR-3.39a's remembered filter already works this way. */
export function useRemembered(key: string, fallback: boolean) {
  const [value, setValue] = useState(() => {
    try { return localStorage.getItem(key) === null ? fallback
      : localStorage.getItem(key) === "1"; } catch { return fallback; }
  });
  useEffect(() => {
    try { localStorage.setItem(key, value ? "1" : "0"); } catch { /* private window */ }
  }, [key, value]);
  return [value, setValue] as const;
}


/**
 * The whole email, as it will send, above the button that sends it.
 *
 * The incident of 2026-09-22: a panel showed the opening line the fractional
 * had written and not the questions underneath it, and six broken questions
 * reached a prospect. **A send panel shows the body or it does not send.**
 */
export function SendPreview({ preview, loading }: {
  preview?: { subject: string; to_address: string; from_address: string;
              body_text: string } | null;
  loading?: boolean;
}) {
  if (loading) return <p className="small muted">Rendering the email…</p>;
  if (!preview) return null;
  return (
    <div className="send-preview">
      <p className="tiny muted" style={{ margin: 0 }}>
        To {preview.to_address || "—"} · from {preview.from_address || "—"}
      </p>
      <p className="small" style={{ margin: "2px 0 8px", fontWeight: 600 }}>
        {preview.subject}
      </p>
      <pre aria-label="The email as it will send">{preview.body_text}</pre>
    </div>
  );
}
