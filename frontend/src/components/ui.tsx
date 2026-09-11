import { ReactNode } from "react";

export function Card({ title, children, actions }: {
  title?: string; children: ReactNode; actions?: ReactNode;
}) {
  return (
    <section className="card">
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
