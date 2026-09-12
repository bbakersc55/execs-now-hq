import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Me, WorkComment, api } from "../lib/api";
import { Banner, Card, Empty, when } from "./ui";

const TENANT = ["FF", "CF", "VA"];

/**
 * FR-3.12 / FR-3.12a — comments on a task, project or goal.
 *
 * A tenant user's comment **defaults to internal** and the current choice is
 * unmistakable before posting: a comment meant for the client that stayed
 * internal gets noticed and reposted, while an internal remark that reached
 * the client cannot be recalled. A client user has no choice to make — theirs
 * are always shared — so they are shown no control.
 */
export function CommentsPanel({ me, target, id }: {
  me: Me; target: "task" | "project" | "goal"; id: string;
}) {
  const qc = useQueryClient();
  const [body, setBody] = useState("");
  const [shared, setShared] = useState(false);
  const isTenant = !!me.role && TENANT.includes(me.role);

  const comments = useQuery<WorkComment[]>({
    queryKey: ["comments", target, id],
    queryFn: () => api.get<WorkComment[]>(`/api/comments/?${target}=${id}`),
  });

  const post = useMutation({
    mutationFn: () => api.post<WorkComment>("/api/comments/", {
      [target]: id, body, ...(isTenant ? { visibility: shared ? "shared" : "internal" } : {}),
    }),
    onSuccess: () => {
      setBody("");
      setShared(false);
      qc.invalidateQueries({ queryKey: ["comments", target, id] });
      qc.invalidateQueries({ queryKey: ["task-updates", id] });
    },
  });

  return (
    <Card title="Comments">
      {(comments.data ?? []).length === 0 ? <Empty>No comments yet.</Empty> : (
        <div>
          {comments.data!.map((c) => (
            <div key={c.id} className={`comment ${c.visibility}`}>
              <div style={{ whiteSpace: "pre-wrap" }}>{c.body}</div>
              <div className="when muted small">
                {c.author.name} · {when(c.created_at)} ·{" "}
                {c.visibility === "shared" ? "shared with the client" : "internal only"}
              </div>
            </div>
          ))}
        </div>
      )}

      <textarea aria-label="Add a comment" rows={3} value={body}
        placeholder="Add a comment…" onChange={(e) => setBody(e.target.value)} />
      {isTenant ? (
        <>
          <label style={{ display: "inline-flex", gap: ".4rem", alignItems: "center" }}>
            <input type="checkbox" checked={shared} aria-label="Share this comment with the client"
              onChange={(e) => setShared(e.target.checked)} style={{ width: "auto" }} />
            Share this comment with the client
          </label>
          <Banner kind={shared ? "warn" : "info"}>
            {shared
              ? "The client will see this comment."
              : "Internal only — the client will not see this."}
          </Banner>
        </>
      ) : (
        <p className="small muted">Your comments are shared with the practice.</p>
      )}
      <button className="primary" disabled={!body.trim() || post.isPending}
        onClick={() => post.mutate()}>
        {shared && isTenant ? "Post shared comment" : "Post comment"}
      </button>
    </Card>
  );
}
