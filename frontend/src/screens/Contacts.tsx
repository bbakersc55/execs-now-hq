import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Card, Empty, Pill } from "../components/ui";
import { api, Contact } from "../lib/api";

export function Contacts() {
  const [term, setTerm] = useState("");
  const [active, setActive] = useState("");

  const list = useQuery<Contact[]>({
    queryKey: ["contacts"],
    queryFn: () => api.get<Contact[]>("/api/contacts/"),
  });

  const results = useQuery<{ contacts: Contact[]; companies: unknown[] }>({
    queryKey: ["search", active],
    queryFn: () => api.get(`/api/contacts/search/?q=${encodeURIComponent(active)}`),
    enabled: active.length > 0,
  });

  const rows = active ? results.data?.contacts ?? [] : list.data ?? [];

  return (
    <>
      <h2>Contacts</h2>
      <p className="sub">Everyone the practice deals with. Search covers names, titles, and background.</p>

      <Card>
        <form
          className="row"
          onSubmit={(e) => { e.preventDefault(); setActive(term.trim()); }}
        >
          <div style={{ flex: "3 1 320px" }}>
            <input
              placeholder="Search contacts…"
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              aria-label="Search contacts"
            />
          </div>
          <div style={{ flex: "0 0 auto" }}>
            <button className="primary" type="submit">Search</button>{" "}
            {active && <button type="button" onClick={() => { setTerm(""); setActive(""); }}>Clear</button>}
          </div>
        </form>
      </Card>

      <Card title={active ? `Results for “${active}”` : "All contacts"}>
        {rows.length === 0 ? (
          <Empty>No contacts{active ? " match that search" : " yet — import a CSV to get started"}.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th><th>Title</th><th>Stage</th><th>Types</th><th>Email</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td><Link to={`/contacts/${c.id}`}>{c.first_name} {c.last_name}</Link></td>
                  <td className="muted">{c.title || "—"}</td>
                  <td>{c.stage_code ? <Pill>{c.stage_code.replace(/_/g, " ")}</Pill> : "—"}</td>
                  <td>{c.type_codes.map((t) => <Pill key={t}>{t.replace(/_/g, " ")}</Pill>)}</td>
                  <td className="mono">{c.emails.find((e) => e.is_primary)?.address ?? c.emails[0]?.address ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
