import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Me, PortalCandidates, api } from "../lib/api";
import { Banner, Card, Pill } from "./ui";

/**
 * Grant portal access to the contact you are looking at.
 *
 * The company screen's picker is a convenience; this is the path that cannot
 * fail to find anyone, because there is nothing to find — you are already on
 * the person. Whether a grant is possible, and the sentence saying why it is
 * not, both come from the server (`portal.refusal_for`), so this card never
 * decides eligibility for itself.
 */
export function GrantPortalAccess({ me, contactId }: { me: Me; contactId: string }) {
  const qc = useQueryClient();
  const [message, setMessage] = useState<{ kind: string; text: string } | null>(null);
  const mayManage = !!me.role && ["FF", "CF"].includes(me.role);

  const candidate = useQuery<PortalCandidates>({
    queryKey: ["portal-candidate", contactId],
    queryFn: () => api.get<PortalCandidates>(`/api/portal-access/candidates/?contact=${contactId}`),
    enabled: mayManage,
    retry: false,
  });

  const grant = useMutation({
    mutationFn: () => api.post("/api/portal-access/", { contact: contactId }),
    onSuccess: () => {
      setMessage({ kind: "ok", text: "Access granted and a sign-in link sent." });
      qc.invalidateQueries({ queryKey: ["portal-candidate", contactId] });
      qc.invalidateQueries({ queryKey: ["portal-access"] });
    },
    onError: (e: Error) => setMessage({ kind: "bad", text: e.message }),
  });

  if (!mayManage || !candidate.data) return null;
  const person = candidate.data.people[0];
  if (!person) return null;
  const { seat_count, seats_in_use, company, company_name } = candidate.data;

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
            <Pill>{person.role === "FCC" ? "founder" : "employee"}</Pill>
            {seat_count !== null
              && ` · ${seats_in_use} of ${seat_count} seat${seat_count === 1 ? "" : "s"} in use`}
          </p>
          <button className="primary" disabled={grant.isPending}
            onClick={() => grant.mutate()}>Grant portal access</button>
          <p className="small muted">
            This creates their login, consumes a seat and emails them a sign-in link.
            It sends nothing else, and they see only their own company.
          </p>
        </>
      )}
    </Card>
  );
}
