import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Company, Me, PortalAccess, PortalCandidates, api } from "../lib/api";
import { ActAsButton } from "./ActAs";
import { Banner, Card, Empty, Field } from "./ui";

export const PORTAL_ROLES = [
  { value: "FCC", label: "Founder (FCC)" },
  { value: "ECC", label: "Employee (ECC)" },
];

/**
 * Seats in use and who holds them, for one client company.
 *
 * One query, shared by the company header and this card, so the two can never
 * disagree: the header used to read the company record and said "2 of 3 seats
 * used" after a revoke while this card said "1 of 3" until a reload.
 */
export function usePortalAccess(me: Me, company: Company) {
  return useQuery<PortalAccess>({
    queryKey: ["portal-access", company.id],
    queryFn: () => api.get<PortalAccess>(`/api/portal-access/?company=${company.id}`),
    enabled: !!me.role && ["FF", "CF"].includes(me.role) && company.is_client_company,
    retry: false,
  });
}

/**
 * FR-3.33c to FR-3.33i — portal access and seats.
 *
 * Granting creates the login, consumes a seat and sends a sign-in link, as the
 * role chosen (preselected to the server's default: FCC for the primary
 * contact). Revoking frees the seat and ends their sessions, and **deletes
 * nothing**: their contact, comments, tasks and stakeholder rows all stay, and
 * they keep receiving digests if they are still a stakeholder. Changing a role
 * from founder to employee ends their sessions the same way; they keep access.
 *
 * The people who can be granted are **this company's contacts**, listed
 * without typing anything: the box narrows that list rather than being the only
 * way to reach it.
 */
export function PortalAccessCard({ me, company }: { me: Me; company: Company }) {
  const qc = useQueryClient();
  const [term, setTerm] = useState("");
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ kind: string; text: string } | null>(null);

  const access = usePortalAccess(me, company);
  const candidates = useQuery<PortalCandidates>({
    queryKey: ["portal-candidates", company.id, term.trim()],
    queryFn: () => api.get<PortalCandidates>(
      `/api/portal-access/candidates/?company=${company.id}`
      + (term.trim() ? `&q=${encodeURIComponent(term.trim())}` : "")),
    enabled: !!me.role && ["FF", "CF"].includes(me.role) && company.is_client_company,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["portal-access", company.id] });
    qc.invalidateQueries({ queryKey: ["portal-candidates", company.id] });
    qc.invalidateQueries({ queryKey: ["company", company.id] });
    qc.invalidateQueries({ queryKey: ["companies"] });
  };
  const grant = useMutation({
    mutationFn: (body: { contact: string; role: string }) => api.post("/api/portal-access/", body),
    onSuccess: () => {
      setTerm("");
      setChosen({});
      setMessage({ kind: "ok", text: "Access granted and a sign-in link sent." });
      refresh();
    },
    onError: (e: Error) => setMessage({ kind: "bad", text: e.message }),
  });
  const changeRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) =>
      api.patch<{ role: string; sessions_ended: number }>(`/api/portal-access/${id}/`, { role }),
    onSuccess: (r) => {
      setMessage({ kind: "ok", text: r.role === "FCC"
        ? "Role changed to founder. Nothing else changed."
        : `Role changed to employee; ${r.sessions_ended} session(s) ended. `
          + "They keep access and sign in again with a fresh link." });
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
  // Anyone already signed in is in the table above, not offered again below.
  const granted = new Set(a.people.map((p) => p.contact));
  const waiting = (candidates.data?.people ?? []).filter((p) => !granted.has(p.contact));

  return (
    <Card title="Portal access">
      {message && <Banner kind={message.kind}>{message.text}</Banner>}
      <p className="small">
        {a.seat_count === null
          ? "No seats allocated yet — set a client seat count on the company before granting access."
          : `${a.seats_in_use} of ${a.seat_count} seat${a.seat_count === 1 ? "" : "s"} in use.`}
        {a.seat_count !== null && a.seats_available === 0
          && " Free one, or raise the seat count, before granting another."}
      </p>
      {a.people.length === 0 ? <Empty>Nobody from this company can sign in yet.</Empty> : (
        <table>
          <thead><tr><th>Person</th><th>Role</th><th></th></tr></thead>
          <tbody>
            {a.people.map((p) => (
              <tr key={p.id}>
                <td>{p.name}<div className="when">{p.email}</div></td>
                <td>
                  <select aria-label={`Role for ${p.name}`} value={p.role}
                    disabled={changeRole.isPending}
                    onChange={(e) => {
                      const role = e.target.value;
                      if (role === "ECC" && p.role === "FCC" && !confirm(
                        `Change ${p.name} to an employee user? Their sessions and any unused `
                        + "sign-in links end now. They keep access and sign in again.")) {
                        return;
                      }
                      changeRole.mutate({ id: p.id, role });
                    }}>
                    {PORTAL_ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                  </select>
                </td>
                <td>
                  {/* FR-3.42 — see exactly what they see; no email while acting. */}
                  {!me.acting && <><ActAsButton membership={p.id} name={p.name} />{" "}</>}
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
        <input aria-label="Narrow this company's people" placeholder="Narrow by name or email…"
          value={term} onChange={(e) => setTerm(e.target.value)} />
      </Field>
      {waiting.length === 0 ? (
        <Empty>
          {term.trim()
            ? `Nobody at ${company.name} matches “${term.trim()}”.`
            : `Everyone at ${company.name} already has access. Add a contact to the company first.`}
        </Empty>
      ) : (
        <ul className="small" style={{ listStyle: "none", paddingLeft: 0 }}>
          {waiting.map((p) => {
            const role = chosen[p.contact] ?? p.role;
            return (
              <li key={p.contact} style={{ padding: ".2rem 0" }}>
                <button className="ghost small" disabled={!!p.refusal || grant.isPending}
                  title={p.refusal ?? ""} onClick={() => grant.mutate({ contact: p.contact, role })}>
                  Grant
                </button>{" "}
                {!p.refusal && (
                  <select aria-label={`Grant ${p.name} as`} value={role}
                    onChange={(e) => setChosen({ ...chosen, [p.contact]: e.target.value })}>
                    {PORTAL_ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                  </select>
                )}{" "}
                {p.name} <span className="muted">{p.email || "no email"}</span>
                {p.refusal && <div className="muted" style={{ paddingLeft: "3.6rem" }}>{p.refusal}</div>}
              </li>
            );
          })}
        </ul>
      )}
      <p className="small muted">
        The company's primary contact is offered as its founder user and everyone else as an
        employee user; choose otherwise before granting, or change a role above.
      </p>
    </Card>
  );
}
