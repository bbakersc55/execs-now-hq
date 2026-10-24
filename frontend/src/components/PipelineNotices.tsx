import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { Card, when } from "./ui";
import { api } from "../lib/api";

export interface PipelineNotice {
  id: string; text: string; created_at: string; contact: string | null; contact_name: string;
  pipeline: string;
}

/** Stage rules' notices to the person signed in (part 2, 2026-10-24): on Home
 *  until dismissed; the same ones arrive in one email a day. Nothing shows
 *  when there are none. */
export function PipelineNotices() {
  const qc = useQueryClient();
  const notices = useQuery<PipelineNotice[]>({
    queryKey: ["pipeline-notices"], queryFn: () => api.get<PipelineNotice[]>("/api/pipeline-notices/"),
  });
  const dismiss = useMutation({
    mutationFn: (id: string) => api.post(`/api/pipeline-notices/${id}/dismiss/`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pipeline-notices"] }),
  });
  const rows = notices.data ?? [];
  if (rows.length === 0) return null;
  return (
    <Card title="Notices" actions={<Link className="small" to="/rules">Stage rules</Link>}>
      <ul className="moves notices">
        {rows.map((n) => (
          <li key={n.id}>
            <span>
              {n.contact ? <Link to={`/contacts/${n.contact}`}>{n.text}</Link> : n.text}
              <span className="small muted"> · {n.pipeline ? `${n.pipeline} · ` : ""}{when(n.created_at)}</span>
            </span>
            <button className="ghost small" aria-label={`Dismiss: ${n.text}`} disabled={dismiss.isPending}
              onClick={() => dismiss.mutate(n.id)}>Dismiss</button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
