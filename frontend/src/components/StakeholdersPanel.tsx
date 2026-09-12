import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Contact, Me, Stakeholder, api } from "../lib/api";
import { Banner, Card, Empty, Field, when } from "./ui";

const TENANT = ["FF", "CF", "VA"];
const CADENCES: Stakeholder["cadence"][] = ["every_update", "weekly", "monthly"];
const CADENCE_LABELS: Record<string, string> = {
  every_update: "On every update", weekly: "Weekly", monthly: "Monthly",
};

/**
 * FR-3.20/3.20a — who hears about this work.
 *
 * A stakeholder is a **contact, not a login**: the client's CFO who reads the
 * Friday email and never opens the portal is the common case. On a task the
 * list shows the *effective* stakeholders — everyone reached through the task,
 * its project and its goal, with the most specific attachment deciding cadence.
 */
export function StakeholdersPanel({ me, target, id }: {
  me: Me; target: "task" | "project" | "goal"; id: string;
}) {
  const qc = useQueryClient();
  const [term, setTerm] = useState("");
  const [message, setMessage] = useState("");
  const isTenant = !!me.role && TENANT.includes(me.role);

  const rows = useQuery<Stakeholder[]>({
    queryKey: ["stakeholders", target, id],
    queryFn: () => api.get<Stakeholder[]>(
      target === "task" ? `/api/stakeholders/?effective=${id}` : `/api/stakeholders/?${target}=${id}`),
  });
  const found = useQuery<{ contacts: Contact[] }>({
    queryKey: ["stakeholder-search", term],
    queryFn: () => api.get(`/api/contacts/search/?q=${encodeURIComponent(term)}`),
    enabled: isTenant && term.trim().length > 1,
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["stakeholders", target, id] });
  const add = useMutation({
    mutationFn: (contact: string) =>
      api.post("/api/stakeholders/", { contact, [target]: id }),
    onSuccess: () => { setTerm(""); setMessage(""); refresh(); },
    onError: (e: Error) => setMessage(e.message),
  });
  const change = useMutation({
    mutationFn: ({ row, cadence }: { row: Stakeholder; cadence: string }) =>
      api.patch(`/api/stakeholders/${row.id}/`, { cadence }),
    onSuccess: refresh,
    onError: (e: Error) => setMessage(e.message),
  });
  const remove = useMutation({
    mutationFn: (row: Stakeholder) => api.del(`/api/stakeholders/${row.id}/`),
    onSuccess: refresh,
    onError: (e: Error) => setMessage(e.message),
  });

  return (
    <Card title="Who hears about this">
      {message && <Banner kind="bad">{message}</Banner>}
      {(rows.data ?? []).length === 0 ? <Empty>Nobody yet.</Empty> : (
        <table>
          <thead><tr><th>Person</th><th>How often</th><th>Attached to</th><th></th></tr></thead>
          <tbody>
            {rows.data!.map((row) => (
              <tr key={row.id}>
                <td>{row.contact.name}{row.is_muted && <span className="pill"> stopped</span>}</td>
                <td>
                  {isTenant ? (
                    <select aria-label={`How often ${row.contact.name} hears`}
                      value={row.cadence}
                      onChange={(e) => change.mutate({ row, cadence: e.target.value })}>
                      {CADENCES.map((c) => (
                        <option key={c} value={c}>{CADENCE_LABELS[c]}</option>
                      ))}
                    </select>
                  ) : CADENCE_LABELS[row.cadence]}
                </td>
                <td className="small muted">
                  {row.level}
                  {target === "task" && row.level !== "task" && " (inherited)"}
                </td>
                <td className="small muted">
                  {row.last_notified_at ? `last told ${when(row.last_notified_at)}` : "not yet told"}
                  {isTenant && row.level === target && (
                    <> · <button className="ghost small" onClick={() => remove.mutate(row)}>
                      remove
                    </button></>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {isTenant && (
        <>
          <Field label="Add someone by name">
            <input aria-label="Find a contact to add" placeholder="Start typing a name…"
              value={term} onChange={(e) => setTerm(e.target.value)} />
          </Field>
          <ul className="small" style={{ listStyle: "none", paddingLeft: 0 }}>
            {(found.data?.contacts ?? []).slice(0, 6).map((c) => (
              <li key={c.id}>
                <button className="ghost small" onClick={() => add.mutate(c.id)}>
                  {c.first_name} {c.last_name}
                </button>
              </li>
            ))}
          </ul>
          <p className="small muted">
            They need no login: digests go to the contact's email. Weekly unless you change it,
            and they can change it themselves from any email we send.
          </p>
        </>
      )}
    </Card>
  );
}
