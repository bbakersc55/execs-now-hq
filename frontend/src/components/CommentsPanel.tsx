import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { Me, WorkComment, api } from "../lib/api";
import { Banner, Card, Empty, Flash, useFlash, when } from "./ui";

const TENANT = ["FF", "CF", "VA"];

type Person = { id: string; name: string };

/** The "@word" being typed just before the caret, or null. */
export function typingMention(text: string, caret: number): { start: number; query: string } | null {
  const before = text.slice(0, caret);
  const match = /(^|\s)@([^\s@]*)$/.exec(before);
  if (!match) return null;
  return { start: before.length - match[2].length - 1, query: match[2] };
}

/** Names whose first, last or any word starts with what is typed. */
export function suggest(people: Person[], query: string): Person[] {
  const q = query.toLowerCase();
  return people.filter((p) => (p.name ?? "").toLowerCase().split(/\s+/).some((w) => w.startsWith(q)))
    .slice(0, 6);
}

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
  const [posted, flashPosted] = useFlash();
  const isTenant = !!me.role && TENANT.includes(me.role);
  // A viewer reads the thread and adds nothing to it (P7 §2.4a).
  const mayPost = isTenant || me.portal?.may_comment !== false;
  const box = useRef<HTMLTextAreaElement>(null);
  const [typing, setTyping] = useState<{ start: number; query: string } | null>(null);
  const [active, setActive] = useState(0);

  // "@" suggestions (owner, 2026-10-27): only the people a mention would
  // tell, for the visibility being written; the server decides who.
  const visibility = isTenant && !shared ? "internal" : "shared";
  const people = useQuery<Person[]>({
    queryKey: ["mentionable", target, id, visibility],
    queryFn: () => api.get<Person[]>(
      `/api/comments/mentionable/?${target}=${id}&visibility=${visibility}`),
    enabled: mayPost,
  });
  const options = typing ? suggest(people.data ?? [], typing.query) : [];

  function edited(text: string, caret: number) {
    setBody(text);
    setTyping(typingMention(text, caret));
    setActive(0);
  }

  function pick(person: Person) {
    if (!typing) return;
    const end = typing.start + 1 + typing.query.length;
    const inserted = `@${person.name} `;
    const next = body.slice(0, typing.start) + inserted + body.slice(end);
    setBody(next);
    setTyping(null);
    const caret = typing.start + inserted.length;
    requestAnimationFrame(() => {
      box.current?.focus();
      box.current?.setSelectionRange(caret, caret);
    });
  }

  function keyed(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (!options.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((active + 1) % options.length); }
    else if (e.key === "ArrowUp") {
      e.preventDefault(); setActive((active - 1 + options.length) % options.length);
    } else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); pick(options[active]); }
    else if (e.key === "Escape") { e.preventDefault(); setTyping(null); }
  }

  const comments = useQuery<WorkComment[]>({
    queryKey: ["comments", target, id],
    queryFn: () => api.get<WorkComment[]>(`/api/comments/?${target}=${id}`),
  });

  const post = useMutation({
    mutationFn: () => api.post<WorkComment>("/api/comments/", {
      [target]: id, body, ...(isTenant ? { visibility: shared ? "shared" : "internal" } : {}),
    }),
    onSuccess: () => {
      flashPosted(shared && isTenant ? "Posted, shared with the client" : "Posted");
      setBody("");
      setShared(false);
      qc.invalidateQueries({ queryKey: ["comments", target, id] });
      qc.invalidateQueries({ queryKey: ["task-updates", id] });
    },
  });

  return (
    <Card title="Comments" actions={<Flash text={posted} />}>
      {(comments.data ?? []).length === 0 ? <Empty>No comments yet.</Empty> : (
        <div>
          {comments.data!.map((c) => (
            <div key={c.id} className={`comment ${c.visibility}`}>
              <div style={{ whiteSpace: "pre-wrap" }}>{c.body}</div>
              <div className="when muted small">
                {c.acting_user ? `${c.acting_user.name} on behalf of ${c.author.name}` : c.author.name}
                {" "}· {when(c.created_at)} ·{" "}
                {c.visibility === "shared" ? "shared with the client" : "internal only"}
              </div>
            </div>
          ))}
        </div>
      )}

      {mayPost && <>
      <div className="mention-wrap">
        <textarea ref={box} aria-label="Add a comment" rows={3} value={body}
          placeholder="Add a comment… type @ to mention someone"
          aria-autocomplete="list"
          aria-controls={options.length ? "mention-options" : undefined}
          onKeyDown={keyed} onBlur={() => setTyping(null)}
          onChange={(e) => edited(e.target.value, e.target.selectionStart ?? e.target.value.length)} />
        {options.length > 0 && (
          <ul id="mention-options" role="listbox" aria-label="People to mention"
            className="mention-options">
            {options.map((p, i) => (
              <li key={p.id} role="option" aria-selected={i === active}
                className={i === active ? "active" : ""}
                onMouseDown={(e) => { e.preventDefault(); pick(p); }}>{p.name}</li>
            ))}
          </ul>
        )}
      </div>
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
      </>}
    </Card>
  );
}
