import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Me, Stakeholder, StakeholderCandidates, api } from "../lib/api";
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
 *
 * Who can be added is scoped by the server: for work at a client company, that
 * company's contacts, listed without typing; "someone outside" is an explicit,
 * typed search for the fractional's own boss or a board member. Internal work
 * searches anyone. It used to search every contact in the tenant, so a client's
 * task offered other clients' people.
 */
export function StakeholdersPanel({ me, target, id }: {
  me: Me; target: "task" | "project" | "goal"; id: string;
}) {
  const qc = useQueryClient();
  const [term, setTerm] = useState("");
  const [outside, setOutside] = useState(false);
  const [message, setMessage] = useState("");
  const isTenant = !!me.role && TENANT.includes(me.role);

  const rows = useQuery<Stakeholder[]>({
    queryKey: ["stakeholders", target, id],
    queryFn: () => api.get<Stakeholder[]>(
      target === "task" ? `/api/stakeholders/?effective=${id}` : `/api/stakeholders/?${target}=${id}`),
  });
  const query = new URLSearchParams({ [target]: id });
  if (outside) query.set("outside", "1");
  if (term.trim()) query.set("q", term.trim());
  const found = useQuery<StakeholderCandidates>({
    queryKey: ["stakeholder-candidates", target, id, outside, term.trim()],
    queryFn: () => api.get<StakeholderCandidates>(`/api/stakeholders/candidates/?${query}`),
    enabled: isTenant,
  });
  // The default list, which also names the company. It stays cached while a
  // typed search loads, so the box is never unmounted mid-word: anchoring the
  // section on the search itself dropped the input on every keystroke.
  const anchor = useQuery<StakeholderCandidates>({
    queryKey: ["stakeholder-candidates", target, id, false, ""],
    queryFn: () => api.get<StakeholderCandidates>(
      `/api/stakeholders/candidates/?${new URLSearchParams({ [target]: id })}`),
    enabled: isTenant,
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

  const company = anchor.data?.company_name ?? "";
  const anchored = !!anchor.data?.company;
  const attached = new Set((rows.data ?? []).map((r) => r.contact.id));
  const offered = (found.data?.people ?? []).filter((p) => !attached.has(p.contact));
  const typedEnough = term.trim().length >= 2;
  const searching = found.isFetching;

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

      {isTenant && anchor.data && (
        <>
          {anchored && (
            <label className="small" style={{ display: "inline-flex", gap: ".4rem", alignItems: "center" }}>
              <input type="checkbox" style={{ width: "auto" }} checked={outside}
                aria-label={`Someone outside ${company}`}
                onChange={(e) => { setOutside(e.target.checked); setTerm(""); }} />
              Someone outside {company} — your own boss, a board member
            </label>
          )}
          <Field label={anchored && !outside ? `Add someone from ${company}` : "Add someone by name"}>
            <input
              aria-label={anchored && !outside ? `Narrow ${company}'s people` : "Find a contact to add"}
              placeholder={anchored && !outside ? "Narrow by name or email…" : "Start typing a name…"}
              value={term} onChange={(e) => setTerm(e.target.value)} />
          </Field>
          {offered.length === 0 ? searching ? (
            <p className="small muted">Looking…</p>
          ) : (
            <p className="small muted">
              {anchored && !outside
                ? (term.trim() ? `Nobody at ${company} matches “${term.trim()}”.`
                               : `Everyone at ${company} is already here, or it has no contacts yet.`)
                : (typedEnough ? `Nobody matches “${term.trim()}”.`
                               : "Type at least two letters of their name.")}
            </p>
          ) : (
            <ul className="small" style={{ listStyle: "none", paddingLeft: 0 }}>
              {offered.map((p) => (
                <li key={p.contact} style={{ padding: ".15rem 0" }}>
                  <button className="ghost small" disabled={add.isPending}
                    aria-label={`Add ${p.name}${p.is_practice ? " (practice)" : ""}`}
                    onClick={() => add.mutate(p.contact)}>Add</button>{" "}
                  {p.name}{p.is_practice && <strong> (practice)</strong>}
                  {(outside || !anchored) && p.company_name && (
                    <span className="muted"> · {p.company_name}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          <p className="small muted">
            They need no login: digests go to the contact's email. Weekly unless you change it,
            and they can change it themselves from any email we send.
          </p>
        </>
      )}
    </Card>
  );
}
