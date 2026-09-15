import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Me, PortalCandidates, api } from "../lib/api";
import { PORTAL_ROLES } from "./PortalAccessCard";
import { Banner, Card } from "./ui";

/**
 * Grant portal access to the contact you are looking at.
 *
 * The company screen's picker is a convenience; this is the path that cannot
 * fail to find anyone, because there is nothing to find — you are already on
 * the person. Whether a grant is possible, the sentence saying why it is not,
 * and the role preselected (FCC for the company's primary contact) all come
 * from the server, so this card never decides eligibility for itself.
 */
export function GrantPortalAccess({ me, contactId }: { me: Me; contactId: string }) {
  const qc = useQueryClient();
  const [message, setMessage] = useState<{ kind: string; text: string } | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const mayManage = !!me.role && ["FF", "CF"].includes(me.role);

  const candidate = useQuery<PortalCandidates>({
    queryKey: ["portal-candidate", contactId],
    queryFn: () => api.get<PortalCandidates>(`/api/portal-access/candidates/?contact=${contactId}`),
    enabled: mayManage,
    retry: false,
  });

  const grant = useMutation({
    mutationFn: (role: string) => api.post("/api/portal-access/", { contact: contactId, role }),
    onSuccess: () => {
      setMessage({ kind: "ok", text: "Access granted and a sign-in link sent." });
      setChosen(null);
      qc.invalidateQueries({ queryKey: ["portal-candidate", contactId] });
      qc.invalidateQueries({ queryKey: ["portal-access"] });
    },
    onError: (e: Error) => setMessage({ kind: "bad", text: e.message }),
  });

  if (!mayManage || !candidate.data) return null;
  const person = candidate.data.people[0];
  if (!person) return null;
  const { seat_count, seats_in_use, company, company_name } = candidate.data;
  const role = chosen ?? person.role;

  return (
    <Card title="Portal access">
      {message && <Banner kind={message.kind}>{message.text}</Banner>}
      {person.refusal ? (
        <p className="small muted">{person.refusal}</p>
      ) : (
        <>
          <p className="small">
            Sign them in to {company
              ? <Link to={`/companies/${company}`}>{company_name}</Link>
              : "their company"}'s portal as{" "}
            <select aria-label="Portal role" value={role} onChange={(e) => setChosen(e.target.value)}>
              {PORTAL_ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
            {seat_count !== null
              && ` · ${seats_in_use} of ${seat_count} seat${seat_count === 1 ? "" : "s"} in use`}
          </p>
          <button className="primary" disabled={grant.isPending}
            onClick={() => grant.mutate(role)}>Grant portal access</button>
          <p className="small muted">
            This creates their login, consumes a seat and emails them a sign-in link.
            It sends nothing else, and they see only their own company. The company's
            primary contact is offered as founder; anyone else as employee.
          </p>
        </>
      )}
    </Card>
  );
}
