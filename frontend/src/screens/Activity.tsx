import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Banner, Card, Empty, Field, when } from "../components/ui";
import {
  ACTIVITY_CATEGORIES, ActivityEntry, Company, Contact, Me, PortalPerson, api,
} from "../lib/api";

const LINK: Record<string, string> = {
  task: "/tasks", project: "/work/projects", goal: "/work/goals",
  note: "/notes", outbox_message: "/outbox",
};

const CATEGORY_LABELS: Record<string, string> = {
  work: "Work", comment: "Comments", note: "Notes", email: "Email",
  pipeline: "Pipeline", import: "Imports", portal: "Portal access",
  act_as: "Acting as", digest: "Digests", settings: "Settings",
};

const TENANT = ["FF", "CF", "VA"];

/**
 * The practice's activity feed — everything across the accounts, newest first.
 *
 * **This replaced the client's activity log.** FR-3.41 gave the log to FCC and
 * ECC; the owner reversed that on 2026-09-16 after using it, because the value
 * is to the practice rather than to the client. A founder's window into the work
 * is the value report (Module 4B), not an audit feed of their own company.
 *
 * Read-only for every role, with no exception and no write path behind it.
 */
export function Activity({ me }: { me: Me }) {
  const [company, setCompany] = useState("");
  const [contact, setContact] = useState("");
  const [actor, setActor] = useState("");
  const [category, setCategory] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");

  const isTenant = !!me.role && TENANT.includes(me.role);

  const query = new URLSearchParams();
  if (company) query.set("company", company);
  if (contact) query.set("contact", contact);
  if (actor) query.set("actor", actor);
  if (category) query.set("category", category);
  // A date alone is midnight local; `until` covers the whole day chosen.
  if (since) query.set("since", `${since}T00:00:00`);
  if (until) query.set("until", `${until}T23:59:59`);

  const log = useQuery<ActivityEntry[]>({
    queryKey: ["activity", query.toString()],
    queryFn: () => api.get<ActivityEntry[]>(`/api/activity/?${query.toString()}`),
    enabled: isTenant,
    refetchInterval: 60_000,
  });
  const companies = useQuery<Company[]>({
    queryKey: ["companies"], queryFn: () => api.get<Company[]>("/api/companies/"),
    enabled: isTenant,
  });
  const contacts = useQuery<Contact[]>({
    queryKey: ["contacts"], queryFn: () => api.get<Contact[]>("/api/contacts/"),
    enabled: isTenant,
  });
  const people = useQuery<PortalPerson[]>({
    queryKey: ["portal-people"], queryFn: () => api.get<PortalPerson[]>("/api/portal-people/"),
    enabled: isTenant,
  });

  if (!isTenant) return <Banner kind="bad">Not available.</Banner>;
  if (log.isError) return <Banner kind="bad">The activity feed is not available to you.</Banner>;

  const rows = log.data ?? [];
  const staff = (people.data ?? []).filter((p) => TENANT.includes(p.role));
  const filtered = !!(company || contact || actor || category || since || until);
  const clear = () => {
    setCompany(""); setContact(""); setActor(""); setCategory(""); setSince(""); setUntil("");
  };

  return (
    <>
      <h2>Activity</h2>
      <p className="sub">
        Everything happening across your accounts, newest first — your team's work as well
        as your own. Nobody can edit or remove an entry.
      </p>

      <Card actions={filtered
        ? <button className="ghost" onClick={clear}>Clear filters</button> : undefined}>
        <div className="row">
          <Field label="Company">
            <select aria-label="Filter by company" value={company}
              onChange={(e) => setCompany(e.target.value)}>
              <option value="">Any company</option>
              {(companies.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </Field>
          <Field label="Contact">
            <select aria-label="Filter by contact" value={contact}
              onChange={(e) => setContact(e.target.value)}>
              <option value="">Anyone</option>
              {(contacts.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>{c.first_name} {c.last_name}</option>
              ))}
            </select>
          </Field>
          <Field label="Done by">
            <select aria-label="Filter by who acted" value={actor}
              onChange={(e) => setActor(e.target.value)}>
              <option value="">Anyone</option>
              {staff.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </Field>
          <Field label="Type">
            <select aria-label="Filter by type" value={category}
              onChange={(e) => setCategory(e.target.value)}>
              <option value="">Everything</option>
              {ACTIVITY_CATEGORIES.map((c) => (
                <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>
              ))}
            </select>
          </Field>
          <Field label="From">
            <input aria-label="From date" type="date" value={since}
              onChange={(e) => setSince(e.target.value)} />
          </Field>
          <Field label="To">
            <input aria-label="To date" type="date" value={until}
              onChange={(e) => setUntil(e.target.value)} />
          </Field>
        </div>
      </Card>

      <Card>
        {log.isLoading ? <p>Loading…</p> : rows.length === 0 ? (
          <Empty>{filtered ? "Nothing matches those filters." : "Nothing has happened yet."}</Empty>
        ) : (
          <ul className="timeline">
            {rows.map((e) => (
              <li key={e.id}>
                <div>
                  <span className="pill">{CATEGORY_LABELS[e.category] ?? e.category}</span>{" "}
                  <strong>{e.by}</strong>
                  {e.on_behalf_of && <> on behalf of <strong>{e.on_behalf_of}</strong></>}{" "}
                  {e.text}
                </div>
                <div className="when">
                  {when(e.at)}
                  {e.company && <> · {e.company.name}</>}
                  {e.contact && <> · {e.contact.name}</>}
                  {e.entity && LINK[e.entity.type] && (
                    <> · <Link to={`${LINK[e.entity.type]}/${e.entity.id}`}>open</Link></>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <p className="small muted">
        Showing {rows.length}{rows.length === 200 && " (the most recent 200)"}.
      </p>
    </>
  );
}
