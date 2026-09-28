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
