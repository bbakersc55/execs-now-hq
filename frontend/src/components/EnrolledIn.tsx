import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Banner, Card, Empty, when } from "./ui";
import { Me, api } from "../lib/api";

export interface EnrollmentRow {
  /** "referral_touches", or "digest" for a stakeholder attachment. */
  kind: string;
  id: string;
  label: string;
  detail: string;
  since: string;
  by: string;
}

/**
 * Everything this person is on, in one place, each with the way off (owner,
 * 2026-09-28). Referral touches only ever because someone enrolled them;
 * digests because someone attached them to a task, project or goal.
 *
 * Changing it is the FF's or a CF's — the list itself is for everyone who
 * can open the contact, so nobody emails someone without seeing what they
 * are already getting.
 */
export function EnrolledIn({ contactId, me, isPartner }: {
  contactId: string; me: Me; isPartner: boolean;
}) {
  const qc = useQueryClient();
  const mayChange = me.role === "FF" || me.role === "CF";
  const rows = useQuery<EnrollmentRow[]>({
    queryKey: ["enrollments", contactId],
    queryFn: () => api.get<EnrollmentRow[]>(`/api/contacts/${contactId}/enrollments/`),
  });
  const done = () => {
    qc.invalidateQueries({ queryKey: ["enrollments", contactId] });
    qc.invalidateQueries({ queryKey: ["contact", contactId] });
    qc.invalidateQueries({ queryKey: ["contacts"] });
  };
  const change = useMutation({
    mutationFn: ({ path, body }: { path: "enroll" | "unenroll"; body: object }) =>
      api.post(`/api/contacts/${contactId}/${path}/`, body),
    onSuccess: done,
  });
  // What they have left, by their own link (owner, 2026-09-28). Shown so no
  // one wonders why an email to them was refused; only their link undoes it.
  const suppressions = useQuery<{ category: string; label: string; date: string }[]>({
    queryKey: ["suppressions", contactId],
    queryFn: () => api.get(`/api/contacts/${contactId}/suppressions/`),
  });
  const list = rows.data ?? [];
  const onTouches = list.some((r) => r.kind === "referral_touches");

  return (
    <Card title="Enrolled in">
      {list.length === 0 ? <Empty>Not enrolled in any email.</Empty> : (
        <ul className="enrolments">
          {list.map((row) => (
            <li key={`${row.kind}-${row.id}`}>
              <div>
                <strong>{row.label}</strong>
                <div className="small muted">
                  {row.detail && <>{row.detail} · </>}since {when(row.since)}
                  {row.by && <> · by {row.by}</>}
                </div>
              </div>
              {mayChange && (
                <button className="small" disabled={change.isPending}
                  aria-label={`Unenroll from ${row.label}`}
                  onClick={() => change.mutate({ path: "unenroll", body:
                    row.kind === "digest" ? { stakeholder: row.id } : { program: row.kind } })}>
                  Unenroll
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {(suppressions.data ?? []).map((row) => (
        <Banner key={row.category} kind="warn">
          Unsubscribed from {row.label} on {row.date}, by their own link. The app will not
          send them {row.label}.
        </Banner>
      ))}
      {mayChange && isPartner && !onTouches && (
        <button onClick={() => change.mutate({ path: "enroll",
                                                body: { program: "referral_touches" } })}
          disabled={change.isPending}>
          Enroll in referral touches
        </button>
      )}
      {change.isError && <Banner kind="bad">{(change.error as Error).message}</Banner>}
    </Card>
  );
}
