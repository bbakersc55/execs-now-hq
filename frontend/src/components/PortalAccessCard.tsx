import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Company, Contact, Me, PortalAccess, api } from "../lib/api";
import { Banner, Card, Empty, Field, Pill } from "./ui";

/**
 * FR-3.33c to FR-3.33h — portal access and seats.
 *
 * Granting creates the login, consumes a seat and sends a sign-in link.
 * Revoking frees the seat and ends their sessions, and **deletes nothing**:
 * their contact, comments, tasks and stakeholder rows all stay, and they keep
 * receiving digests if they are still a stakeholder.
 */
export function PortalAccessCard({ me, company }: { me: Me; company: Company }) {
  const qc = useQueryClient();
  const [term, setTerm] = useState("");
  const [message, setMessage] = useState<{ kind: string; text: string } | null>(null);

  const access = useQuery<PortalAccess>({
    queryKey: ["portal-access", company.id],
    queryFn: () => api.get<PortalAccess>(`/api/portal-access/?company=${company.id}`),
    enabled: !!me.role && ["FF", "CF"].includes(me.role) && company.is_client_company,
    retry: false,
  });
  const found = useQuery<{ contacts: Contact[] }>({
    queryKey: ["portal-search", term],
    queryFn: () => api.get(`/api/contacts/search/?q=${encodeURIComponent(term)}`),
    enabled: term.trim().length > 1,
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["portal-access", company.id] });
  const grant = useMutation({
    mutationFn: (contact: string) => api.post("/api/portal-access/", { contact }),
    onSuccess: () => {
      setTerm("");
      setMessage({ kind: "ok", text: "Access granted and a sign-in link sent." });
      refresh();
    },
    onError: (e: Error) => setMessage({ kind: "bad", text: e.message }),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api.del<{ sessions_ended: number }>(`/api/portal-access/${id}/`),
    onSuccess: (r) => {
      setMessage({ kind: "ok", text: `Access revoked; ${r.sessions_ended} session(s) ended. `
        + "Their contact, comments and tasks are untouched." });
      refresh();
    },
    onError: (e: Error) => setMessage({ kind: "bad", text: e.message }),
  });

  if (!access.data) return null;
  const a = access.data;

  return (
    <Card title="Portal access">
      {message && <Banner kind={message.kind}>{message.text}</Banner>}
      <p className="small">
        {a.seat_count === null
          ? `${a.seats_in_use} in use, no seat limit set.`
          : `${a.seats_in_use} of ${a.seat_count} seat${a.seat_count === 1 ? "" : "s"} in use.`}
        {a.seats_available === 0 && " Free one, or raise the seat count, before granting another."}
      </p>
      {a.people.length === 0 ? <Empty>Nobody from this company can sign in yet.</Empty> : (
        <table>
          <thead><tr><th>Person</th><th>Role</th><th></th></tr></thead>
          <tbody>
            {a.people.map((p) => (
              <tr key={p.id}>
                <td>{p.name}<div className="when">{p.email}</div></td>
                <td><Pill>{p.role}</Pill></td>
                <td>
                  <button className="ghost small" onClick={() => {
                    if (confirm(`Revoke access for ${p.name}? They keep their contact record, `
                                + "comments and tasks, and any digests they are a stakeholder for.")) {
                      revoke.mutate(p.id);
                    }
                  }}>Revoke</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Field label="Give someone access">
        <input aria-label="Find a contact for portal access" placeholder="Start typing a name…"
          value={term} onChange={(e) => setTerm(e.target.value)} />
      </Field>
      <ul className="small" style={{ listStyle: "none", paddingLeft: 0 }}>
        {(found.data?.contacts ?? []).slice(0, 6).map((c) => (
          <li key={c.id}>
            <button className="ghost small" onClick={() => grant.mutate(c.id)}>
              {c.first_name} {c.last_name}
            </button>
          </li>
        ))}
      </ul>
      <p className="small muted">
        The company's main contact becomes its founder user; everyone else is an employee user.
      </p>
    </Card>
  );
}
