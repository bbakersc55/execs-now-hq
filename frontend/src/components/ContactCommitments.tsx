import { useQuery } from "@tanstack/react-query";

import { CommitmentList } from "./CommitmentList";
import { Card } from "./ui";
import { Commitment, api } from "../lib/api";

/** What this person said they would do, from meetings (2026-09-28). Shown
 *  only when there is something: most contacts owe nothing. */
export function ContactCommitments({ contactId }: { contactId: string }) {
  const rows = useQuery<Commitment[]>({
    queryKey: ["commitments", "contact", contactId],
    queryFn: () => api.get<Commitment[]>(`/api/commitments/?contact=${contactId}&state=all`),
  });
  const list = rows.data ?? [];
  if (list.length === 0) return null;
  return (
    <Card title="Commitments">
      <CommitmentList rows={list} showPerson={false} />
    </Card>
  );
}

/** What a client is waiting on from the practice (2026-10-20): the tasks
 *  ticked "Promised to <company>" in the meeting queue, done when the task is.
 *  Shown only when there is something. */
export function CompanyCommitments({ companyId }: { companyId: string }) {
  const rows = useQuery<Commitment[]>({
    queryKey: ["commitments", "company", companyId, "ours"],
    queryFn: () => api.get<Commitment[]>(
      `/api/commitments/?company=${companyId}&side=ours&state=all`),
  });
  const list = rows.data ?? [];
  if (list.length === 0) return null;
  return (
    <Card title="Waiting on us">
      <CommitmentList rows={list} showPerson={false} />
    </Card>
  );
}
