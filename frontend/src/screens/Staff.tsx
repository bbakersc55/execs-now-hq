import { PageHead } from "../components/shell";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Card, Empty, Field, Pill, when } from "../components/ui";
import { api, Me, StaffMember } from "../lib/api";
import { STAFF_ROLES, roleLabel } from "../lib/roles";

export function Staff({ me }: { me: Me }) {
  const qc = useQueryClient();
  // The example address is at the inviter's own domain: Google sign-in is
  // restricted to it (banner below). Never another practice's domain.
  const domain = me.email.split("@")[1] || "example.com";
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("VA");
  const [note, setNote] = useState("");

  const staff = useQuery<StaffMember[]>({
    queryKey: ["staff"], queryFn: () => api.get<StaffMember[]>("/api/staff/"),
  });

  const invite = useMutation({
    mutationFn: () => api.post("/api/staff/", { email, role, full_name: name }),
    onSuccess: () => {
      setNote(`Invited ${email}. They can now sign in with Google using that address.`);
      setEmail(""); setName("");
      qc.invalidateQueries({ queryKey: ["staff"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  const changeRole = useMutation({
    mutationFn: (v: { id: string; role: string }) =>
      api.post(`/api/staff/${v.id}/change-role/`, { role: v.role }),
    onSuccess: () => {
      setNote("Role changed. It takes effect on their next request.");
      qc.invalidateQueries({ queryKey: ["staff"] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.post<{ cascade: Record<string, number> }>(
      `/api/staff/${id}/remove/`
    ),
    onSuccess: (data) => {
      const c = data.cascade;
      setNote(
        `Removed. Sessions invalidated: ${c.sessions_invalidated}. ` +
        `Client assignments closed: ${c.assignments_closed}. ` +
        `Gmail connections removed: ${c.gmail_connections_removed}. ` +
        `Everything they created stays on the record.`
      );
      qc.invalidateQueries({ queryKey: ["staff"] });
    },
  });

  return (
    <>
      <PageHead title="Team"
        sub="Your practice's own people. Sign-in is invite-only — an address with no membership
        here is refused at Google." />

      {note && <Banner kind="ok">{note}</Banner>}
      <Banner kind="info">
        Google sign-in is restricted to your Workspace domain, so an associate or assistant
        needs an account at that domain. Client users are different — they get portal access on a
        contact and sign in by magic link.
      </Banner>

      <Card title="Invite someone">
        <div className="row">
          <Field label="Email"><input value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder={`name@${domain}`} /></Field>
          <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Role">
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              {[...STAFF_ROLES].reverse().map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
            </select>
          </Field>
          <div style={{ flex: "0 0 auto" }}>
            <button className="primary" disabled={!email || invite.isPending}
              onClick={() => invite.mutate()}>Invite</button>
          </div>
        </div>
      </Card>

      <Card title="Who is on the team">
        {(staff.data ?? []).length === 0 ? <Empty>Nobody yet.</Empty> : (
          <table>
            <thead><tr><th>Person</th><th>Role</th><th>Invited</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {staff.data!.map((m) => (
                <tr key={m.id}>
                  <td>{m.full_name || "—"}<div className="muted mono small">{m.email}</div></td>
                  <td>
                    <select value={m.role} disabled={!m.is_active}
                      onChange={(e) => changeRole.mutate({ id: m.id, role: e.target.value })}>
                      {STAFF_ROLES.map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
                    </select>
                  </td>
                  <td className="muted small">{when(m.invited_at)}</td>
                  <td>{m.is_active
                    ? <Pill kind="ok">active</Pill>
                    : <Pill kind="bad">removed {when(m.revoked_at)}</Pill>}</td>
                  <td className="right">
                    {m.is_active && (
                      <button className="danger" onClick={() => remove.mutate(m.id)}>Remove</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted small" style={{ marginBottom: 0 }}>
          Removing someone ends their sessions, closes their client assignments, and
          disconnects their Gmail. Their contacts, tasks, notes, and sent mail remain.
        </p>
      </Card>
    </>
  );
}
