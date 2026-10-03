import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { PageHead } from "../components/shell";
import { Banner, Card, Empty, Pill, when } from "../components/ui";
import { api } from "../lib/api";

interface Row {
  id: string; practice_name: string; role: string; doing: string; happened: string;
  expected: string; page_url: string; status: "new" | "seen" | "closed";
  has_screenshot: boolean; created_at: string;
}

/** The Practices area's Feedback (P2 §7): what practice staff chose to send. */
export function PlatformFeedback() {
  const qc = useQueryClient();
  const list = useQuery<Row[]>({
    queryKey: ["platform-feedback"], queryFn: () => api.get<Row[]>("/api/platform/feedback"),
  });
  const mark = useMutation({
    mutationFn: ({ id, status }: { id: string; status: Row["status"] }) =>
      api.patch(`/api/platform/feedback/${id}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["platform-feedback"] }),
  });
  const rows = list.data ?? [];
  return (
    <>
      <PageHead title="Feedback" sub="What practice staff sent with the Feedback button." />
      {list.isError && <Banner kind="bad">{(list.error as Error).message}</Banner>}
      {rows.length === 0 ? <Empty>No feedback yet.</Empty> : rows.map((r) => (
        <Card key={r.id} title={`${r.practice_name} · ${r.role}`}
          actions={<Pill kind={r.status === "new" ? "warn" : ""}>{r.status}</Pill>}>
          <p className="small muted" style={{ marginTop: 0 }}>{when(r.created_at)} · {r.page_url}</p>
          <p><strong>Doing:</strong> {r.doing}</p>
          <p><strong>What happened:</strong> {r.happened}</p>
          <p><strong>Expected:</strong> {r.expected}</p>
          {r.has_screenshot && (
            <p><a href={`/api/platform/feedback/${r.id}`} target="_blank" rel="noreferrer">
              Open the screenshot</a></p>
          )}
          <div className="row" style={{ gap: "0.5rem" }}>
            {r.status !== "seen" && <button className="ghost" disabled={mark.isPending}
              onClick={() => mark.mutate({ id: r.id, status: "seen" })}>Mark seen</button>}
            {r.status !== "closed" && <button className="ghost" disabled={mark.isPending}
              onClick={() => mark.mutate({ id: r.id, status: "closed" })}>Close</button>}
          </div>
        </Card>
      ))}
    </>
  );
}
