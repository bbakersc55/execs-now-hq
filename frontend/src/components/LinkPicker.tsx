import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Company, Contact, Task, api } from "../lib/api";

export interface Links {
  contact: string | null; contactName?: string;
  company: string | null;
  task: string | null;
}

/**
 * FR-2.3 — at most one of a Contact or a Company, and independently a Task.
 * The first choice is ONE control with three positions, so the UI has no way
 * to select a contact and a company together (AC-2.2).
 */
export function LinkPicker({ value, onChange }: { value: Links; onChange: (v: Links) => void }) {
  const initialMode = value.contact ? "contact" : value.company ? "company" : "none";
  const [mode, setMode] = useState<"none" | "contact" | "company">(initialMode);
  const [term, setTerm] = useState("");

  const companies = useQuery<Company[]>({
    queryKey: ["companies"], queryFn: () => api.get<Company[]>("/api/companies/"),
    enabled: mode === "company",
  });
  const tasks = useQuery<Task[]>({ queryKey: ["tasks"], queryFn: () => api.get<Task[]>("/api/tasks/") });
  const found = useQuery<{ contacts: Contact[] }>({
    queryKey: ["link-search", term],
    queryFn: () => api.get(`/api/contacts/search/?q=${encodeURIComponent(term)}`),
    enabled: mode === "contact" && term.trim().length > 1,
  });

  function choose(next: "none" | "contact" | "company") {
    setMode(next);
    // Switching position clears the other link: never both.
    onChange({ ...value, contact: null, contactName: undefined, company: null });
  }

  return (
    <div className="field">
      <fieldset className="choices">
        <legend>Linked to</legend>
        <div className="options" role="radiogroup" aria-label="Link to a contact or a company">
          {(["none", "contact", "company"] as const).map((m) => (
            <label key={m}>
              <input type="radio" name="link-kind" value={m} checked={mode === m}
                onChange={() => choose(m)} />
              {m === "none" ? "Nothing" : m === "contact" ? "A contact" : "A company"}
            </label>
          ))}
        </div>
      </fieldset>

      {mode === "contact" && (
        value.contact ? (
          <p className="small">
            {value.contactName || "Selected contact"}{" "}
            <button className="ghost small" onClick={() => onChange({ ...value, contact: null, contactName: undefined })}>
              change
            </button>
          </p>
        ) : (
          <>
            <label htmlFor="link-contact-search">Find a contact by name</label>
            <input id="link-contact-search" placeholder="Start typing a name…" value={term}
              onChange={(e) => setTerm(e.target.value)} />
            <ul className="small" style={{ listStyle: "none", paddingLeft: 0 }}>
              {(found.data?.contacts ?? []).slice(0, 8).map((c) => (
                <li key={c.id}>
                  <button className="ghost small" onClick={() => onChange({
                    ...value, contact: c.id, contactName: `${c.first_name} ${c.last_name}`, company: null,
                  })}>{c.first_name} {c.last_name}</button>
                </li>
              ))}
            </ul>
          </>
        )
      )}

      {mode === "company" && (
        <>
          <label htmlFor="link-company">Company</label>
          <select id="link-company" value={value.company ?? ""}
            onChange={(e) => onChange({ ...value, company: e.target.value || null, contact: null })}>
            <option value="">Choose a company…</option>
            {(companies.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </>
      )}

      <label htmlFor="link-task" style={{ marginTop: ".6rem" }}>Task (optional, and separate from the above)</label>
      <select id="link-task" value={value.task ?? ""}
        onChange={(e) => onChange({ ...value, task: e.target.value || null })}>
        <option value="">No task</option>
        {(tasks.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
      </select>
    </div>
  );
}
